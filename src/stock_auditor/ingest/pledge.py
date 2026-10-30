"""股权质押比例采集：取最近一期（周频）全市场快照。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import (
    DataClient,
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
    """Unavailable: the upstream market-wide ratio is not the B3 metric."""
    del client, settings, codes
    log.warning("ingest.pledge.unavailable", reason="missing controlling-holder detail")
    return []
