from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

from stock_auditor.calibration import (
    CALIBRATION_CODES,
    CALIBRATION_STOCKS,
    CalibrationResult,
    CalibrationRow,
    run_calibration,
)
from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.llm.client import LlmResponse, LlmUsage

AS_OF = date(2026, 10, 29)
MATERIAL_TEXT = "公司于本报告期内实现营业收入同比增长，主要得益于新产品放量。" * 20
QUOTE = MATERIAL_TEXT[:120]

SCORES = {
    "002773": 38,
    "002185": 37,
    "002774": 30,
    "002354": 30,
    "002724": 30,
    "603528": 30,
    "600664": 5,
}


def _tier_for(score: int) -> str:
    for label, low, high in (
        ("0-10", 0, 10),
        ("11-20", 11, 20),
        ("21-30", 21, 30),
        ("31-35", 31, 35),
        ("36-40", 36, 40),
    ):
        if low <= score <= high:
            return label
    raise ValueError(score)


class FakeClient:
    def __init__(self, scores: dict[str, int]) -> None:
        self._scores = scores
        self.calls = 0

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        prompt_version: str,
        input_hash: str | None = None,
        response_format: Any | None = None,
        messages: Any | None = None,
    ) -> LlmResponse:
        self.calls += 1
        match = re.search(r"（(\d{6})）", prompt)
        assert match is not None
        code = match.group(1)
        if "Tier-1 材料抽取" in prompt:
            content = {
                "key_facts": [
                    {
                        "fact_id": "F01",
                        "category": "业绩",
                        "statement": "营业收入同比增长",
                        "source_id": "A01",
                        "source_type": "法定公告",
                        "date": AS_OF.isoformat(),
                        "quote": QUOTE,
                        "context_tags": [],
                        "anomaly_flag": False,
                        "anomaly_description": "",
                    }
                ],
                "red_flags": [],
                "counter_checks": [],
                "summary": "本期收入增长，需关注后续兑现。",
            }
        else:
            score = self._scores[code]
            content = {
                "bear_points": [
                    {"text": "收入增长依赖单一产品", "fact_ids": ["F01"]},
                    {"text": "现金流仍需观察", "fact_ids": ["F01"]},
                ],
                "tier": _tier_for(score),
                "score": score,
                "reasons": [
                    {"text": "收入保持增长", "fact_ids": ["F01"]},
                    {"text": "订单仍需验证", "fact_ids": ["F01"]},
                ],
                "risk_tags": [],
                "confidence": "medium",
            }
        return LlmResponse(
            content=json.dumps(content, ensure_ascii=False),
            model=model,
            prompt_version=prompt_version,
            usage=LlmUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def _insert_stock(
    connection: duckdb.DuckDBPyConnection,
    code: str,
    name: str,
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
            (
                code,
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
    connection.executemany(
        "INSERT INTO financials (code, report_period, source, ann_date, revenue, "
        "net_profit_parent, ocf, total_assets, total_liab, cash, interest_debt, "
        "receivables, roe, roic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
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
            for period, ann_date, revenue, profit, ocf in (
                (date(2023, 12, 31), date(2024, 4, 20), 100.0, 10.0, 12.0),
                (date(2024, 12, 31), date(2025, 4, 20), 110.0, 12.0, 13.0),
                (date(2025, 12, 31), date(2026, 4, 20), 121.0, 14.0, 15.0),
            )
        ],
    )
    connection.executemany(
        "INSERT INTO valuation_daily (code, trade_date, pe_ttm, pb, ps_ttm) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (code, AS_OF - timedelta(days=index), 15.0, 1.5, 1.2)
            for index in range(700)
        ],
    )
    connection.execute(
        "INSERT INTO announcements (ann_id, code, ann_date, title, category, text) "
        "VALUES (?, ?, ?, '年度报告', '定期报告', ?)",
        [f"{code}-1", code, AS_OF - timedelta(days=3), MATERIAL_TEXT],
    )


def test_calibration_passes_when_five_of_seven_in_range() -> None:
    rows = tuple(
        CalibrationRow(
            code=stock.code,
            name=stock.name,
            low=stock.low,
            high=stock.high,
            label=stock.label,
            status="ok",
            score=(stock.low + stock.high) // 2 if index < 5 else 99,
            tier="0-10",
        )
        for index, stock in enumerate(CALIBRATION_STOCKS)
    )
    assert CalibrationResult("x", AS_OF, rows).passed is True
    assert CalibrationResult("x", AS_OF, rows[:4]).passed is False


def test_run_calibration_writes_all_seven(tmp_path: Path) -> None:
    settings = load_settings()
    with duckdb.connect(str(tmp_path / "calibrate.duckdb")) as connection:
        apply_migrations(connection)
        for stock in CALIBRATION_STOCKS:
            _insert_stock(connection, stock.code, stock.name)
        client = FakeClient(SCORES)

        result = run_calibration(
            connection,
            settings,
            client=client,
            as_of=AS_OF,
        )

        assert [row.code for row in result.rows] == list(CALIBRATION_CODES)
        assert result.in_range_count == 7
        assert result.failed_count == 0
        assert result.passed is True
        assert client.calls == 14

        tier1_count = connection.execute(
            "SELECT count(*) FROM tier1_dossiers WHERE run_id = ?",
            [result.run_id],
        ).fetchone()[0]
        tier2_count = connection.execute(
            "SELECT count(*) FROM tier2_scores WHERE run_id = ?",
            [result.run_id],
        ).fetchone()[0]
        assert tier1_count == 7
        assert tier2_count == 7
        status, step_status = connection.execute(
            "SELECT status, step_status FROM run_log WHERE run_id = ?",
            [result.run_id],
        ).fetchone()
        assert status == "success"
        assert json.loads(step_status) == {}
