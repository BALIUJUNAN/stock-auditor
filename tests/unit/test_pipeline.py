from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.domain import FilterResult
from stock_auditor.pipeline import RunContext, new_run_id, run_weekly
from stock_auditor.report.quant_check import (
    CALIBRATION_CODES,
    QuantCheckRow,
    render_quant_check,
)
from stock_auditor.scoring.fundamental import FundamentalResult
from stock_auditor.scoring.momentum import MomentumResult

AS_OF = date(2026, 10, 29)


def test_new_run_id_format() -> None:
    assert new_run_id("weekly", datetime(2026, 10, 29, 20, 0, 5)) == (
        "weekly-20261029-200005"
    )


def test_run_context_writes_run_log(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / "test.duckdb")) as connection:
        apply_migrations(connection)
        context = RunContext.start("weekly", now=datetime(2026, 10, 29, 20, 0, 0))
        context.begin_step("S2")
        context.complete_step("S2")
        context.finish()
        context.save(connection)

        run_id, status, step_status, error = connection.execute(
            "SELECT run_id, status, step_status, error FROM run_log"
        ).fetchone()
        assert run_id == "weekly-20261029-200000"
        assert status == "success"
        assert json.loads(step_status) == {"S2": "done"}
        assert error is None


def test_render_quant_check_lists_calibration_rows() -> None:
    row = QuantCheckRow(
        code="002773",
        name="康弘药业",
        filter_result=FilterResult(code="002773", passed=True, reasons=[]),
        fundamental=FundamentalResult(
            code="002773",
            total=21.5,
            profitability=10.0,
            growth=6.0,
            valuation=3.5,
            health=2.0,
            tags=["无一致预期"],
        ),
        momentum=MomentumResult(
            score=10.0,
            base=10.0,
            penalty=0.0,
            tags=[],
            raw={"r5": 0.01, "r20": 0.02, "dev20": 0.03},
        ),
        data_flag="未交叉验证",
        pool_source="quant",
    )
    content = render_quant_check(
        run_id="weekly-20261029-200000",
        as_of=AS_OF,
        rows=[row],
        universe_count=5577,
        stage0_passed=2,
        hard_veto=0,
        pool_count=2,
    )
    assert "# 量化校准检查" in content
    assert "| 002773 | 康弘药业 | 通过 | 21.5 | 10.0 | 31.5 |" in content
    assert "无一致预期" in content
    assert "LLM 池来源：quant" in content


def _insert_stock(
    connection: duckdb.DuckDBPyConnection,
    code: str,
    name: str,
    *,
    sw_l1: str,
    sw_l2: str,
) -> None:
    connection.execute(
        "INSERT INTO stock_universe (code, name, board, list_date, sw_l1, sw_l2) "
        "VALUES (?, ?, 'sz_main', DATE '2000-01-01', ?, ?)",
        [code, name, sw_l1, sw_l2],
    )
    quote_rows = []
    for index in range(80):
        trade_date = AS_OF - timedelta(days=79 - index)
        quote_rows.append(
            (code, trade_date, 10.0, 10.0, 9.7, 10.0, 1_000_000.0, 100_000_000.0, 0.05)
        )
    connection.executemany(
        "INSERT INTO daily_quotes (code, trade_date, open, high, low, close, "
        "volume, amount, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        quote_rows,
    )
    financial_rows = []
    for period, ann_date, revenue, profit, ocf in (
        (date(2023, 12, 31), date(2024, 4, 20), 100.0, 10.0, 12.0),
        (date(2024, 12, 31), date(2025, 4, 20), 110.0, 12.0, 13.0),
        (date(2025, 12, 31), date(2026, 4, 20), 121.0, 14.0, 15.0),
    ):
        financial_rows.append(
            (
                code,
                period,
                "akshare",
                ann_date,
                revenue,
                profit,
                ocf,
                100.0,
                30.0,
                5.0,
                10.0,
                10.0,
                0.12,
                0.10,
            )
        )
    connection.executemany(
        "INSERT INTO financials (code, report_period, source, ann_date, revenue, "
        "net_profit_parent, ocf, total_assets, total_liab, cash, interest_debt, "
        "receivables, roe, roic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        financial_rows,
    )
    valuation_rows = [
        (code, AS_OF - timedelta(days=index), 15.0, 1.5, 1.2)
        for index in range(700)
    ]
    connection.executemany(
        "INSERT INTO valuation_daily (code, trade_date, pe_ttm, pb, ps_ttm) "
        "VALUES (?, ?, ?, ?, ?)",
        valuation_rows,
    )


def test_weekly_runs_through_s4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with duckdb.connect(str(tmp_path / "test.duckdb")) as connection:
        apply_migrations(connection)
        _insert_stock(connection, "000001", "测试甲", sw_l1="电子", sw_l2="半导体")
        _insert_stock(connection, "000002", "测试乙", sw_l1="医药生物", sw_l2="化学制药")

        result = run_weekly(
            connection,
            load_settings(),
            until="S4",
            as_of=AS_OF,
            codes=["000001", "000002"],
        )

        assert result.universe_count == 2
        assert result.stage0_passed_count == 2
        assert result.hard_veto_count == 0
        assert [entry.code for entry in result.pool] == ["000001", "000002"]
        assert set(result.fundamentals) == {"000001", "000002"}
        assert result.data_flags == {
            "000001": "未交叉验证",
            "000002": "未交叉验证",
        }
        assert result.quant_check_path is not None
        assert result.quant_check_path.exists()
        content = result.quant_check_path.read_text(encoding="utf-8")
        for code in CALIBRATION_CODES:
            assert code in content
        assert "未在股票池" in content

        status, step_status = connection.execute(
            "SELECT status, step_status FROM run_log WHERE run_id = ?",
            [result.run_id],
        ).fetchone()
        assert status == "success"
        assert json.loads(step_status) == {
            "S1": "done",
            "S2": "done",
            "S3": "done",
            "S4": "done",
        }

        quant_rows = connection.execute(
            "SELECT code, fundamental, momentum FROM quant_scores ORDER BY code"
        ).fetchall()
        assert len(quant_rows) == 2
        assert all(row[1] > 0 for row in quant_rows)

        pool_rows = connection.execute(
            "SELECT code, source FROM llm_pool ORDER BY code"
        ).fetchall()
        assert pool_rows == [("000001", "quant"), ("000002", "quant")]

        filter_count = connection.execute(
            "SELECT count(*) FROM filter_log"
        ).fetchone()[0]
        assert filter_count == 2
        assert len(CALIBRATION_CODES) == 7
