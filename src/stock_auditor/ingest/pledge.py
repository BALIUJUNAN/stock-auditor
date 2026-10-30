"""股权质押比例采集：取最近一期（周频）全市场快照。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import (
    DataClient,
    clean_number,
    frame_records,
    normalize_code,
    to_date,
)

log = structlog.get_logger(__name__)

PLEDGE_COLUMNS = ("code", "date", "controlling_pledge_ratio")


def _ak() -> Any:
    import akshare as ak

    return ak


def snapshot_date(today: date) -> date:
    """最近一个已发布快照的周五；当天即使周五也回退 7 天（数据盘后更新）。"""
    days = (today.weekday() - 4) % 7 or 7
    return today - timedelta(days=days)


def candidate_snapshot_dates(today: date, lookback_days: int) -> list[date]:
    """按时间倒序返回回看范围内的周五。"""
    dates: list[date] = []
    cursor = snapshot_date(today)
    while (today - cursor).days <= lookback_days:
        dates.append(cursor)
        cursor -= timedelta(days=7)
    return dates


def collect_pledge(
    client: DataClient,
    settings: Settings,
    codes: list[str] | None,
) -> list[tuple[Any, ...]]:
    """抓取最近一期质押快照，按目标代码过滤。"""
    allowed = {normalize_code(code) for code in codes} if codes is not None else None
    frame = None
    used_date: date | None = None
    for candidate in candidate_snapshot_dates(
        date.today(), settings.ingest.pledge_snapshot_lookback_days
    ):
        text = candidate.strftime("%Y%m%d")
        result = client.call(
            lambda value=text: _ak().stock_gpzy_pledge_ratio_em(date=value),
            description=f"质押快照 {text}",
        )
        records = frame_records(result)
        if records:
            frame = records
            used_date = candidate
            break
    if frame is None:
        log.warning(
            "ingest.pledge.empty",
            lookback_days=settings.ingest.pledge_snapshot_lookback_days,
        )
        return []

    rows: list[tuple[Any, ...]] = []
    for record in frame:
        raw_code = record.get("股票代码")
        if raw_code is None:
            continue
        try:
            code = normalize_code(raw_code)
        except ValueError:
            continue
        if allowed is not None and code not in allowed:
            continue
        ratio = clean_number(record.get("质押比例"))
        if ratio is None:
            continue
        row_date = to_date(record.get("交易日期")) or used_date
        rows.append((code, row_date, ratio / 100.0))
    log.info("ingest.pledge.collected", rows=len(rows), snapshot=str(used_date))
    return rows
