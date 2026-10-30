"""全市场历史回填：逐只采集、逐只落库，进度写状态文件，可中断续传。

``sa init --backfill`` 的耗时主要在行情与财务（数千只股票）。状态文件记录
每个数据集已完成的股票代码；中断后重跑只处理未完成的股票。``Ctrl+C`` 不会
被吞掉：当前这只股票会重跑，之前完成的进度已保存。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import structlog

from stock_auditor import paths
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
from stock_auditor.ingest.common import DataClient, upsert_rows

log = structlog.get_logger(__name__)

STATE_FILENAME = "backfill.json"
_PROGRESS_EVERY = 50


@dataclass
class BackfillSummary:
    """各数据集写入行数与失败项（键为 ``数据集`` 或 ``数据集:代码``）。"""

    counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def code_failures(self) -> int:
        return sum(1 for key in self.errors if ":" in key)


class BackfillState:
    """JSON 状态文件；``fingerprint`` 变化时自动作废旧进度。"""

    def __init__(self, path: Path, fingerprint: str) -> None:
        self._path = Path(path)
        self._fingerprint = fingerprint
        self._completed: dict[str, set[str]] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("backfill.state_unreadable", path=str(self._path), error=str(exc))
            return
        if payload.get("fingerprint") != self._fingerprint:
            log.info("backfill.state_reset", reason="fingerprint_changed")
            return
        completed = payload.get("completed") or {}
        self._completed = {
            name: {str(code) for code in codes}
            for name, codes in completed.items()
            if isinstance(codes, list)
        }

    def is_done(self, dataset: str, code: str) -> bool:
        return code in self._completed.get(dataset, set())

    def done_count(self, dataset: str) -> int:
        return len(self._completed.get(dataset, set()))

    def mark(self, dataset: str, code: str) -> None:
        self._completed.setdefault(dataset, set()).add(code)
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fingerprint": self._fingerprint,
            "completed": {name: sorted(codes) for name, codes in self._completed.items()},
        }
        temporary = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._path)


@dataclass(frozen=True)
class StockStep:
    """一个按股票执行的数据集：抓取 + 落库。"""

    name: str
    fetch: Callable[[str], list[tuple[Any, ...]]]
    store: Callable[[list[tuple[Any, ...]]], int]


def _fingerprint(settings: Settings) -> str:
    payload = {
        "years": settings.backfill.years,
        "financial_periods": settings.ingest.financial_periods,
        "announcement_lookback_days": settings.ingest.announcement_lookback_days,
        "research_lookback_days": settings.ingest.research_lookback_days,
        "research_max_pages": settings.ingest.research_max_pages,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16]


def backfill_stocks(
    codes: Sequence[str],
    steps: Sequence[StockStep],
    state: BackfillState,
    summary: BackfillSummary | None = None,
) -> BackfillSummary:
    """按数据集顺序逐只执行；失败不标记完成，下次运行自动重试。"""
    result = summary if summary is not None else BackfillSummary()
    for step in steps:
        pending = [code for code in codes if not state.is_done(step.name, code)]
        log.info(
            "backfill.step_start",
            dataset=step.name,
            total=len(codes),
            pending=len(pending),
        )
        for position, code in enumerate(pending, 1):
            try:
                rows = step.fetch(code)
                written = step.store(rows)
            except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
                result.errors[f"{step.name}:{code}"] = str(exc)
                log.error(
                    "backfill.code_failed",
                    dataset=step.name,
                    code=code,
                    error=str(exc),
                )
                continue
            state.mark(step.name, code)
            result.counts[step.name] = result.counts.get(step.name, 0) + written
            if position % _PROGRESS_EVERY == 0:
                log.info(
                    "backfill.progress",
                    dataset=step.name,
                    position=position,
                    pending=len(pending),
                )
        log.info("backfill.step_done", dataset=step.name, pending=len(pending))
    return result


def _run_market_step(
    summary: BackfillSummary,
    name: str,
    func: Callable[[], int],
) -> None:
    try:
        summary.counts[name] = func()
    except Exception as exc:  # noqa: BLE001 - 市场级步骤失败记录后继续
        summary.errors[name] = str(exc)
        log.error("backfill.step_failed", step=name, error=str(exc))


def run_backfill(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    client: DataClient | None = None,
    state_path: Path | None = None,
) -> BackfillSummary:
    """先刷新股票池与行业，再逐只回填；市场级数据最后补齐。"""
    data_client = client if client is not None else DataClient(settings)
    summary = BackfillSummary()

    _run_market_step(
        summary,
        "stock_universe",
        lambda: universe.store_universe(
            connection, universe.collect_universe(data_client, settings)
        ),
    )

    codes = [
        row[0]
        for row in connection.execute("SELECT code FROM stock_universe ORDER BY code").fetchall()
    ]
    if not codes:
        return summary

    missing_industry = connection.execute(
        "SELECT count(*) FROM stock_universe WHERE sw_l1 IS NULL OR sw_l2 IS NULL"
    ).fetchone()[0]
    if missing_industry:
        _run_market_step(
            summary,
            "industry",
            lambda: industry.store_industry(
                connection, industry.collect_industry(data_client, settings)
            ),
        )

    today = date.today()
    backfill_days = settings.backfill.years * 365
    quote_start = today - timedelta(days=backfill_days)
    valuation_start = today - timedelta(days=backfill_days)
    research_cutoff = today - timedelta(days=settings.ingest.research_lookback_days)
    announcement_begin = today - timedelta(days=settings.ingest.announcement_lookback_days)
    begin_text = announcement_begin.strftime("%Y%m%d")
    end_text = today.strftime("%Y%m%d")

    steps = [
        StockStep(
            name="daily_quotes",
            fetch=lambda code: quotes.fetch_quote_rows(data_client, code, quote_start, today),
            store=lambda rows: upsert_rows(connection, "daily_quotes", quotes.QUOTE_COLUMNS, rows),
        ),
        StockStep(
            name="financials",
            fetch=lambda code: financials.fetch_financial_rows(
                data_client, code, settings.ingest.financial_periods
            ),
            store=lambda rows: upsert_rows(
                connection, "financials", financials.FINANCIAL_COLUMNS, rows
            ),
        ),
        StockStep(
            name="valuation_daily",
            fetch=lambda code: valuation.fetch_valuation_rows(data_client, code, valuation_start),
            store=lambda rows: upsert_rows(
                connection, "valuation_daily", valuation.VALUATION_COLUMNS, rows
            ),
        ),
        StockStep(
            name="announcements",
            fetch=lambda code: announcements.fetch_announcement_rows(
                data_client, code, begin_text, end_text
            ),
            store=lambda rows: announcements.store_announcements(connection, rows),
        ),
        StockStep(
            name="research_visits",
            fetch=lambda code: research.fetch_research_rows(
                data_client, settings, code, research_cutoff
            ),
            store=lambda rows: upsert_rows(
                connection, "research_visits", research.RESEARCH_COLUMNS, rows
            ),
        ),
    ]

    state = BackfillState(
        Path(state_path) if state_path is not None else paths.state_dir() / STATE_FILENAME,
        _fingerprint(settings),
    )
    backfill_stocks(codes, steps, state, summary)

    index_settings = settings.model_copy(
        update={"ingest": settings.ingest.model_copy(update={"daily_lookback_days": backfill_days})}
    )
    _run_market_step(
        summary,
        "earnings_calendar",
        lambda: upsert_rows(
            connection,
            "earnings_calendar",
            earnings.EARNINGS_COLUMNS,
            earnings.collect_earnings(data_client, settings, codes),
        ),
    )
    _run_market_step(
        summary,
        "index_daily",
        lambda: upsert_rows(
            connection,
            "index_daily",
            index.INDEX_COLUMNS,
            index.collect_index(data_client, index_settings),
        ),
    )
    return summary
