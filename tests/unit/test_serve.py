"""T3.5：调度表达式、12 小时补跑、APScheduler 与常驻服务启动。"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.serve import (
    build_scheduler,
    catch_up_pipelines,
    latest_occurrence,
    parse_schedule,
    start_serve,
)

NOW = datetime(2026, 10, 29, 18, 0)  # Thursday
DAILY_SLOT = datetime(2026, 10, 29, 16, 30)
WEEKLY_SLOT = datetime(2026, 10, 25, 20, 0)  # Sunday


@pytest.fixture()
def connection(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    db = duckdb.connect(str(tmp_path / "serve.duckdb"))
    apply_migrations(db)
    try:
        yield db
    finally:
        db.close()


def test_parse_schedule() -> None:
    weekly = parse_schedule("sun 20:00")
    assert weekly.weekdays == frozenset({6})
    assert (weekly.hour, weekly.minute) == (20, 0)
    assert weekly.day_of_week == "sun"

    daily = parse_schedule("mon-fri 16:30")
    assert daily.weekdays == frozenset({0, 1, 2, 3, 4})
    assert (daily.hour, daily.minute) == (16, 30)

    with pytest.raises(ValueError):
        parse_schedule("weekday 16:30")
    with pytest.raises(ValueError):
        parse_schedule("sun 25:00")


def test_latest_occurrence_handles_weekends() -> None:
    daily = parse_schedule("mon-fri 16:30")
    assert latest_occurrence(daily, NOW) == DAILY_SLOT
    assert latest_occurrence(daily, datetime(2026, 10, 31, 10, 0)) == datetime(2026, 10, 30, 16, 30)
    assert latest_occurrence(daily, datetime(2026, 10, 31, 3, 0)) == datetime(2026, 10, 30, 16, 30)

    weekly = parse_schedule("sun 20:00")
    assert latest_occurrence(weekly, NOW) == WEEKLY_SLOT
    assert latest_occurrence(weekly, datetime(2026, 10, 26, 9, 0)) == WEEKLY_SLOT


def test_catch_up_only_within_grace_and_without_success(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    calls: list[str] = []

    def weekly() -> None:
        calls.append("weekly")

    def daily() -> None:
        calls.append("daily")

    executed = catch_up_pipelines(
        connection,
        load_settings(),
        now=NOW,
        runners={"weekly": weekly, "daily": daily},
    )
    assert executed == ("daily",)
    assert calls == ["daily"]

    connection.execute(
        "INSERT INTO run_log (run_id, pipeline, started_at, finished_at, status, "
        "step_status, llm_tokens, llm_cost) "
        "VALUES ('daily-20261029-163000', 'daily', ?, ?, 'success', '{}', 0, 0)",
        [DAILY_SLOT, DAILY_SLOT],
    )
    calls.clear()
    assert (
        catch_up_pipelines(
            connection,
            load_settings(),
            now=NOW,
            runners={"weekly": weekly, "daily": daily},
        )
        == ()
    )
    assert calls == []

    # 超过 12 小时宽限窗口，即使没跑过也不补跑。
    late = datetime(2026, 10, 30, 5, 0)
    assert (
        catch_up_pipelines(
            connection,
            load_settings(),
            now=late,
            runners={"weekly": weekly, "daily": daily},
        )
        == ()
    )


def test_catch_up_ignores_runner_failure(connection: duckdb.DuckDBPyConnection) -> None:
    def boom() -> None:
        raise RuntimeError("采集失败")

    executed = catch_up_pipelines(
        connection,
        load_settings(),
        now=NOW,
        runners={"daily": boom},
    )
    assert executed == ()


def test_build_scheduler_registers_cron_jobs() -> None:
    settings = load_settings()
    scheduler = build_scheduler(
        settings,
        runners={"weekly": lambda: None, "daily": lambda: None},
    )
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"weekly", "daily"}
    assert "day_of_week='sun'" in str(jobs["weekly"].trigger)
    assert "day_of_week='mon-fri'" in str(jobs["daily"].trigger)
    assert scheduler._job_defaults["misfire_grace_time"] == 12 * 3600


def test_start_serve_runs_catch_up_and_bot_thread(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    @contextmanager
    def factory() -> Iterator[duckdb.DuckDBPyConnection]:
        db = duckdb.connect(str(tmp_path / "serve-runtime.duckdb"))
        apply_migrations(db)
        try:
            yield db
        finally:
            db.close()

    bot_started = threading.Event()
    runtime = start_serve(
        load_settings(),
        now=NOW,
        block=False,
        runners={
            "weekly": lambda: calls.append("weekly"),
            "daily": lambda: calls.append("daily"),
        },
        bot_runner=bot_started.set,
        start_bot=True,
        connection_factory=factory,
    )
    try:
        assert runtime.caught_up == ("daily",)
        assert calls == ["daily"]
        assert runtime.scheduler.running
        assert runtime.bot_thread is not None
        assert bot_started.wait(timeout=2)
    finally:
        runtime.stop()
    assert not runtime.scheduler.running


def test_start_serve_can_skip_bot_and_catch_up(tmp_path: Path) -> None:
    @contextmanager
    def factory() -> Iterator[duckdb.DuckDBPyConnection]:
        db = duckdb.connect(str(tmp_path / "serve-skip.duckdb"))
        apply_migrations(db)
        try:
            yield db
        finally:
            db.close()

    runtime = start_serve(
        load_settings(),
        now=NOW,
        block=False,
        runners={"weekly": lambda: None, "daily": lambda: None},
        start_bot=False,
        catch_up=False,
        connection_factory=factory,
    )
    try:
        assert runtime.caught_up == ()
        assert runtime.bot_thread is None
    finally:
        runtime.stop()


def test_daily_runner_passes_configured_llm(monkeypatch, tmp_path):
    import stock_auditor.serve as serve
    from stock_auditor.ingest.service import IngestSummary

    client = object()
    received = []

    @contextmanager
    def factory():
        with duckdb.connect(":memory:") as db:
            yield db

    monkeypatch.setattr(serve, "connect", factory)
    monkeypatch.setattr(serve, "LlmClient", lambda settings: client)
    monkeypatch.setattr(serve, "run_ingest", lambda *args, **kwargs: IngestSummary())
    monkeypatch.setattr(serve, "run_daily", lambda *args, **kwargs: received.append(kwargs))
    serve.default_runners(load_settings())["daily"]()
    assert received == [{"client": client, "ingest_errors": {}, "ingest_warnings": {}}]


def test_daily_runner_keeps_warnings_separate_and_skips_pdf(monkeypatch, tmp_path):
    import stock_auditor.serve as serve
    from stock_auditor.ingest.service import IngestSummary

    calls = {}

    @contextmanager
    def factory():
        with duckdb.connect(":memory:") as db:
            yield db

    def ingest(*args, **kwargs):
        calls["ingest"] = kwargs
        return IngestSummary(warnings={"announcement_text": "missing"})

    monkeypatch.setattr(serve, "connect", factory)
    monkeypatch.setattr(serve, "LlmClient", lambda settings: object())
    monkeypatch.setattr(serve, "run_ingest", ingest)
    monkeypatch.setattr(serve, "run_daily", lambda *args, **kwargs: calls.update(daily=kwargs))
    serve.default_runners(load_settings())["daily"]()
    assert calls["ingest"] == {"backfill_text": False}
    assert calls["daily"]["ingest_errors"] == {}
    assert calls["daily"]["ingest_warnings"]["announcement_text"] == "missing"
