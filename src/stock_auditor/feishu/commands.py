"""飞书指令与按钮回调：``/查``、``/周报``、``/状态`` 与“加入关注/本周忽略”。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import structlog

from stock_auditor.config import Settings
from stock_auditor.db import connect
from stock_auditor.feishu.actions import BUTTON_IGNORE, BUTTON_WATCH
from stock_auditor.feishu.base import FeishuChannel
from stock_auditor.feishu.config import FeishuConfig, load_feishu_config
from stock_auditor.feishu.ignored import ignore_code, ignored_codes
from stock_auditor.funnel.watchlist import (
    WatchlistError,
    add_watch_entry,
)
from stock_auditor.ingest.common import normalize_code
from stock_auditor.llm.audit import LlmCompleter
from stock_auditor.pipeline.single import StockReview, review_stock
from stock_auditor.report.cards import build_main_card, build_text_card

log = structlog.get_logger(__name__)

USAGE = (
    "**可用指令**\n"
    "- `/查 000001`：即时审计单只股票（每人 10 分钟最多 1 次）\n"
    "- `/周报`：查看最近一期周报\n"
    "- `/状态`：查看系统与数据状态\n"
    "- `/帮助`：显示本说明"
)

_AUDIT_LABELS = {
    "ok": "LLM 审计完成",
    "failed": "LLM 审计失败",
    "skipped": "未执行 LLM 审计",
}


@dataclass
class CommandService:
    """解析并执行指令；返回卡片字典，由机器人层负责发送。

    传入 ``connection`` 时直接复用（测试/单进程内）；否则每次按默认路径打开数据库。
    """

    settings: Settings
    config: FeishuConfig | None = None
    connection: duckdb.DuckDBPyConnection | None = None
    channel: FeishuChannel | None = None
    client: LlmCompleter | None = None
    prompt_dir: Path | None = None
    watchlist_path: Path | None = None
    ignored_path: Path | None = None
    clock: Callable[[], datetime] = datetime.now
    query_interval: timedelta = timedelta(minutes=10)
    _last_query: dict[str, datetime] = field(
        default_factory=dict, init=False, repr=False
    )

    # ------------------------------------------------------------------ 权限

    def _feishu_config(self) -> FeishuConfig | None:
        if self.config is not None:
            return self.config
        return load_feishu_config()

    def authorized(self, *, chat_id: str, user_id: str) -> bool:
        """群与用户都必须在白名单内；任一白名单留空视为不启用指令。"""
        config = self._feishu_config()
        if config is None:
            return False
        if not config.allowed_chat_ids or not config.allowed_user_ids:
            return False
        return chat_id in config.allowed_chat_ids and user_id in config.allowed_user_ids

    # ------------------------------------------------------------------ 指令

    def handle_text(self, text: str, *, chat_id: str, user_id: str) -> dict[str, Any] | None:
        """处理文本消息；非指令或未授权返回 ``None``。"""
        stripped = (text or "").strip()
        if not stripped.startswith("/"):
            return None
        if not self.authorized(chat_id=chat_id, user_id=user_id):
            log.info("feishu.command.unauthorized", chat_id=chat_id, user_id=user_id)
            return None

        parts = stripped.split()
        command = parts[0]
        if command == "/查":
            return self._query(parts[1:], user_id=user_id)
        if command in ("/周报", "/weekly"):
            return self._weekly_card()
        if command in ("/状态", "/status"):
            return self._status_card()
        if command in ("/帮助", "/help", "/?"):
            return self._text("指令说明", USAGE, "blue")
        return self._text(
            "未知指令",
            f"不认识指令 `{command}`。\n\n{USAGE}",
            "orange",
        )

    def _query(self, args: list[str], *, user_id: str) -> dict[str, Any]:
        if len(args) != 1:
            return self._text("用法", "用法：`/查 000001`，一次只查询一只股票。", "orange")
        try:
            code = normalize_code(args[0])
        except ValueError as exc:
            return self._text("代码格式错误", str(exc), "orange")

        now = self.clock()
        last = self._last_query.get(user_id)
        if last is not None and now - last < self.query_interval:
            remaining = self.query_interval - (now - last)
            seconds = max(1, int(math.ceil(remaining.total_seconds())))
            minutes = int(self.query_interval.total_seconds() // 60)
            return self._text(
                "操作过于频繁",
                f"每 {minutes} 分钟只能查询一次，请在约 {seconds} 秒后重试。",
                "orange",
            )
        self._last_query[user_id] = now

        with self._db() as connection:
            try:
                review = review_stock(
                    connection,
                    self.settings,
                    code,
                    as_of=now.date(),
                    client=self.client,
                    prompt_dir=self.prompt_dir,
                )
            except ValueError as exc:
                return self._text("未找到股票", str(exc), "orange")
        return self._review_card(review)

    def _review_card(self, review: StockReview) -> dict[str, Any]:
        row = review.to_row()
        lines: list[str] = []
        if review.fundamental is not None and review.momentum is not None:
            lines.append(
                "**量化**："
                f"基本面 {review.fundamental.total:g}/40 · "
                f"动量 {review.momentum.score:g}/20 · "
                f"合计 {review.quant_total:g}/100"
            )
        else:
            lines.append("**量化**：暂无基本面分（未纳入最近一期周流水线）")

        final = review.final
        if final is not None:
            if final.is_veto:
                lines.append("**结论**：硬 Veto，不建议关注")
            elif final.final_total is None:
                lines.append("**综合**：待 LLM 审计给出前景分后定级")
            else:
                stars = "★" * final.stars if final.stars else "—"
                suffix = "（黄牌）" if final.is_yellow else ""
                lines.append(f"**综合**：{final.final_total:g} 分 · {stars}{suffix}")

        if review.tier2 is not None:
            lines.append(
                f"**前景**：{review.tier2.score} 分"
                f"（Tier {review.tier2.tier}，置信度 {review.tier2.confidence}）"
            )

        lines.append(
            f"**审计**：{_AUDIT_LABELS.get(review.audit_status, review.audit_status)}"
        )
        if review.data_flag:
            lines.append(f"**数据**：{review.data_flag}")

        if not review.stage0_passed:
            lines.append("\n**初筛**：未通过")
            lines.extend(f"- {reason}" for reason in review.stage0_reasons[:5])

        if review.tier2 is not None:
            lines.append("\n**看多理由**")
            lines.extend(
                f"- {item.text}（{', '.join(item.fact_ids)}）"
                for item in review.tier2.reasons[:3]
            )
            lines.append("\n**看空理由**")
            lines.extend(
                f"- {item.text}（{', '.join(item.fact_ids)}）"
                for item in review.tier2.bear_points[:2]
            )
            if review.tier2.risk_tags:
                tags = "、".join(
                    f"{item.tag}({item.severity})" for item in review.tier2.risk_tags
                )
                lines.append(f"\n**风险标签**：{tags}")

        evidence = row.get("evidence") or []
        if evidence:
            lines.append("\n**证据**")
            for item in evidence[:3]:
                lines.append(
                    f"- [{item['fact_id']}] {item['statement']}\n"
                    f"  > {item['quote']}"
                )

        if review.warnings:
            lines.append("\n**提示**")
            lines.extend(f"- {warning}" for warning in review.warnings)

        template = "blue"
        if review.hard_veto:
            template = "red"
        elif final is not None and final.final_total is not None and final.stars:
            if final.stars >= 4:
                template = "green"
            elif final.stars >= 1:
                template = "orange"
        return self._text(
            f"{review.name} {review.code} · 审计结果",
            "\n".join(lines),
            template,
        )

    def _weekly_card(self) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT run_id, report_json, markdown FROM weekly_reports "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None or (not row[1] and not row[2]):
            return self._text("周报", "暂无周报记录，请先运行 `sa run weekly`。", "orange")

        run_id, report_json, markdown = row
        payload = _payload(report_json)
        if payload and payload.get("main_markdown"):
            return build_main_card(payload, show_button=False)
        text = str(markdown or "")
        if len(text) > 3500:
            text = text[:3500] + "\n\n…（已截断，完整周报见 var/reports）"
        return self._text(f"周报 {run_id}", text, "blue")

    def _status_card(self) -> dict[str, Any]:
        now = self.clock()
        with self._db() as connection:
            rows = connection.execute(
                "SELECT pipeline, run_id, status, started_at FROM run_log "
                "WHERE pipeline IN ('weekly', 'daily') "
                "ORDER BY started_at DESC NULLS LAST"
            ).fetchall()
            universe = connection.execute(
                "SELECT count(*) FROM stock_universe"
            ).fetchone()[0]
        latest: dict[str, tuple[str, str, Any]] = {}
        for pipeline, run_id, status, started_at in rows:
            latest.setdefault(str(pipeline), (str(run_id), str(status), started_at))

        channel_status = self.channel.status if self.channel is not None else "未接入"
        tier1 = self.settings.llm.tier1_model or "未配置"
        tier2 = self.settings.llm.tier2_model or "未配置"
        lines = [
            f"**飞书通道**：{channel_status}",
            f"**模型**：Tier-1 `{tier1}` / Tier-2 `{tier2}`",
        ]
        for pipeline, label in (("weekly", "周报"), ("daily", "每日")):
            item = latest.get(pipeline)
            if item is None:
                lines.append(f"**最近{label}**：暂无记录")
                continue
            run_id, status, started_at = item
            if isinstance(started_at, datetime):
                started = started_at.strftime("%Y-%m-%d %H:%M")
            else:
                started = str(started_at or "-")
            lines.append(f"**最近{label}**：{run_id}（{status}，{started}）")
        ignored = ignored_codes(path=self.ignored_path, as_of=now.date())
        lines.append(f"**股票池**：{universe} 只")
        lines.append(f"**本周忽略**：{len(ignored)} 只")
        return self._text("系统状态", "\n".join(lines), "blue")

    # ------------------------------------------------------------------ 按钮

    def handle_action(
        self,
        action: str,
        code: str,
        *,
        chat_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """处理卡片按钮回调；未授权返回 ``None``。"""
        if not self.authorized(chat_id=chat_id, user_id=user_id):
            log.info(
                "feishu.action.unauthorized",
                action=action,
                chat_id=chat_id,
                user_id=user_id,
            )
            return None
        try:
            normalized = normalize_code(code)
        except ValueError as exc:
            return self._text("代码格式错误", str(exc), "orange")

        if action == BUTTON_WATCH:
            return self._watch(normalized)
        if action == BUTTON_IGNORE:
            created = ignore_code(
                normalized,
                path=self.ignored_path,
                as_of=self.clock().date(),
            )
            message = (
                f"本周将忽略 {normalized} 的异动提醒。"
                if created
                else f"{normalized} 已在本周忽略名单。"
            )
            return self._text("本周忽略", message, "grey")
        return self._text("未知操作", f"不认识按钮操作：`{action}`。", "orange")

    def _watch(self, code: str) -> dict[str, Any]:
        with self._db() as connection:
            row = connection.execute(
                "SELECT name FROM stock_universe WHERE code = ?", [code]
            ).fetchone()
        name = str(row[0]) if row is not None else None
        try:
            added = add_watch_entry(
                code,
                name=name,
                path=self.watchlist_path,
                max_entries=self.settings.funnel.watchlist_max,
            )
        except WatchlistError as exc:
            return self._text("加入关注失败", str(exc), "red")
        message = (
            f"已加入关注名单：{code} {name or ''}".strip()
            if added
            else f"已在关注名单：{code} {name or ''}".strip()
        )
        return self._text("关注名单", message, "green")

    # ------------------------------------------------------------------ 工具

    @contextmanager
    def _db(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if self.connection is not None:
            yield self.connection
        else:
            with connect() as connection:
                yield connection

    def _text(self, title: str, markdown: str, template: str) -> dict[str, Any]:
        return build_text_card(title=title, markdown=markdown, template=template)


def _payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
