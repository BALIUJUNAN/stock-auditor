"""财报预约披露日期采集（巨潮资讯，经 AKShare）。"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import DataClient, clean_text, normalize_code, to_date

log = structlog.get_logger(__name__)

EARNINGS_COLUMNS = ("code", "report_period", "scheduled_date", "actual_date")

_PERIOD_NAMES = {3: "一季", 6: "半年报", 9: "三季", 12: "年报"}
_SCHEDULE_KEYS = ("三次变更", "二次变更", "初次变更", "一次变更", "首次预约")


def _ak() -> Any:
    import akshare as ak

    return ak


def recent_quarter_ends(today: date, count: int = 4) -> list[date]:
    """返回不晚于今天的最近 ``count`` 个季度末，按时间倒序。"""
    ends: list[date] = []
    for year in range(today.year, today.year - 3, -1):
        for month in (12, 9, 6, 3):
            last_day = calendar.monthrange(year, month)[1]
            quarter_end = date(year, month, last_day)
            if quarter_end > today:
                continue
            ends.append(quarter_end)
            if len(ends) == count:
                return ends
    return ends


def period_label(quarter_end: date) -> str:
    """转换为巨潮接口的期间写法，如 ``2026三季``。"""
    return f"{quarter_end.year}{_PERIOD_NAMES[quarter_end.month]}"


def collect_earnings(
    client: DataClient,
    settings: Settings,
    codes: list[str] | None,
) -> list[tuple[Any, ...]]:
    """抓取最近四个报告期的预约与实际披露日期。"""
    del settings  # 期间数量由数据源“最近四期”约定决定
    allowed = {normalize_code(code) for code in codes} if codes is not None else None
    rows: list[tuple[Any, ...]] = []
    for quarter_end in recent_quarter_ends(date.today()):
        label = period_label(quarter_end)
        try:
            frame = client.call(
                lambda period=label: _ak().stock_report_disclosure(
                    market="沪深京", period=period
                ),
                description=f"预约披露 {label}",
            )
        except Exception as exc:  # noqa: BLE001 - 未发布期间失败不阻塞
            log.warning("ingest.earnings.failed", period=label, error=str(exc))
            continue
        if frame is None or getattr(frame, "empty", False):
            continue
        for record in frame.to_dict("records"):
            raw_code = clean_text(record.get("股票代码"))
            if raw_code is None:
                continue
            try:
                code = normalize_code(raw_code)
            except ValueError:
                continue
            if allowed is not None and code not in allowed:
                continue
            scheduled = None
            for key in _SCHEDULE_KEYS:
                scheduled = to_date(record.get(key))
                if scheduled is not None:
                    break
            rows.append(
                (
                    code,
                    quarter_end,
                    scheduled,
                    to_date(record.get("实际披露")),
                )
            )
    log.info("ingest.earnings.collected", rows=len(rows))
    return rows
