"""T3.4：每日核心池异动触发、忽略名单与财报联动。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.feishu.ignored import ignore_code
from stock_auditor.pipeline.core import core_pool
from stock_auditor.pipeline.daily import build_daily_card, run_daily

AS_OF = date(2026, 10, 29)
NOW = datetime(2026, 10, 29, 16, 30)
WEEKLY_RUN = "weekly-20261025-200000"


def _bars(close: float, volume: float = 1_000_000.0) -> list[tuple[float, ...]]:
    return [
        (close, close, close * 0.98, close, volume, 100_000_000.0, 0.05)
        for _ in range(80)
    ]


def _insert_stock(
    connection: duckdb.DuckDBPyConnection,
    code: str,
    name: str,
    *,
    bars: list[tuple[float, ...]],
) -> None:
    connection.execute(
        "INSERT INTO stock_universe (code, name, board, list_date, sw_l1, sw_l2) "
        "VALUES (?, ?, 'sz_main', DATE '2000-01-01', '电子', '半导体')",
        [code, name],
    )
    connection.executemany(
        "INSERT INTO daily_quotes (code, trade_date, open, high, low, close, "
        "volume, amount, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (code, AS_OF - timedelta(days=79 - index), *row)
            for index, row in enumerate(bars)
        ],
    )


def _breakdown_bars() -> list[tuple[float, ...]]:
    bars = _bars(10.0)
    bars[75] = (8.0, 8.0, 7.9, 8.0, 10_000_000.0, 80_000_000.0, 0.05)
    for index in range(76, 80):
        bars[index] = (8.0, 8.0, 7.9, 8.0, 1_000_000.0, 80_000_000.0, 0.05)
    return bars


@pytest.fixture()
def connection(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect(str(tmp_path / "daily.duckdb"))
    apply_migrations(db)

    move_bars = _bars(10.0)
    move_bars[-1] = (11.5, 11.5, 10.8, 11.5, 2_000_000.0, 200_000_000.0, 0.08)
    _insert_stock(db, "000001", "测试甲", bars=move_bars)
    _insert_stock(db, "000002", "测试乙", bars=_breakdown_bars())
    _insert_stock(db, "000003", "测试丙", bars=_bars(10.0))

    db.execute(
        "INSERT INTO announcements (ann_id, code, ann_date, title, category) "
        "VALUES ('a1', '000001', ?, '关于签订重大合同的公告', '重大合同')",
        [AS_OF],
    )
    db.execute(
        "INSERT INTO pledge (code, date, controlling_pledge_ratio) "
        "VALUES ('000003', ?, 0.82)",
        [AS_OF],
    )
    try:
        yield db
    finally:
        db.close()


def _run(
    connection: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    codes: list[str] | None = None,
):
    return run_daily(
        connection,
        load_settings(),
        as_of=AS_OF,
        codes=codes or ["000001", "000002", "000003"],
        client=None,
        push=False,
        now=NOW,
        state_file=tmp_path / "daily.json",
        ignored_path=tmp_path / "ignored.json",
        earnings_state_file=tmp_path / "earnings.json",
        use_lock=False,
    )


def test_daily_detects_four_trigger_types_and_dedupes(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    result = _run(connection, tmp_path)
    by_code = {item.code: item for item in result.triggers}
    assert set(by_code) == {"000001", "000002", "000003"}

    assert any("重大公告" in reason for reason in by_code["000001"].reasons)
    assert any("单日涨跌幅" in reason for reason in by_code["000001"].reasons)
    assert any("动量破位" in reason for reason in by_code["000002"].reasons)
    assert any("新触发 Veto：pledge_ratio" in reason for reason in by_code["000003"].reasons)

    assert set(result.reviews) == {"000001", "000002", "000003"}
    card = build_daily_card(
        by_code["000001"],
        result.reviews["000001"],
        as_of=AS_OF,
    )
    content = card["body"]["elements"][0]["content"]
    assert "触发原因" in content
    assert "重大公告" in content
    assert "未执行 LLM 审计" in content

    state = (tmp_path / "daily.json").read_text(encoding="utf-8")
    assert "000002" in state
    assert "000003:pledge_ratio" in state

    second = _run(connection, tmp_path)
    assert second.triggers == ()
    assert second.reviews == {}


def test_ignored_code_is_suppressed(
    connection: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    ignore_code("000001", path=tmp_path / "ignored.json", as_of=AS_OF)

    result = _run(connection, tmp_path)

    assert result.ignored == ("000001",)
    assert {item.code for item in result.triggers} == {"000002", "000003"}


def test_core_pool_merges_watchlist_and_weekly_scores(
    connection: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection.execute(
        "INSERT INTO run_log (run_id, pipeline, started_at, finished_at, status, "
        "step_status, llm_tokens, llm_cost) "
        "VALUES (?, 'weekly', ?, ?, 'success', '{}', 0, 0)",
        [WEEKLY_RUN, NOW - timedelta(days=4), NOW - timedelta(days=4)],
    )
    connection.executemany(
        "INSERT INTO final_scores (run_id, code, raw_total, final_total, stars, "
        "is_yellow, is_veto) VALUES (?, ?, ?, ?, ?, FALSE, ?)",
        [
            (WEEKLY_RUN, "000001", 80.0, 80.0, 4, False),
            (WEEKLY_RUN, "000002", 70.0, 70.0, 3, False),
            (WEEKLY_RUN, "000003", 90.0, 90.0, 5, True),
        ],
    )
    monkeypatch.setattr(
        "stock_auditor.pipeline.core.load_watchlist",
        lambda max_entries: SimpleNamespace(codes=("000009",)),
    )

    assert core_pool(
        connection, load_settings(), as_of=AS_OF
    ) == ("000009", "000001")
    assert core_pool(connection, load_settings(), codes=["000002", "000002"]) == (
        "000002",
    )
