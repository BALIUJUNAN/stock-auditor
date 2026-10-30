"""每日估值采集：东财估值分析（PE/PB/PS 全历史）。"""

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

VALUATION_COLUMNS = ("code", "trade_date", "pe_ttm", "pb", "ps_ttm")


def _ak() -> Any:
    import akshare as ak

    return ak


def fetch_valuation_rows(
    client: DataClient,
    code: str,
    cutoff: date,
) -> list[tuple[Any, ...]]:
    frame = client.call(
        lambda symbol=code: _ak().stock_value_em(symbol=symbol),
        description=f"估值分析 {code}",
    )
    rows: list[tuple[Any, ...]] = []
    for record in frame_records(frame):
        trade_date = to_date(record.get("数据日期"))
        if trade_date is None or trade_date < cutoff:
            continue
        rows.append(
            (
                code,
                trade_date,
                clean_number(record.get("PE(TTM)")),
                clean_number(record.get("市净率")),
                clean_number(record.get("市销率")),
            )
        )
    return rows


def collect_valuation(
    client: DataClient,
    settings: Settings,
    codes: list[str],
) -> list[tuple[Any, ...]]:
    """抓取 ``ingest.valuation_years`` 年内的估值序列。"""
    cutoff = date.today() - timedelta(days=365 * settings.ingest.valuation_years)
    rows: list[tuple[Any, ...]] = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        try:
            collected = fetch_valuation_rows(client, code, cutoff)
            if not collected:
                raise ValueError("no data returned")
            rows.extend(collected)
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            if hasattr(client, "record_failure"):
                client.record_failure("valuation", code, exc)
            log.error("ingest.valuation.failed", code=code, error=str(exc))
    log.info("ingest.valuation.collected", rows=len(rows))
    return rows
