"""T3.4：财报提醒、T+1 重算与状态去重。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.pipeline.earnings import (
    EARNINGS_TAG,
    build_recalc_card,
    build_warning_card,
    check_earnings,
    next_trading_days,
    recompute_due,
    run_earnings,
    trading_days_until,
)

AS_OF = date(2026, 10, 29)
CODE = "000001"
NAME = "测试甲"


def _seed_stock(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        "INSERT INTO stock_universe (code, name, board, list_date, sw_l1, sw_l2) "
        "VALUES (?, ?, 'sz_main', DATE '2000-01-01', '电子', '半导体')",
        [CODE, NAME],
    )
    connection.executemany(
        "INSERT INTO daily_quotes (code, trade_date, open, high, low, close, "
        "volume, amount, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                CODE,
                AS_OF - timedelta(days=79 - index),
                10.0,
                10.0,
                9.7,
                10.0,
                1_000_000.0,
                100_000_000.0,
                0.05,
            )
            for index in range(80)
        ],
    )


@pytest.fixture()
def connection(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(str(tmp_path / "earnings.duckdb"))
    apply_migrations(db)
    _seed_stock(db)
    try:
        yield db
    finally:
        db.close()


def _add_calendar(
    connection: duckdb.DuckDBPyConnection,
    *,
    report_period: date,
    scheduled: date | None = None,
    actual: date | None = None,
) -> None:
    connection.execute(
        "INSERT INTO earnings_calendar (code, report_period, scheduled_date, actual_date) "
        "VALUES (?, ?, ?, ?)",
        [CODE, report_period, scheduled, actual],
    )


def _ingest_stub(
    connection: duckdb.DuckDBPyConnection,
    settings: Any,
    codes: list[str],
) -> None:
    del connection, settings, codes


def test_trading_day_helpers_skip_weekends() -> None:
    days = next_trading_days(AS_OF, 3)
    assert days == (date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3))
    assert trading_days_until(AS_OF, date(2026, 11, 2)) == 2


def test_check_earnings_flags_upcoming_disclosures(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    _add_calendar(
        connection,
        report_period=date(2026, 9, 30),
        scheduled=date(2026, 11, 2),
    )
    _add_calendar(
        connection,
        report_period=date(2026, 6, 30),
        scheduled=date(2026, 11, 10),
    )
    _add_calendar(
        connection,
        report_period=date(2026, 3, 31),
        scheduled=date(2026, 10, 30),
        actual=date(2026, 10, 28),
    )

    warnings = check_earnings(connection, load_settings(), [CODE], as_of=AS_OF)

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code == CODE
    assert warning.name == NAME
    assert warning.scheduled_date == date(2026, 11, 2)
    assert warning.trading_days == 2
    assert warning.tag == EARNINGS_TAG

    card = build_warning_card(warnings)
    content = card["body"]["elements"][0]["content"]
    assert EARNINGS_TAG in content
    assert "2026-11-02" in content


def test_recompute_due_and_state_dedupe(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    _add_calendar(
        connection,
        report_period=date(2026, 9, 30),
        scheduled=date(2026, 10, 28),
        actual=date(2026, 10, 28),
    )
    state_file = tmp_path / "earnings.json"

    due = recompute_due(connection, [CODE], as_of=AS_OF, path=state_file)
    assert len(due) == 1
    assert due[0].key == f"{CODE}:2026-09-30:2026-10-28"

    first = run_earnings(
        connection,
        load_settings(),
        as_of=AS_OF,
        codes=[CODE],
        push=False,
        state_file=state_file,
        ingest=_ingest_stub,
        use_lock=False,
    )
    assert first.recalculated == (CODE,)
    assert CODE in first.reviews
    assert first.reviews[CODE].momentum is not None
    assert first.due == due
    assert state_file.exists()

    card = build_recalc_card(first.reviews[CODE], due[0], as_of=AS_OF)
    content = card["body"]["elements"][0]["content"]
    assert "已按最新数据全量重算" in content
    assert "2026-09-30" in content

    second = run_earnings(
        connection,
        load_settings(),
        as_of=AS_OF,
        codes=[CODE],
        push=False,
        state_file=state_file,
        ingest=_ingest_stub,
        use_lock=False,
    )
    assert second.due == ()
    assert second.recalculated == ()


def test_earnings_refresh_does_not_backfill_global_announcements(monkeypatch):
    import stock_auditor.pipeline.earnings as earnings
    from stock_auditor.ingest.service import IngestSummary

    captured = {}

    def ingest(*args, **kwargs):
        captured.update(kwargs)
        return IngestSummary(errors={"quotes": "failed"})

    monkeypatch.setattr(earnings, "run_ingest", ingest)
    with duckdb.connect(":memory:") as db, pytest.raises(RuntimeError):
        earnings.recalculate_stock(db, load_settings(), "000001", as_of=AS_OF, run_id="test")
    assert captured == {"codes": ["000001"], "backfill_text": False}
