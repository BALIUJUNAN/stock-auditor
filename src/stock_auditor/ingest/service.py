"""采集编排：按顺序运行各采集器并写入数据库。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import duckdb
import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest import (
    announcements,
    earnings,
    financials,
    index,
    industry,
    pledge,
    quotes,
    research,
    universe,
    valuation,
)
from stock_auditor.ingest.common import DataClient, normalize_code, upsert_rows

log = structlog.get_logger(__name__)


@dataclass
class IngestSummary:
    """每个表写入的行数与失败步骤。"""

    counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _target_codes(
    connection: duckdb.DuckDBPyConnection,
    codes: list[str] | None,
) -> list[str]:
    if codes is not None:
        return sorted({normalize_code(code) for code in codes})
    rows = connection.execute("SELECT code FROM stock_universe ORDER BY code").fetchall()
    return [row[0] for row in rows]


def _needs_industry(
    connection: duckdb.DuckDBPyConnection,
    codes: list[str],
) -> bool:
    missing = {
        row[0]
        for row in connection.execute(
            "SELECT code FROM stock_universe WHERE sw_l1 IS NULL OR sw_l2 IS NULL"
        ).fetchall()
    }
    return bool(missing.intersection(codes))


def _run_step(summary: IngestSummary, name: str, func: Callable[[], int]) -> None:
    try:
        summary.counts[name] = func()
    except Exception as exc:  # noqa: BLE001 - 单个步骤失败不阻塞其余数据
        log.error("ingest.step_failed", step=name, error=str(exc))
        summary.errors[name] = str(exc)


def run_ingest(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    codes: list[str] | None = None,
    client: DataClient | None = None,
) -> IngestSummary:
    """采集股票池、行业、行情、财务、估值、公告、质押、调研、预约与指数。"""
    data_client = client if client is not None else DataClient(settings)
    summary = IngestSummary()

    _run_step(
        summary,
        "stock_universe",
        lambda: universe.store_universe(
            connection, universe.collect_universe(data_client, settings)
        ),
    )

    targets = _target_codes(connection, codes)
    if not targets:
        log.warning("ingest.no_targets")
        return summary

    def _industry_step() -> int:
        if not _needs_industry(connection, targets):
            return 0
        return industry.store_industry(
            connection, industry.collect_industry(data_client, settings)
        )

    _run_step(summary, "industry", _industry_step)
    _run_step(
        summary,
        "daily_quotes",
        lambda: upsert_rows(
            connection,
            "daily_quotes",
            quotes.QUOTE_COLUMNS,
            quotes.collect_quotes(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "financials",
        lambda: upsert_rows(
            connection,
            "financials",
            financials.FINANCIAL_COLUMNS,
            financials.collect_financials(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "valuation_daily",
        lambda: upsert_rows(
            connection,
            "valuation_daily",
            valuation.VALUATION_COLUMNS,
            valuation.collect_valuation(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "announcements",
        lambda: announcements.store_announcements(
            connection,
            announcements.collect_announcements(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "pledge",
        lambda: upsert_rows(
            connection,
            "pledge",
            pledge.PLEDGE_COLUMNS,
            pledge.collect_pledge(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "research_visits",
        lambda: upsert_rows(
            connection,
            "research_visits",
            research.RESEARCH_COLUMNS,
            research.collect_research(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "earnings_calendar",
        lambda: upsert_rows(
            connection,
            "earnings_calendar",
            earnings.EARNINGS_COLUMNS,
            earnings.collect_earnings(data_client, settings, targets),
        ),
    )
    _run_step(
        summary,
        "index_daily",
        lambda: upsert_rows(
            connection,
            "index_daily",
            index.INDEX_COLUMNS,
            index.collect_index(data_client, settings),
        ),
    )
    return summary
