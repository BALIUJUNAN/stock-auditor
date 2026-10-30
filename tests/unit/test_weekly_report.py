"""T3.2：周报 Markdown、飞书卡片与落库。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from stock_auditor.db import apply_migrations
from stock_auditor.feishu import FeishuChannel, FeishuError
from stock_auditor.report import (
    WeeklyRow,
    build_alert_card,
    build_detail_card,
    build_main_card,
    build_receipt_card,
    build_weekly_report,
    collect_weekly_rows,
    load_weekly_markdown,
)
from stock_auditor.report.weekly import render_detail_markdown

RUN_ID = "weekly-20261029-200000"
AS_OF = date(2026, 10, 29)


class RecordingChannel(FeishuChannel):
    name = "webhook"

    def __init__(self, *, fail: bool = False) -> None:
        self.cards: list[dict[str, Any]] = []
        self.fail = fail

    @property
    def configured(self) -> bool:
        return True

    @property
    def status(self) -> str:
        return "已配置"

    def send_card(self, card: dict[str, Any]) -> str:
        if self.fail:
            raise FeishuError("模拟推送失败")
        self.cards.append(card)
        return f"m{len(self.cards)}"


def _seed(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        "INSERT INTO run_log (run_id, pipeline, started_at, finished_at, status, "
        "step_status, llm_tokens, llm_cost, error) "
        "VALUES (?, 'weekly', ?, ?, 'success', '{}', 120, 0.5, NULL)",
        [RUN_ID, datetime(2026, 10, 29, 20, 0, 0), datetime(2026, 10, 29, 20, 5, 0)],
    )
    connection.execute(
        "INSERT INTO stock_universe (code, name, board, list_date, sw_l1, sw_l2) "
        "VALUES ('000001', '测试甲', 'sz_main', DATE '2000-01-01', '电子', '半导体'), "
        "('000002', '测试乙', 'sz_main', DATE '2000-01-01', '医药生物', '化学制药')"
    )
    connection.executemany(
        "INSERT INTO filter_log (run_id, code, passed, reasons) VALUES (?, ?, ?, '[]')",
        [(RUN_ID, "000001", True), (RUN_ID, "000002", False)],
    )
    connection.execute(
        "INSERT INTO quant_scores (run_id, code, raw_values, industry_percentiles, "
        "scores, is_imputed, fundamental, momentum, tags, data_flag) "
        "VALUES (?, '000001', '{}', '{}', '{}', '{}', 35.0, 15.0, '[]', '未交叉验证')",
        [RUN_ID],
    )
    connection.executemany(
        "INSERT INTO llm_pool (run_id, code, source) VALUES (?, ?, 'quant')",
        [(RUN_ID, "000001"), (RUN_ID, "000002")],
    )
    dossier = {
        "key_facts": [
            {
                "fact_id": "F01",
                "category": "业绩",
                "statement": "营业收入同比增长",
                "source_id": "A01",
                "source_type": "法定公告",
                "date": AS_OF.isoformat(),
                "quote": "公司于本报告期内实现营业收入同比增长，主要得益于新产品放量。",
                "context_tags": [],
                "anomaly_flag": False,
                "anomaly_description": "",
            }
        ],
        "red_flags": [],
        "counter_checks": [],
        "summary": "收入增长。",
    }
    connection.execute(
        "INSERT INTO tier1_dossiers (run_id, code, input_hash, model, "
        "prompt_version, payload, status) VALUES (?, '000001', 'h', 'm', 'v', ?, 'ok')",
        [RUN_ID, json.dumps(dossier, ensure_ascii=False)],
    )
    tier2 = {
        "bear_points": [
            {"text": "收入增长依赖单一产品", "fact_ids": ["F01"]},
            {"text": "现金流仍需观察", "fact_ids": ["F01"]},
        ],
        "tier": "21-30",
        "score": 30,
        "reasons": [
            {"text": "收入保持增长", "fact_ids": ["F01"]},
            {"text": "订单仍需验证", "fact_ids": ["F01"]},
        ],
        "risk_tags": [{"tag": "高估值", "severity": "medium"}],
        "confidence": "medium",
    }
    connection.execute(
        "INSERT INTO tier2_scores (run_id, code, input_hash, model, prompt_version, "
        "tier, score, payload, status) "
        "VALUES (?, '000001', 'h', 'm', 'v', '21-30', 30, ?, 'ok')",
        [RUN_ID, json.dumps(tier2, ensure_ascii=False)],
    )
    connection.executemany(
        "INSERT INTO final_scores (run_id, code, raw_total, final_total, stars, "
        "is_yellow, is_veto) VALUES (?, ?, ?, ?, ?, FALSE, ?)",
        [
            (RUN_ID, "000001", 80.0, 80.0, 4, False),
            (RUN_ID, "000002", 0.0, 0.0, 0, True),
        ],
    )


@pytest.fixture()
def connection(tmp_path):
    db = duckdb.connect(str(tmp_path / "report.duckdb"))
    apply_migrations(db)
    _seed(db)
    try:
        yield db
    finally:
        db.close()


def test_weekly_report_markdown_and_row(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=False)

    assert report.run_id == RUN_ID
    assert report.as_of == AS_OF
    assert report.path is not None
    assert report.path.exists()
    markdown = report.markdown
    assert markdown.startswith(f"# 周报 {RUN_ID}")
    assert "| 1 | 000001 | 测试甲 | ★★★★ | 80 | 50 | 30 |" in markdown
    assert "高估值(medium)" in markdown
    assert "本期无黄牌。" in markdown
    assert "| 000002 | 测试乙 |" in markdown
    assert "| 0 | - |" in markdown
    assert "- 000002 测试乙：Tier-1 missing / Tier-2 missing" in markdown
    assert report.payload["top"][0]["code"] == "000001"
    assert report.payload["counts"] == {
        "scored": 2,
        "stage0_passed": 1,
        "pool": 2,
        "llm_tokens": 120,
        "llm_cost": 0.5,
    }

    row = connection.execute(
        "SELECT markdown, pushed_at FROM weekly_reports WHERE run_id = ?",
        [RUN_ID],
    ).fetchone()
    assert row is not None
    assert row[0] == markdown
    assert row[1] is None
    assert not report.pushed


def test_weekly_report_pushes_main_detail_and_receipt(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    channel = RecordingChannel()
    report = build_weekly_report(
        connection,
        RUN_ID,
        as_of=AS_OF,
        push=True,
        channel=channel,
    )

    assert report.pushed is True
    assert len(channel.cards) == 3
    main, detail, receipt = channel.cards
    assert "本周审计 Top 3 · 2026-10-29" in main["header"]["title"]["content"]
    assert "button" not in json.dumps(main, ensure_ascii=False)
    assert "测试甲" in detail["header"]["title"]["content"]
    detail_markdown = detail["body"]["elements"][0]["content"]
    assert "**证据链**" in detail_markdown
    assert "F01" in detail_markdown
    assert "原文：" in detail_markdown
    assert "**看空理由**" in detail_markdown
    assert receipt["body"]["elements"][0]["content"].find(RUN_ID) >= 0
    pushed_at = connection.execute(
        "SELECT pushed_at FROM weekly_reports WHERE run_id = ?",
        [RUN_ID],
    ).fetchone()[0]
    assert pushed_at is not None
    assert connection.execute("SELECT count(*) FROM final_scores").fetchone()[0] == 2


def test_weekly_push_failure_keeps_report(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    report = build_weekly_report(
        connection,
        RUN_ID,
        as_of=AS_OF,
        push=True,
        channel=RecordingChannel(fail=True),
    )

    assert report.pushed is False
    assert report.path is not None and report.path.exists()
    pushed_at = connection.execute(
        "SELECT pushed_at FROM weekly_reports WHERE run_id = ?",
        [RUN_ID],
    ).fetchone()[0]
    assert pushed_at is None


def test_collect_rows_builds_evidence_chain(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    rows = collect_weekly_rows(connection, RUN_ID)
    by_code = {row.code: row for row in rows}
    assert [row.code for row in rows] == ["000001", "000002"]
    detail = by_code["000001"]
    assert detail.is_detail is True
    assert detail.quant_total == 50.0
    assert detail.evidence[0]["fact_id"] == "F01"
    assert detail.evidence[0]["quote"].startswith("公司于本报告期内")
    assert by_code["000002"].is_veto is True
    assert by_code["000002"].is_detail is False


def test_render_detail_markdown_handles_missing_outlook() -> None:
    row = WeeklyRow(
        code="000003",
        name="无展望",
        fundamental=10.0,
        momentum=5.0,
        quant_total=15.0,
        outlook=None,
        raw_total=15.0,
        final_total=15.0,
        stars=0,
        tier=None,
        is_yellow=False,
        is_veto=False,
        audit_status="audit_failed",
        reasons=(),
        bear_points=(),
        risk_tags=(),
        evidence=(),
    )
    text = render_detail_markdown(row)
    assert "基本面 10/40" in text
    assert "前景 0/40" in text
    assert "动量 5/20" in text


def test_cards_render_alert_and_button() -> None:
    alert = build_alert_card(
        code="000001",
        name="测试甲",
        title="质押比例异常",
        detail="控股股东质押比例超过阈值",
        as_of=AS_OF.isoformat(),
    )
    assert alert["schema"] == "2.0"
    assert "测试甲" in alert["header"]["title"]["content"]

    main = build_main_card(
        {
            "as_of": AS_OF.isoformat(),
            "main_markdown": "1. **测试甲（000001）** ★★★★ 80 分",
            "report_url": "file:///tmp/weekly.md",
            "footer": "完整周报：/tmp/weekly.md",
        },
        show_button=True,
    )
    elements = main["body"]["elements"]
    assert any(item.get("tag") == "button" for item in elements)
    detail = build_detail_card({"name": "测试甲", "code": "000001", "markdown": "**总分 80**"})
    assert detail["body"]["elements"][0]["content"] == "**总分 80**"
    receipt = build_receipt_card(
        run_id=RUN_ID,
        status="success",
        duration="5 分 0 秒",
        llm_tokens=120,
        llm_cost=0.5,
    )
    assert RUN_ID in receipt["body"]["elements"][0]["content"]


def test_load_weekly_markdown_falls_back_to_file(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    assert load_weekly_markdown(connection, RUN_ID) is None

    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=False)
    assert load_weekly_markdown(connection, RUN_ID) == report.markdown

    connection.execute("DELETE FROM weekly_reports WHERE run_id = ?", [RUN_ID])
    assert load_weekly_markdown(connection, RUN_ID) == report.markdown
    assert load_weekly_markdown(connection, "weekly-20260101-000000") is None


class ImageRecordingChannel(RecordingChannel):
    def __init__(self, *, fail_upload: bool = False) -> None:
        super().__init__()
        self.uploads: list[Path] = []
        self.fail_upload = fail_upload

    def upload_image(self, path: Path) -> str | None:
        if self.fail_upload:
            raise FeishuError("模拟图片上传失败")
        self.uploads.append(path)
        return "img_test"


def test_weekly_report_renders_chart(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=False)

    assert report.chart_path is not None
    assert report.chart_path.exists()
    assert report.chart_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert report.payload["chart_path"] == str(report.chart_path)
    assert f"- 图表：{report.chart_path}" in report.markdown


def test_weekly_report_ranks_by_quant_when_final_missing(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    connection.execute("UPDATE final_scores SET raw_total = NULL, final_total = NULL, stars = NULL")
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=False)

    assert report.payload["ranked_by"] == "quant"
    assert report.payload["top"][0]["code"] == "000001"
    assert report.payload["top"][0]["quant_total"] == 50.0
    assert "量化 50 分" in report.payload["main_markdown"]
    assert "- 排序：按量化总分" in report.markdown
    assert report.chart_path is not None
    assert report.chart_path.exists()


def test_weekly_push_uploads_chart_image(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    channel = ImageRecordingChannel()
    report = build_weekly_report(
        connection,
        RUN_ID,
        as_of=AS_OF,
        push=True,
        channel=channel,
    )

    assert report.pushed is True
    assert len(channel.uploads) == 1
    assert channel.uploads[0] == report.chart_path
    main = channel.cards[0]
    images = [item for item in main["body"]["elements"] if item.get("tag") == "img"]
    assert images
    assert images[0]["img_key"] == "img_test"


def test_weekly_push_survives_chart_upload_failure(
    connection: duckdb.DuckDBPyConnection, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    channel = ImageRecordingChannel(fail_upload=True)
    report = build_weekly_report(
        connection,
        RUN_ID,
        as_of=AS_OF,
        push=True,
        channel=channel,
    )

    assert report.pushed is True
    assert len(channel.cards) == 3
    assert all(item.get("tag") != "img" for item in channel.cards[0]["body"]["elements"])


def test_weekly_reports_missing_peg_for_affected_stocks(connection, tmp_path, monkeypatch):
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    connection.execute(
        "UPDATE quant_scores SET is_imputed = ? WHERE run_id = ? AND code = '000001'",
        [json.dumps({"peg_unavailable": True}), RUN_ID],
    )
    channel = RecordingChannel()
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=True, channel=channel)
    assert report.payload["top"][0]["peg_unavailable"] is True
    assert "000001" in report.markdown
    assert "PEG 暂未评分（按 0 分计入）" in report.markdown
    assert "PEG 暂未评分（按 0 分计入）" in json.dumps(channel.cards, ensure_ascii=False)


def test_weekly_does_not_report_missing_peg_without_marker(connection, tmp_path, monkeypatch):
    monkeypatch.setenv("SA_HOME", str(tmp_path))
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=False)
    assert report.payload["top"][0]["peg_unavailable"] is False
    assert "PEG 暂未评分" not in report.markdown


def test_weekly_partial_delivery_retries_only_failed_cards(connection, tmp_path, monkeypatch):
    from stock_auditor.pipeline.outbox import deliver

    monkeypatch.setenv("SA_HOME", str(tmp_path))

    class IntermittentChannel(RecordingChannel):
        calls = 0

        def send_card(self, card):
            self.calls += 1
            if self.calls == 2:
                raise FeishuError("temporary failure")
            return super().send_card(card)

    channel = IntermittentChannel()
    report = build_weekly_report(connection, RUN_ID, as_of=AS_OF, push=True, channel=channel)
    assert not report.pushed
    assert len(channel.cards) == 2
    assert (
        connection.execute("SELECT count(*) FROM alert_outbox WHERE status='pending'").fetchone()[0]
        == 1
    )
    assert deliver(connection, channel) == 1
    assert len(channel.cards) == 3
    assert deliver(connection, channel) == 0
