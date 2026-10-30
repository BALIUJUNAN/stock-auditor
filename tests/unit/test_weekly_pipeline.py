"""T3.1：周日流水线 S1~S8、断点续跑与并发锁。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from stock_auditor.config import load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.llm.client import LlmResponse, LlmUsage
from stock_auditor.pipeline import (
    FileLock,
    PipelineLockedError,
    run_weekly,
)

AS_OF = date(2026, 10, 29)
NOW = datetime(2026, 10, 29, 20, 0, 0)
MATERIAL_TEXT = "公司于本报告期内实现营业收入同比增长，主要得益于新产品放量。" * 20
QUOTE = MATERIAL_TEXT[:120]

SCORES = {"000001": 30, "000002": 32}


def _tier_for(score: int) -> str:
    for label, low, high in (
        ("21-30", 21, 30),
        ("31-35", 31, 35),
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


class FlakyClient(FakeClient):
    """在指定调用序号上抛出非 ``LlmCallError``，模拟进程/网络中断。"""

    def __init__(self, scores: dict[str, int], fail_calls: set[int]) -> None:
        super().__init__(scores)
        self.fail_calls = fail_calls

    def complete(self, prompt: str, **kwargs: Any) -> LlmResponse:
        if self.calls + 1 in self.fail_calls:
            self.calls += 1
            raise RuntimeError("模拟模型调用中断")
        return super().complete(prompt, **kwargs)


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
        "INSERT INTO valuation_daily (code, trade_date, pe_ttm, pb, ps_ttm) VALUES (?, ?, ?, ?, ?)",
        [(code, AS_OF - timedelta(days=index), 15.0, 1.5, 1.2) for index in range(700)],
    )
    connection.execute(
        "INSERT INTO announcements (ann_id, code, ann_date, title, category, text) "
        "VALUES (?, ?, ?, '年度报告', '定期报告', ?)",
        [f"{code}-1", code, AS_OF - timedelta(days=3), MATERIAL_TEXT],
    )


def _database(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(tmp_path / "weekly.duckdb"))
    apply_migrations(connection)
    _insert_stock(connection, "000001", "测试甲")
    _insert_stock(connection, "000002", "测试乙")
    return connection


def test_full_pipeline_runs_s1_to_s8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    client = FakeClient(SCORES)
    with _database(tmp_path) as connection:
        result = run_weekly(
            connection,
            load_settings(),
            as_of=AS_OF,
            codes=["000001", "000002"],
            client=client,
            push=False,
            now=NOW,
        )

        assert result.run_id == "weekly-20261029-200000"
        assert result.universe_count == 2
        assert {entry.code for entry in result.pool} == {"000001", "000002"}
        assert client.calls == 4
        assert result.audit_ok_count == 2
        assert result.audit_failed_count == 0
        assert set(result.final_scores) == {"000001", "000002"}
        assert all(item.final_total is not None for item in result.final_scores.values())

        status, step_status, tokens = connection.execute(
            "SELECT status, step_status, llm_tokens FROM run_log WHERE run_id = ?",
            [result.run_id],
        ).fetchone()
        assert status == "success"
        assert json.loads(step_status) == {
            step: "done" for step in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
        }
        assert tokens == 60

        assert result.report_path is not None
        assert result.report_path.exists()
        assert result.chart_path is not None
        assert result.chart_path.exists()
        assert result.chart_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        markdown = result.report_path.read_text(encoding="utf-8")
        assert "PEG 暂未评分（按 0 分计入）" in markdown
        assert all(item.imputed.get("peg_unavailable") for item in result.fundamentals.values())
        assert "# 周报 weekly-20261029-200000" in markdown
        assert "测试甲" in markdown
        assert f"- 数据日期：{AS_OF}" in markdown
        assert f"- 图表：{result.chart_path}" in markdown
        assert "## 本周 Top 20" in markdown

        report_row = connection.execute(
            "SELECT report_json, markdown, pushed_at FROM weekly_reports WHERE run_id = ?",
            [result.run_id],
        ).fetchone()
        assert report_row is not None
        payload = json.loads(report_row[0])
        assert payload["as_of"] == AS_OF.isoformat()
        assert payload["status"] == "success"
        assert payload["counts"]["pool"] == 2
        assert report_row[1] == markdown
        assert report_row[2] is None

        assert (
            connection.execute(
                "SELECT count(*) FROM tier1_dossiers WHERE run_id = ?",
                [result.run_id],
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM tier2_scores WHERE run_id = ?",
                [result.run_id],
            ).fetchone()[0]
            == 2
        )


def test_resume_after_s6_failure_reuses_finished_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    failing = FlakyClient(SCORES, fail_calls={3})
    with _database(tmp_path) as connection:
        with pytest.raises(RuntimeError, match="模拟模型调用中断"):
            run_weekly(
                connection,
                load_settings(),
                as_of=AS_OF,
                codes=["000001", "000002"],
                client=failing,
                push=False,
                now=NOW,
            )

        run_id, status, step_status = connection.execute(
            "SELECT run_id, status, step_status FROM run_log"
        ).fetchone()
        assert status == "failed"
        steps = json.loads(step_status)
        assert steps["S1"] == "done"
        assert steps["S5"] == "done"
        assert steps["S6"].startswith("failed:")
        assert failing.calls == 3
        assert (
            connection.execute(
                "SELECT count(*) FROM tier1_dossiers WHERE run_id = ?", [run_id]
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM tier2_scores WHERE run_id = ?", [run_id]
            ).fetchone()[0]
            == 0
        )

        resumed_client = FakeClient(SCORES)
        result = run_weekly(
            connection,
            load_settings(),
            resume=True,
            client=resumed_client,
            push=False,
        )

        assert result.run_id == run_id
        assert resumed_client.calls == 2
        assert result.audit_ok_count == 2
        assert result.report_path is not None
        assert result.report_path.exists()

        assert connection.execute("SELECT count(*) FROM run_log").fetchone()[0] == 1
        final_status, final_steps = connection.execute(
            "SELECT status, step_status FROM run_log WHERE run_id = ?", [run_id]
        ).fetchone()
        assert final_status == "success"
        final_steps = json.loads(final_steps)
        assert final_steps["S6"] == "done"
        assert final_steps["S8"] == "done"


def test_lock_prevents_concurrent_weekly_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with _database(tmp_path) as connection:
        with FileLock("weekly"), pytest.raises(PipelineLockedError):
            run_weekly(
                connection,
                load_settings(),
                as_of=AS_OF,
                codes=["000001"],
                push=False,
                now=NOW,
            )
        assert connection.execute("SELECT count(*) FROM run_log").fetchone()[0] == 0

    run_counts = list((tmp_path / "state").glob("*.json")) if (tmp_path / "state").exists() else []
    assert run_counts == []


def test_resume_without_failed_run_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with _database(tmp_path) as connection, pytest.raises(ValueError, match="没有可续跑"):
        run_weekly(
            connection,
            load_settings(),
            resume=True,
            client=FakeClient(SCORES),
            push=False,
        )


def test_weekly_degrades_when_llm_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with _database(tmp_path) as connection:
        result = run_weekly(
            connection,
            load_settings(),
            as_of=AS_OF,
            codes=["000001", "000002"],
            push=False,
            now=NOW,
        )

        assert result.llm_skipped is True
        assert result.llm_skip_reason
        assert result.audit_ok_count == 0
        assert result.audit_failed_count == 0
        assert result.report_path is not None
        assert result.chart_path is not None
        assert result.chart_path.exists()
        markdown = result.report_path.read_text(encoding="utf-8")
        assert "模型审计：未执行" in markdown
        assert "本次未执行模型审计" in markdown
        assert "- 排序：按量化总分" in markdown
        assert "测试甲" in markdown
        assert f"- 图表：{result.chart_path}" in markdown

        status, step_status = connection.execute(
            "SELECT status, step_status FROM run_log WHERE run_id = ?",
            [result.run_id],
        ).fetchone()
        assert status == "success"
        steps = json.loads(step_status)
        assert steps["S5"].startswith("skipped:")
        assert steps["S6"].startswith("skipped:")
        assert steps["S8"] == "done"


def test_resume_explicit_run_id_selects_that_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with _database(tmp_path) as connection:
        with pytest.raises(RuntimeError, match="模拟模型调用中断"):
            run_weekly(
                connection,
                load_settings(),
                as_of=AS_OF,
                codes=["000001", "000002"],
                client=FlakyClient(SCORES, fail_calls={3}),
                push=False,
                now=NOW,
            )
        target_run_id = connection.execute("SELECT run_id FROM run_log").fetchone()[0]

        other_run_id = "weekly-20991231-235959"
        connection.execute(
            "INSERT INTO run_log (run_id, pipeline, started_at, status, step_status, "
            "llm_tokens, llm_cost) VALUES (?, 'weekly', ?, 'failed', ?, 0, 0)",
            [
                other_run_id,
                datetime(2099, 12, 31, 23, 59, 59),
                json.dumps({"S1": "failed:模拟并发运行"}),
            ],
        )

        result = run_weekly(
            connection,
            load_settings(),
            resume=target_run_id,
            client=FakeClient(SCORES),
            push=False,
        )

        assert result.run_id == target_run_id
        statuses = dict(connection.execute("SELECT run_id, status FROM run_log").fetchall())
        assert statuses[target_run_id] == "success"
        assert statuses[other_run_id] == "failed"


def test_resume_unknown_run_id_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with (
        _database(tmp_path) as connection,
        pytest.raises(ValueError, match="找不到周流水线运行记录"),
    ):
        run_weekly(
            connection,
            load_settings(),
            resume="weekly-20000101-000000",
            client=FakeClient(SCORES),
            push=False,
        )


def test_resume_completed_run_id_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with _database(tmp_path) as connection:
        finished = run_weekly(
            connection,
            load_settings(),
            until="S2",
            as_of=AS_OF,
            codes=["000001"],
            push=False,
            now=NOW,
        )
        with pytest.raises(ValueError, match="已完成，无需续跑"):
            run_weekly(
                connection,
                load_settings(),
                resume=finished.run_id,
                client=FakeClient(SCORES),
                push=False,
            )


def test_unknown_step_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    with _database(tmp_path) as connection, pytest.raises(ValueError, match="不支持的步骤"):
        run_weekly(
            connection,
            load_settings(),
            until="S9",
            codes=["000001"],
            client=FakeClient(SCORES),
            push=False,
            now=NOW,
        )


def test_refresh_loads_universe_after_ingest(tmp_path, monkeypatch):
    import stock_auditor.pipeline.weekly as weekly
    from stock_auditor.ingest.service import IngestSummary

    monkeypatch.setenv("SA_HOME", str(tmp_path))

    def ingest(connection, settings, codes=None, **kwargs):
        connection.execute(
            "INSERT INTO stock_universe (code, name, board, list_date) "
            "VALUES ('000001', 'Example', 'sz_main', DATE '2000-01-01')"
        )
        return IngestSummary()

    monkeypatch.setattr(weekly, "run_ingest", ingest)
    with duckdb.connect(":memory:") as connection:
        apply_migrations(connection)
        result = run_weekly(
            connection,
            load_settings(),
            refresh=True,
            until="S2",
            as_of=AS_OF,
            push=False,
            use_lock=False,
        )
    assert result.universe_count == 1
    assert "000001" in result.filter_results


def test_missing_announcement_text_does_not_invalidate_weekly_results(tmp_path, monkeypatch):
    import stock_auditor.pipeline.weekly as weekly
    from stock_auditor.ingest.service import IngestSummary
    from stock_auditor.pipeline.single import latest_run_id

    monkeypatch.setenv("SA_HOME", str(tmp_path))
    monkeypatch.setattr(
        weekly,
        "run_ingest",
        lambda *args, **kwargs: IngestSummary(warnings={"announcement_text": "100 missing"}),
    )
    captured = []

    def backfill(connection, client, **kwargs):
        captured.extend(kwargs["codes"])
        return 0, {}

    monkeypatch.setattr(weekly, "backfill_announcement_text", backfill)
    with _database(tmp_path) as connection:
        result = run_weekly(
            connection,
            load_settings(),
            as_of=AS_OF,
            codes=["000001", "000002"],
            client=FakeClient(SCORES),
            refresh=True,
            push=False,
            now=NOW,
        )
        status, raw = connection.execute(
            "SELECT status,step_status FROM run_log WHERE run_id=?", [result.run_id]
        ).fetchone()
        assert status == "success"
        assert json.loads(raw)["S1_data"].startswith("warning:")
        assert set(captured) == {entry.code for entry in result.pool}
        assert latest_run_id(connection, "weekly", as_of=AS_OF) == result.run_id
        assert "公告正文提示" in result.report_path.read_text(encoding="utf8")


def test_single_stock_refresh_failure_blocks_weekly_before_scoring(tmp_path, monkeypatch):
    import stock_auditor.pipeline.weekly as weekly
    from stock_auditor.ingest.service import IngestSummary

    monkeypatch.setenv("SA_HOME", str(tmp_path))
    summary = IngestSummary(
        errors={"quotes": "000001: unavailable"}, failed_codes={"quotes": {"000001": "unavailable"}}
    )
    monkeypatch.setattr(weekly, "run_ingest", lambda *args, **kwargs: summary)
    with _database(tmp_path) as connection:
        with pytest.raises(RuntimeError, match="quotes"):
            run_weekly(
                connection,
                load_settings(),
                as_of=AS_OF,
                refresh=True,
                codes=["000001", "000002"],
                push=False,
                now=NOW,
            )
        assert connection.execute("SELECT status FROM run_log").fetchone()[0] == "failed"
        assert connection.execute("SELECT count(*) FROM quant_scores").fetchone()[0] == 0
