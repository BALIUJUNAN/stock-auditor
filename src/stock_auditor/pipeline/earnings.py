"""财报季节奏：披露前 7 个交易日提醒、披露后 T+1 全量重算。"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import structlog

from stock_auditor import paths
from stock_auditor.config import Settings, load_industry_peg
from stock_auditor.feishu.actions import ALERT_BUTTONS
from stock_auditor.feishu.base import FeishuChannel, FeishuError
from stock_auditor.feishu.factory import create_feishu_channel
from stock_auditor.ingest import run_ingest
from stock_auditor.llm.audit import LlmCompleter
from stock_auditor.pipeline.core import core_pool
from stock_auditor.pipeline.loader import load_universe
from stock_auditor.pipeline.lock import FileLock
from stock_auditor.pipeline.outbox import deliver, enqueue, pending_count
from stock_auditor.pipeline.run_context import RunContext
from stock_auditor.pipeline.single import StockReview, review_stock
from stock_auditor.report.cards import build_alert_card, build_text_card
from stock_auditor.scoring import (
    FundamentalResult,
    MomentumResult,
    QuantScore,
    score_fundamentals,
    score_momentum,
    store_quant_scores,
)

log = structlog.get_logger(__name__)

PIPELINE = "earnings"
EARNINGS_TAG = "即将披露财报，谨防变脸"
STATE_FILENAME = "earnings.json"
_MAX_DONE_KEYS = 2000

IngestCallable = Callable[[duckdb.DuckDBPyConnection, Settings, list[str]], Any]


@dataclass(frozen=True)
class EarningsWarning:
    code: str
    name: str
    report_period: date
    scheduled_date: date
    trading_days: int
    tag: str = EARNINGS_TAG


@dataclass(frozen=True)
class EarningsRecalc:
    code: str
    name: str
    report_period: date
    actual_date: date
    key: str


@dataclass(frozen=True)
class EarningsResult:
    run_id: str
    as_of: date
    warnings: tuple[EarningsWarning, ...]
    due: tuple[EarningsRecalc, ...]
    recalculated: tuple[str, ...]
    reviews: dict[str, StockReview]
    pushed_count: int


def state_path() -> Path:
    return paths.state_dir() / STATE_FILENAME


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


def mark_recomputed(key: str, *, path: Path | None = None) -> None:
    state = _load_state(path)
    done = [str(item) for item in state.get("recomputed", []) if isinstance(item, str)]
    if key not in done:
        done.append(key)
    state["recomputed"] = done[-_MAX_DONE_KEYS:]
    _save_state(state, path)


def next_trading_days(as_of: date, count: int) -> tuple[date, ...]:
    """按工作日近似交易日（任务书未要求节假日日历）。"""
    days: list[date] = []
    cursor = as_of
    while len(days) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return tuple(days)


def trading_days_until(as_of: date, target: date, *, limit: int = 10) -> int:
    cursor = as_of
    count = 0
    while cursor < target and count <= limit:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            count += 1
    return count


def check_earnings(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    codes: Sequence[str],
    *,
    as_of: date,
) -> tuple[EarningsWarning, ...]:
    """返回 7 个交易日内即将披露的核心池股票。"""
    if not codes:
        return ()
    placeholders = ", ".join("?" for _ in codes)
    window = next_trading_days(as_of, settings.earnings.warn_trading_days_before)
    if not window:
        return ()
    window_end = window[-1]
    rows = connection.execute(
        "SELECT e.code, COALESCE(u.name, ''), e.report_period, e.scheduled_date "
        "FROM earnings_calendar e "
        "LEFT JOIN stock_universe u ON u.code = e.code "
        f"WHERE e.code IN ({placeholders}) AND e.actual_date IS NULL "
        "AND e.scheduled_date > ? AND e.scheduled_date <= ? "
        "ORDER BY e.scheduled_date, e.code",
        [*codes, as_of, window_end],
    ).fetchall()
    return tuple(
        EarningsWarning(
            code=str(code),
            name=str(name),
            report_period=period,
            scheduled_date=scheduled,
            trading_days=trading_days_until(as_of, scheduled),
        )
        for code, name, period, scheduled in rows
    )


def recompute_due(
    connection: duckdb.DuckDBPyConnection,
    codes: Sequence[str],
    *,
    as_of: date,
    path: Path | None = None,
) -> tuple[EarningsRecalc, ...]:
    """实际披露日在 ``as_of`` 之前、且尚未重算过的核心池股票。"""
    if not codes:
        return ()
    done = {str(item) for item in _load_state(path).get("recomputed", []) if isinstance(item, str)}
    placeholders = ", ".join("?" for _ in codes)
    rows = connection.execute(
        "SELECT e.code, COALESCE(u.name, ''), e.report_period, e.actual_date "
        "FROM earnings_calendar e "
        "LEFT JOIN stock_universe u ON u.code = e.code "
        f"WHERE e.code IN ({placeholders}) AND e.actual_date IS NOT NULL "
        "AND e.actual_date < ? "
        "ORDER BY e.actual_date, e.code, e.report_period",
        [*codes, as_of],
    ).fetchall()
    result: list[EarningsRecalc] = []
    for code, name, period, actual in rows:
        key = f"{code}:{period.isoformat()}:{actual.isoformat()}"
        if key in done:
            continue
        result.append(
            EarningsRecalc(
                code=str(code),
                name=str(name),
                report_period=period,
                actual_date=actual,
                key=key,
            )
        )
    return tuple(result)


def _quant_row(
    code: str,
    fundamental: FundamentalResult,
    momentum: MomentumResult,
) -> QuantScore:
    raw_values = dict(fundamental.raw_values)
    raw_values.update({f"momentum_{key}": value for key, value in momentum.raw.items()})
    return QuantScore(
        code=code,
        fundamental=fundamental.total,
        momentum=momentum.score,
        raw_values=raw_values,
        industry_percentiles=dict(fundamental.percentiles),
        scores={
            "profitability": fundamental.profitability,
            "growth": fundamental.growth,
            "valuation": fundamental.valuation,
            "health": fundamental.health,
            "momentum_base": momentum.base,
            "momentum_penalty": momentum.penalty,
        },
        is_imputed=dict(fundamental.imputed),
        tags=[*fundamental.tags, *momentum.tags],
        data_flag=None,
    )


def recalculate_stock(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    code: str,
    *,
    as_of: date,
    run_id: str,
    client: LlmCompleter | None = None,
    prompt_dir: Path | None = None,
    ingest: IngestCallable | None = None,
) -> StockReview:
    """S1 单股刷新 → 全市场截面量化 → 该股 S5~S8。"""
    if ingest is not None:
        summary = ingest(connection, settings, [code])
    else:
        summary = run_ingest(connection, settings, codes=[code])
    if getattr(summary, "errors", None):
        raise RuntimeError(f"财报重算数据刷新失败: {summary.errors}")

    universe = load_universe(connection, as_of=as_of)
    data = universe.data.get(code)
    if data is None:
        raise ValueError(f"股票池中没有该代码：{code}")
    fundamentals = score_fundamentals(
        list(universe.data.values()),
        settings,
        load_industry_peg(),
        as_of,
        peer_data=[
            item
            for item in universe.data.values()
            if not item.stock.is_st
            and item.stock.list_date is not None
            and (as_of - item.stock.list_date).days >= 365
        ],
    )
    fundamental = fundamentals.get(code)
    if fundamental is None:
        raise ValueError(f"无法计算基本面分：{code}")
    momentum = score_momentum(data.quotes, settings)
    store_quant_scores(
        connection,
        run_id,
        [_quant_row(code, fundamental, momentum)],
    )
    return review_stock(
        connection,
        settings,
        code,
        as_of=as_of,
        client=client,
        run_id=run_id,
        prompt_dir=prompt_dir,
        quant=(fundamental, momentum, None),
    )


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
    lines.append(f"**审计**：{review.audit_status}")
    if review.tier2 is not None:
        lines.append("**看空理由**")
        lines.extend(
            f"- {item.text}（{', '.join(item.fact_ids)}）" for item in review.tier2.bear_points[:2]
        )
        if review.tier2.risk_tags:
            tags = "、".join(f"{item.tag}({item.severity})" for item in review.tier2.risk_tags)
            lines.append(f"**风险标签**：{tags}")
    if review.warnings:
        lines.extend(f"- {warning}" for warning in review.warnings)
    return "\n".join(lines)


def _buttons(channel: FeishuChannel | None) -> tuple[dict[str, str], ...]:
    return ALERT_BUTTONS if channel is not None and channel.name == "app" else ()


def build_warning_card(warnings: Sequence[EarningsWarning]) -> dict[str, Any]:
    lines = [f"**核心池中有 {len(warnings)} 只股票临近财报披露：**", ""]
    lines.extend(
        f"- {item.code} {item.name}：{item.scheduled_date} 披露"
        f"（{item.trading_days} 个交易日内）—— {item.tag}"
        for item in warnings
    )
    return build_text_card(
        title="财报临近提醒",
        markdown="\n".join(lines),
        template="orange",
    )


def build_recalc_card(
    review: StockReview,
    recalc: EarningsRecalc,
    *,
    as_of: date,
    channel: FeishuChannel | None = None,
) -> dict[str, Any]:
    detail = (
        f"**{recalc.report_period} 报告已披露（实际披露 {recalc.actual_date}），"
        "已按最新数据全量重算。**\n\n"
        f"{_review_summary(review)}"
    )
    return build_alert_card(
        code=review.code,
        name=review.name,
        title="财报披露后重算",
        detail=detail,
        as_of=as_of.isoformat(),
        buttons=_buttons(channel),
    )


def _send(channel: FeishuChannel | None, cards: Iterable[dict[str, Any]]) -> int:
    if channel is None or not channel.configured:
        return 0
    sent = 0
    for card in cards:
        try:
            channel.send_card(card)
            sent += 1
        except FeishuError as exc:
            log.warning("earnings.push_failed", error=str(exc))
    return sent


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        del args


def run_earnings(
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
    ingest: IngestCallable | None = None,
    use_lock: bool = True,
    queue_notifications: bool | None = None,
) -> EarningsResult:
    """手动执行财报流水线：提醒 + 对到期股票做 T+1 全量重算。"""
    moment = now or datetime.now()
    run_date = as_of or moment.date()
    lock = FileLock(PIPELINE) if use_lock else _NullLock()
    with lock:
        context = RunContext.start(PIPELINE, now=moment)
        context.save(connection)
        log.info("pipeline.earnings.start", run_id=context.run_id)
        target_channel = channel
        if push and target_channel is None:
            target_channel = create_feishu_channel()

        warnings: tuple[EarningsWarning, ...] = ()
        due: tuple[EarningsRecalc, ...] = ()
        recalculated: list[str] = []
        reviews: dict[str, StockReview] = {}
        cards: list[dict[str, Any]] = []
        try:
            pool = core_pool(connection, settings, as_of=run_date, codes=codes)
            context.begin_step("E1")
            warnings = check_earnings(connection, settings, pool, as_of=run_date)
            due = recompute_due(connection, pool, as_of=run_date, path=state_file)
            context.complete_step("E1")

            context.begin_step("E2")
            for item in due:
                try:
                    review = recalculate_stock(
                        connection,
                        settings,
                        item.code,
                        as_of=run_date,
                        run_id=context.run_id,
                        client=client,
                        prompt_dir=prompt_dir,
                        ingest=ingest,
                    )
                except Exception as exc:  # noqa: BLE001 - 单股失败不阻塞其余
                    log.error(
                        "pipeline.earnings.recalc_failed",
                        code=item.code,
                        error=str(exc),
                    )
                    context.fail_step("E2", f"{item.code}: {exc}")
                    continue
                context.add_usage(review.llm_tokens, review.llm_cost)
                reviews[item.code] = review
                recalculated.append(item.code)
                card = build_recalc_card(review, item, as_of=run_date, channel=target_channel)
                if queue_notifications if queue_notifications is not None else push:
                    enqueue(connection, card, key=f"earnings:{item.key}")
                mark_recomputed(item.key, path=state_file)
                cards.append(card)
            if "failed" not in context.step_status.get("E2", ""):
                context.complete_step("E2")

            context.begin_step("E3")
            if warnings:
                cards.append(build_warning_card(warnings))
            if warnings and push:
                enqueue(
                    connection,
                    cards[-1],
                    key=f"earnings-warning:{run_date}:{','.join(item.code for item in warnings)}",
                )
            pushed = deliver(connection, target_channel) if push else 0
            if push and pending_count(connection):
                context.fail_step("E3", "告警待投递，将在下次运行重试")
            else:
                context.complete_step("E3")
        except KeyboardInterrupt:
            context.fail("用户中断")
            context.save(connection)
            raise
        except Exception as exc:
            context.fail(str(exc))
            context.save(connection)
            log.error(
                "pipeline.earnings.failed",
                run_id=context.run_id,
                error=str(exc),
            )
            raise

        context.finish()
        context.save(connection)
        log.info(
            "pipeline.earnings.done",
            run_id=context.run_id,
            warnings=len(warnings),
            recalculated=len(recalculated),
            pushed=pushed,
        )
        return EarningsResult(
            run_id=context.run_id,
            as_of=run_date,
            warnings=warnings,
            due=due,
            recalculated=tuple(recalculated),
            reviews=reviews,
            pushed_count=pushed,
        )
