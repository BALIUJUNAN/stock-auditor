"""每日复盘：只扫描核心池，命中四类异动时重跑 S5~S8 并推送告警。

触发条件（任务书第 13 节）：
1. 新出现的重大公告关键词；
2. 最近交易日涨跌幅绝对值超过 ``daily_watch.abs_change_alert``；
3. 新触发动量破位；
4. 新触发硬 Veto。

财报检查随每日流水线执行：临近披露只提醒，实际披露后 T+1 全量重算。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import structlog

from stock_auditor import paths
from stock_auditor.config import Settings
from stock_auditor.domain import StockData
from stock_auditor.feishu.actions import ALERT_BUTTONS
from stock_auditor.feishu.base import FeishuChannel, FeishuError
from stock_auditor.feishu.factory import create_feishu_channel
from stock_auditor.feishu.ignored import ignored_codes
from stock_auditor.filters.veto import check_hard_veto
from stock_auditor.llm.audit import LlmCompleter
from stock_auditor.pipeline.core import core_pool
from stock_auditor.pipeline.earnings import (
    EarningsWarning,
    build_recalc_card,
    build_warning_card,
    check_earnings,
    recompute_due,
    run_earnings,
)
from stock_auditor.pipeline.loader import load_universe
from stock_auditor.pipeline.lock import FileLock
from stock_auditor.pipeline.run_context import RunContext
from stock_auditor.pipeline.single import StockReview, review_stock
from stock_auditor.report.cards import build_alert_card
from stock_auditor.scoring import score_momentum

log = structlog.get_logger(__name__)

PIPELINE = "daily"
STATE_FILENAME = "daily.json"
EARNINGS_STATE_FILENAME = "earnings.json"
_MAX_ANNOUNCEMENT_KEYS = 5000
_AUDIT_LABELS = {
    "ok": "LLM 审计完成",
    "audit_failed": "LLM 审计失败",
    "skipped": "未执行 LLM 审计",
}

_ANNOUNCEMENTS = "announcements"
_BREAKDOWN = "breakdown"
_VETO = "veto"
_MOVES = "moves"


def state_path() -> Path:
    return paths.state_dir() / STATE_FILENAME


def earnings_state_path() -> Path:
    return paths.state_dir() / EARNINGS_STATE_FILENAME


@dataclass(frozen=True)
class DailyTrigger:
    code: str
    name: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DailyResult:
    run_id: str
    as_of: date
    pool: tuple[str, ...]
    triggers: tuple[DailyTrigger, ...]
    reviews: dict[str, StockReview]
    ignored: tuple[str, ...]
    earnings_warnings: tuple[EarningsWarning, ...]
    earnings_recalculated: tuple[str, ...]
    pushed_count: int


def _load_state(path: Path | None) -> dict[str, Any]:
    target = Path(path) if path is not None else state_path()
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_state(state: dict[str, Any], path: Path | None) -> None:
    target = Path(path) if path is not None else state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _string_set(state: dict[str, Any], key: str) -> set[str]:
    value = state.get(key, [])
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str)}


def _announcement_key(code: str, day: date, title: str) -> str:
    return f"{code}|{day.isoformat()}|{title}"


def _new_announcements(
    data: StockData,
    settings: Settings,
    as_of: date,
    seen: set[str],
) -> tuple[list[str], set[str]]:
    cutoff = as_of - timedelta(days=settings.funnel.announcement_lookback_days)
    keywords = settings.funnel.major_announcement_keywords
    reasons: list[str] = []
    matched: set[str] = set()
    for row in data.announcements:
        if row.ann_date is None or not (cutoff <= row.ann_date <= as_of):
            continue
        if not any(keyword in row.title for keyword in keywords):
            continue
        key = _announcement_key(data.stock.code, row.ann_date, row.title)
        matched.add(key)
        if key not in seen:
            reasons.append(f"重大公告：{row.title}（{row.ann_date.isoformat()}）")
    return reasons, matched


def _price_move_reason(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> str | None:
    bars = [bar for bar in data.quotes if bar.trade_date <= as_of]
    if len(bars) < 2:
        return None
    latest, prior = bars[-1], bars[-2]
    if latest.trade_date != as_of or latest.is_suspended:
        return None
    if latest.close is None or prior.close in (None, 0):
        return None
    change = latest.close / prior.close - 1
    threshold = settings.daily_watch.abs_change_alert
    if abs(change) <= threshold:
        return None
    return f"单日涨跌幅 {change:+.2%}，超过 ±{threshold:.0%}"


def _move_key(code: str, as_of: date) -> str:
    return f"{code}|{as_of.isoformat()}"


def _prune_announcements(keys: set[str], cutoff: date) -> list[str]:
    kept = [
        key
        for key in keys
        if len(key.split("|")) == 3
        and _key_date(key) is not None
        and _key_date(key) >= cutoff
    ]
    return sorted(kept)[-_MAX_ANNOUNCEMENT_KEYS:]


def _key_date(key: str) -> date | None:
    try:
        return date.fromisoformat(key.split("|")[1])
    except (IndexError, ValueError):
        return None


def _scan_triggers(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    pool: Sequence[str],
    *,
    as_of: date,
    state: dict[str, Any],
) -> list[DailyTrigger]:
    """返回命中触发的股票，并把最新状态写回 ``state``。"""
    if not pool:
        return []

    universe = load_universe(connection, as_of=as_of, codes=list(pool))
    prior_breakdown = _string_set(state, _BREAKDOWN)
    prior_veto = _string_set(state, _VETO)
    prior_moves = _string_set(state, _MOVES)
    seen_announcements = _string_set(state, _ANNOUNCEMENTS)

    current_breakdown: set[str] = set()
    current_veto: set[str] = set()
    triggered: list[DailyTrigger] = []
    all_moves: set[str] = set()
    matched_announcements: set[str] = set()

    for code in pool:
        data = universe.data.get(code)
        if data is None:
            continue
        reasons: list[str] = []

        announcement_reasons, matched = _new_announcements(
            data, settings, as_of, seen_announcements
        )
        reasons.extend(announcement_reasons)
        matched_announcements.update(matched)

        move_reason = _price_move_reason(data, settings, as_of)
        move_key = _move_key(code, as_of)
        if move_reason is not None:
            all_moves.add(move_key)
            if move_key not in prior_moves:
                reasons.append(move_reason)

        momentum = score_momentum(data.quotes, settings)
        if "破位" in momentum.tags:
            current_breakdown.add(code)
            if code not in prior_breakdown:
                reasons.append("动量破位：放量跌破 MA60")

        for event in check_hard_veto(data, settings, as_of):
            key = f"{code}:{event.rule}"
            current_veto.add(key)
            if key not in prior_veto:
                reasons.append(f"新触发 Veto：{event.rule}（{event.detail}）")

        if reasons:
            triggered.append(
                DailyTrigger(
                    code=code,
                    name=data.stock.name,
                    reasons=tuple(reasons),
                )
            )

    state[_BREAKDOWN] = sorted(current_breakdown)
    state[_VETO] = sorted(current_veto)
    state[_MOVES] = sorted(all_moves)
    state[_ANNOUNCEMENTS] = _prune_announcements(
        seen_announcements | matched_announcements,
        as_of - timedelta(days=settings.funnel.announcement_lookback_days),
    )
    return triggered


def _review_summary(review: StockReview) -> str:
    lines: list[str] = []
    if review.fundamental is not None and review.momentum is not None:
        lines.append(
            f"**量化**：基本面 {review.fundamental.total:g}/40 · "
            f"动量 {review.momentum.score:g}/20 · "
            f"合计 {review.quant_total:g}/100"
        )
    final = review.final
    if final is not None:
        if final.is_veto:
            lines.append("**结论**：触发硬 Veto")
        elif final.final_total is None:
            lines.append("**结论**：待 LLM 审计给出前景分后定级")
        else:
            stars = "★" * final.stars if final.stars else "—"
            suffix = "（黄牌）" if final.is_yellow else ""
            lines.append(f"**综合**：{final.final_total:g} 分 · {stars}{suffix}")
    lines.append(
        f"**审计**：{_AUDIT_LABELS.get(review.audit_status, review.audit_status)}"
    )
    if review.tier2 is not None:
        lines.append("**看空理由**")
        lines.extend(
            f"- {item.text}（{', '.join(item.fact_ids)}）"
            for item in review.tier2.bear_points[:2]
        )
        if review.tier2.risk_tags:
            tags = "、".join(
                f"{item.tag}({item.severity})" for item in review.tier2.risk_tags
            )
            lines.append(f"**风险标签**：{tags}")
    if review.warnings:
        lines.extend(f"- {warning}" for warning in review.warnings)
    return "\n".join(lines)


def build_daily_card(
    trigger: DailyTrigger,
    review: StockReview,
    *,
    as_of: date,
    channel: FeishuChannel | None = None,
) -> dict[str, Any]:
    detail = "\n".join(
        [
            "**触发原因**",
            *(f"- {reason}" for reason in trigger.reasons),
            "",
            _review_summary(review),
        ]
    )
    return build_alert_card(
        code=trigger.code,
        name=trigger.name,
        title="每日异动提醒",
        detail=detail,
        as_of=as_of.isoformat(),
        buttons=_buttons(channel),
    )


def _buttons(channel: FeishuChannel | None) -> tuple[dict[str, str], ...]:
    return ALERT_BUTTONS if channel is not None and channel.name == "app" else ()


def _send(channel: FeishuChannel | None, cards: Sequence[dict[str, Any]]) -> int:
    if channel is None or not channel.configured:
        return 0
    sent = 0
    for card in cards:
        try:
            channel.send_card(card)
            sent += 1
        except FeishuError as exc:
            log.warning("daily.push_failed", error=str(exc))
    return sent


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        del args


def run_daily(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    *,
    as_of: date | None = None,
    codes: Sequence[str] | None = None,
    client: LlmCompleter | None = None,
    push: bool = True,
    channel: FeishuChannel | None = None,
    prompt_dir: Path | None = None,
    now: datetime | None = None,
    state_file: Path | None = None,
    ignored_path: Path | None = None,
    earnings_state_file: Path | None = None,
    ingest: Callable[..., Any] | None = None,
    use_lock: bool = True,
) -> DailyResult:
    """执行每日流水线：核心池异动告警 + 财报提醒与 T+1 重算。"""
    moment = now or datetime.now()
    run_date = as_of or moment.date()
    lock = FileLock(PIPELINE) if use_lock else _NullLock()
    with lock:
        context = RunContext.start(PIPELINE, now=moment)
        context.save(connection)
        log.info("pipeline.daily.start", run_id=context.run_id)

        target_channel = channel
        if push and target_channel is None:
            target_channel = create_feishu_channel()

        pool: tuple[str, ...] = ()
        triggers: list[DailyTrigger] = []
        reviews: dict[str, StockReview] = {}
        ignored: list[str] = []
        earnings_warnings: tuple[EarningsWarning, ...] = ()
        earnings_recalculated: tuple[str, ...] = ()
        cards: list[dict[str, Any]] = []
        pushed = 0

        try:
            context.begin_step("D1")
            pool = core_pool(
                connection, settings, as_of=run_date, codes=codes
            )
            state = _load_state(state_file)
            ignored_set = set(
                ignored_codes(path=ignored_path, as_of=run_date)
            )
            found = _scan_triggers(
                connection,
                settings,
                pool,
                as_of=run_date,
                state=state,
            )
            for item in found:
                if item.code in ignored_set:
                    ignored.append(item.code)
                    continue
                triggers.append(item)
            context.complete_step("D1")

            context.begin_step("D2")
            for item in triggers:
                try:
                    review = review_stock(
                        connection,
                        settings,
                        item.code,
                        as_of=run_date,
                        client=client,
                        run_id=context.run_id,
                        prompt_dir=prompt_dir,
                    )
                except Exception as exc:  # noqa: BLE001 - 单股失败不阻塞其余
                    log.error(
                        "pipeline.daily.review_failed",
                        code=item.code,
                        error=str(exc),
                    )
                    context.fail_step("D2", f"{item.code}: {exc}")
                    continue
                context.add_usage(review.llm_tokens, review.llm_cost)
                reviews[item.code] = review
                cards.append(
                    build_daily_card(
                        item,
                        review,
                        as_of=run_date,
                        channel=target_channel,
                    )
                )
            if "failed" not in context.step_status.get("D2", ""):
                context.complete_step("D2")

            context.begin_step("D3")
            try:
                earnings_warnings = check_earnings(
                    connection, settings, pool, as_of=run_date
                )
                due = recompute_due(
                    connection,
                    pool,
                    as_of=run_date,
                    path=earnings_state_file,
                )
                if due:
                    earnings_result = run_earnings(
                        connection,
                        settings,
                        as_of=run_date,
                        codes=list(pool),
                        client=client,
                        push=False,
                        channel=target_channel,
                        prompt_dir=prompt_dir,
                        now=moment,
                        state_file=earnings_state_file,
                        ingest=ingest,
                        use_lock=False,
                    )
                    earnings_warnings = earnings_result.warnings
                    earnings_recalculated = earnings_result.recalculated
                    context.add_usage(
                        sum(
                            review.llm_tokens
                            for review in earnings_result.reviews.values()
                        ),
                        sum(
                            review.llm_cost
                            for review in earnings_result.reviews.values()
                        ),
                    )
                    for item in earnings_result.due:
                        review = earnings_result.reviews.get(item.code)
                        if review is not None:
                            cards.append(
                                build_recalc_card(
                                    review,
                                    item,
                                    as_of=run_date,
                                    channel=target_channel,
                                )
                            )
                if earnings_warnings:
                    cards.append(build_warning_card(earnings_warnings))
                context.complete_step("D3")
            except Exception as exc:  # noqa: BLE001 - 财报检查不阻塞异动告警
                context.fail_step("D3", str(exc))
                log.error(
                    "pipeline.daily.earnings_failed",
                    run_id=context.run_id,
                    error=str(exc),
                )

            context.begin_step("D4")
            pushed = _send(target_channel, cards) if push else 0
            _save_state(state, state_file)
            context.complete_step("D4")
        except KeyboardInterrupt:
            context.fail("用户中断")
            context.save(connection)
            raise
        except Exception as exc:
            context.fail(str(exc))
            context.save(connection)
            log.error(
                "pipeline.daily.failed",
                run_id=context.run_id,
                error=str(exc),
            )
            raise

        context.finish()
        context.save(connection)
        log.info(
            "pipeline.daily.done",
            run_id=context.run_id,
            pool=len(pool),
            triggers=len(triggers),
            ignored=len(ignored),
            recalculated=len(earnings_recalculated),
            pushed=pushed,
        )
        return DailyResult(
            run_id=context.run_id,
            as_of=run_date,
            pool=pool,
            triggers=tuple(triggers),
            reviews=reviews,
            ignored=tuple(ignored),
            earnings_warnings=earnings_warnings,
            earnings_recalculated=earnings_recalculated,
            pushed_count=pushed,
        )
