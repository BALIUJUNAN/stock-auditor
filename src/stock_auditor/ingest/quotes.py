"""日线行情采集：新浪为主源，腾讯为备用源，均取前复权。"""

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
    sina_symbol,
    to_date,
)

log = structlog.get_logger(__name__)

QUOTE_COLUMNS = (
    "code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "is_suspended",
)


def _ak() -> Any:
    import akshare as ak

    return ak


def _to_rows(code: str, frame: Any) -> list[tuple[Any, ...]]:
    by_date: dict[date, tuple[Any, ...]] = {}
    for record in frame_records(frame):
        trade_date = to_date(record.get("date"))
        if trade_date is None:
            continue
        volume = clean_number(record.get("volume"))
        by_date[trade_date] = (
            code,
            trade_date,
            clean_number(record.get("open")),
            clean_number(record.get("high")),
            clean_number(record.get("low")),
            clean_number(record.get("close")),
            volume,
            clean_number(record.get("amount")),
            clean_number(record.get("turnover")),
            volume is None or volume == 0,
        )
    return [by_date[key] for key in sorted(by_date)]


def fetch_quote_rows(
    client: DataClient,
    code: str,
    start: date,
    end: date,
) -> list[tuple[Any, ...]]:
    symbol = sina_symbol(code)
    start_text = start.strftime("%Y%m%d")
    end_text = end.strftime("%Y%m%d")
    try:
        frame = client.call(
            lambda: _ak().stock_zh_a_daily(
                symbol=symbol,
                start_date=start_text,
                end_date=end_text,
                adjust="qfq",
            ),
            description=f"新浪日线 {code}",
        )
    except Exception as exc:  # noqa: BLE001 - 主源失败时切换备用源
        log.warning("ingest.quotes.sina_failed", code=code, error=str(exc))
        frame = client.call(
            lambda: _ak().stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start_text,
                end_date=end_text,
                adjust="qfq",
                timeout=30,
            ),
            description=f"腾讯日线 {code}",
        )
    return _to_rows(code, frame)


def collect_quotes(
    client: DataClient,
    settings: Settings,
    codes: list[str],
) -> list[tuple[Any, ...]]:
    """按 ``ingest.daily_lookback_days`` 抓取前复权日线。"""
    end = date.today()
    start = end - timedelta(days=settings.ingest.daily_lookback_days)
    rows: list[tuple[Any, ...]] = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        try:
            collected = fetch_quote_rows(client, code, start, end)
            if not collected:
                raise ValueError("no data returned")
            rows.extend(collected)
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            if hasattr(client, "record_failure"):
                client.record_failure("quotes", code, exc)
            log.error("ingest.quotes.failed", code=code, error=str(exc))
    log.info("ingest.quotes.collected", rows=len(rows))
    return rows
