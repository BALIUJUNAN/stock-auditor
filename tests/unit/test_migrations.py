from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from stock_auditor.cli import app
from stock_auditor.db.migrations import apply_migrations, discover_migrations

EXPECTED_TABLES = {
    "schema_version",
    "stock_universe",
    "daily_quotes",
    "financials",
    "valuation_daily",
    "consensus",
    "announcements",
    "pledge",
    "research_visits",
    "earnings_calendar",
    "index_daily",
    "filter_log",
    "veto_events",
    "quant_scores",
    "llm_pool",
    "tier1_dossiers",
    "tier2_scores",
    "final_scores",
    "weekly_reports",
    "recommendation_tracking",
    "run_log",
    "push_log",
}


def test_discover_migrations() -> None:
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == [1]
    assert migrations[0].name == "init"


def test_apply_migrations_idempotent(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / "test.duckdb")) as connection:
        assert apply_migrations(connection) == [1]

        rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        table_names = {str(row[0]) for row in rows}
        assert table_names >= EXPECTED_TABLES

        assert apply_migrations(connection) == []
        applied = connection.execute("SELECT version FROM schema_version").fetchall()
        assert applied == [(1,)]


def test_cli_init_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path / "home"))
    runner = CliRunner()

    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.output
    assert "已应用迁移" in first.output

    second = runner.invoke(app, ["init"])
    assert second.exit_code == 0, second.output
    assert "已是最新" in second.output

    assert (tmp_path / "home" / "db" / "stock_auditor.duckdb").is_file()
