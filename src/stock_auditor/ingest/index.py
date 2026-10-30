"""指数日线采集：基准指数用新浪，申万行业指数用申万接口。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import (
    DataClient,
    clean_number,
    direct_network,
    frame_records,
    normalize_code,
    to_date,
)

log = structlog.get_logger(__name__)

INDEX_COLUMNS = ("index_code", "trade_date", "close")


def _ak() -> Any:
    import akshare as ak

    return ak


def index_symbol(code: str) -> str:
    """新浪指数代码：399 开头为深证，其余按上证处理。"""
    code = normalize_code(code)
    prefix = "sz" if code.startswith("399") else "sh"
    return f"{prefix}{code}"


def _benchmark_rows(
    client: DataClient,
    code: str,
    cutoff: date,
) -> dict[date, tuple[Any, ...]]:
    frame = client.call(
        lambda: _ak().stock_zh_index_daily(symbol=index_symbol(code)),
        description=f"基准指数 {code}",
    )
    rows: dict[date, tuple[Any, ...]] = {}
    for record in frame_records(frame):
        trade_date = to_date(record.get("date"))
        if trade_date is None or trade_date < cutoff:
            continue
        close = clean_number(record.get("close"))
        if close is not None:
            rows[trade_date] = (code, trade_date, close)
    return rows


def _sector_rows(
    client: DataClient,
    code: str,
    cutoff: date,
) -> dict[date, tuple[Any, ...]]:
    with direct_network():
        frame = client.call(
            lambda: _ak().index_hist_sw(symbol=code, period="day"),
            description=f"申万行业指数 {code}",
        )
    rows: dict[date, tuple[Any, ...]] = {}
    for record in frame_records(frame):
        trade_date = to_date(record.get("日期"))
        close = clean_number(record.get("收盘"))
        if trade_date is None or close is None or trade_date < cutoff:
            continue
        rows[trade_date] = (code, trade_date, close)
    return rows


def collect_index(client: DataClient, settings: Settings) -> list[tuple[Any, ...]]:
    """抓取沪深 300 与配置中的申万行业指数；单个指数失败不影响其余。"""
    cutoff = date.today() - timedelta(days=settings.ingest.daily_lookback_days)
    collected: dict[tuple[str, date], tuple[Any, ...]] = {}

    benchmark = settings.tracking.benchmark
    try:
        for key, row in _benchmark_rows(client, benchmark, cutoff).items():
            collected[(benchmark, key)] = row
    except Exception as exc:  # noqa: BLE001 - 指数是辅助数据
        log.error("ingest.index.benchmark_failed", code=benchmark, error=str(exc))

    for sector_code in settings.tracking.sector_benchmarks.values():
        code = normalize_code(sector_code)
        try:
            for key, row in _sector_rows(client, code, cutoff).items():
                collected[(code, key)] = row
        except Exception as exc:  # noqa: BLE001 - 单个行业指数失败不阻塞
            log.warning("ingest.index.sector_failed", code=code, error=str(exc))

    rows = [collected[key] for key in sorted(collected)]
    log.info("ingest.index.collected", rows=len(rows))
    return rows
