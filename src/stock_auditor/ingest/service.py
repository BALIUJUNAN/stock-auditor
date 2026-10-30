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
    warnings: dict[str, str] = field(default_factory=dict)
    failed_codes: dict[str, dict[str, str]] = field(default_factory=dict)
    successful_codes: dict[str, int] = field(default_factory=dict)
    latest_dates: dict[str, str | None] = field(default_factory=dict)
    latest_dates_by_code: dict[str, dict[str, str | None]] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if not self.errors:
            return "partial" if "announcement_text" in self.warnings else "success"
        return "partial" if any(self.counts.values()) else "failed"


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
    if isinstance(data_client, DataClient):
        data_client.failures.clear()

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
        summary.errors["targets"] = "no stocks available"
        return summary

    def _industry_step() -> int:
        if not _needs_industry(connection, targets):
            return 0
        return industry.store_industry(connection, industry.collect_industry(data_client, settings))

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
    try:
        count, failures = announcements.backfill_announcement_text(connection, data_client)
        summary.counts["announcement_text"] = count
        missing = connection.execute(
            "SELECT count(*) FROM announcements WHERE text IS NULL OR length(trim(text)) < 100"
        ).fetchone()[0]
        if missing:
            summary.warnings["announcement_text"] = f"{missing} announcements missing text"
        if failures:
            summary.failed_codes["announcement_text"] = failures
    except Exception as exc:
        summary.errors["announcement_text"] = str(exc)

    # The available market-wide ratio is not the controlling shareholder ratio.
    # Existing rows have no provenance and cannot be trusted either.
    summary.warnings["pledge"] = "质押数据不全：缺少控股股东及一致行动人明细"
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
    for source, failures in getattr(data_client, "failures", {}).items():
        if failures:
            summary.failed_codes[source] = dict(failures)
            summary.errors[source] = f"{len(failures)} stocks failed: {', '.join(sorted(failures))}"
    for source in ("quotes", "financials", "valuation", "announcements", "research"):
        summary.successful_codes[source] = len(targets) - len(summary.failed_codes.get(source, {}))
    for table, column in (
        ("daily_quotes", "trade_date"),
        ("financials", "report_period"),
        ("valuation_daily", "trade_date"),
        ("announcements", "ann_date"),
    ):
        latest = connection.execute(f"SELECT max({column}) FROM {table}").fetchone()[0]
        summary.latest_dates[table] = latest.isoformat() if latest else None
        placeholders = ", ".join("?" for _ in targets)
        rows = connection.execute(
            f"SELECT code, max({column}) FROM {table} WHERE code IN ({placeholders}) GROUP BY code",
            targets,
        ).fetchall()
        dates = {str(code): value.isoformat() if value else None for code, value in rows}
        summary.latest_dates_by_code[table] = {code: dates.get(code) for code in targets}
    return summary
