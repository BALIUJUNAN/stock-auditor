"""周报生成、落库与飞书卡片推送（任务书 14 节）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import structlog

from stock_auditor import paths
from stock_auditor.feishu.base import FeishuChannel, FeishuError
from stock_auditor.feishu.factory import create_feishu_channel
from stock_auditor.report.cards import (
    build_detail_card,
    build_main_card,
    build_receipt_card,
)
from stock_auditor.report.charts import render_weekly_chart

log = structlog.get_logger(__name__)

_REPORT_SQL = """
INSERT OR REPLACE INTO weekly_reports
    (run_id, report_json, markdown, pushed_at, created_at)
VALUES (?, ?, ?, ?, ?)
"""

_ROW_SQL = """
SELECT f.code, COALESCE(u.name, ''), q.fundamental, q.momentum,
       f.raw_total, f.final_total, f.stars, f.is_yellow, f.is_veto,
       t.tier, t.score, t.status, t.payload, d.payload, q.data_flag, q.is_imputed
FROM final_scores f
LEFT JOIN stock_universe u ON u.code = f.code
LEFT JOIN quant_scores q ON q.run_id = f.run_id AND q.code = f.code
LEFT JOIN tier2_scores t ON t.run_id = f.run_id AND t.code = f.code
LEFT JOIN tier1_dossiers d ON d.run_id = f.run_id AND d.code = f.code
WHERE f.run_id = ?
ORDER BY COALESCE(f.final_total, -1) DESC, f.code
"""

_FAILURE_SQL = """
SELECT p.code, COALESCE(u.name, ''), d.status, t.status
FROM llm_pool p
LEFT JOIN stock_universe u ON u.code = p.code
LEFT JOIN tier1_dossiers d ON d.run_id = p.run_id AND d.code = p.code
LEFT JOIN tier2_scores t ON t.run_id = p.run_id AND t.code = p.code
WHERE p.run_id = ?
  AND (COALESCE(d.status, 'missing') <> 'ok'
       OR COALESCE(t.status, 'missing') <> 'ok')
ORDER BY p.code
"""


@dataclass(frozen=True)
class WeeklyRow:
    code: str
    name: str
    fundamental: float | None
    momentum: float | None
    quant_total: float | None
    outlook: float | None
    raw_total: float | None
    final_total: float | None
    stars: int | None
    tier: str | None
    is_yellow: bool
    is_veto: bool
    audit_status: str | None
    reasons: tuple[dict[str, Any], ...] = ()
    bear_points: tuple[dict[str, Any], ...] = ()
    risk_tags: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, str], ...] = ()
    data_flag: str | None = None
    peg_unavailable: bool = False

    @property
    def is_detail(self) -> bool:
        return bool(
            self.stars is not None
            and self.stars >= 4
            and not self.is_veto
            and self.final_total is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "fundamental": self.fundamental,
            "momentum": self.momentum,
            "quant_total": self.quant_total,
            "outlook": self.outlook,
            "raw_total": self.raw_total,
            "final_total": self.final_total,
            "stars": self.stars,
            "tier": self.tier,
            "is_yellow": self.is_yellow,
            "is_veto": self.is_veto,
            "audit_status": self.audit_status,
            "reasons": list(self.reasons),
            "bear_points": list(self.bear_points),
            "risk_tags": list(self.risk_tags),
            "evidence": list(self.evidence),
            "data_flag": self.data_flag,
            "peg_unavailable": self.peg_unavailable,
        }


@dataclass(frozen=True)
class WeeklyReport:
    run_id: str
    as_of: date
    markdown: str
    payload: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None
    chart_path: Path | None = None
    pushed: bool = False


def _load_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _tier2_parts(
    payload: Any,
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    data = _load_json(payload, {})
    if not isinstance(data, dict):
        return (), (), ()
    reasons = tuple(item for item in data.get("reasons", []) if isinstance(item, dict))
    bear_points = tuple(item for item in data.get("bear_points", []) if isinstance(item, dict))
    risk_tags = tuple(item for item in data.get("risk_tags", []) if isinstance(item, dict))
    return reasons, bear_points, risk_tags


def _evidence(
    dossier_payload: Any,
    reasons: tuple[dict[str, Any], ...],
    bear_points: tuple[dict[str, Any], ...],
) -> tuple[dict[str, str], ...]:
    data = _load_json(dossier_payload, {})
    if not isinstance(data, dict):
        return ()
    facts = {
        str(fact.get("fact_id")): fact
        for fact in data.get("key_facts", [])
        if isinstance(fact, dict)
    }
    referenced: list[str] = []
    for item in [*reasons, *bear_points]:
        for fact_id in item.get("fact_ids", []):
            if str(fact_id) in facts and str(fact_id) not in referenced:
                referenced.append(str(fact_id))
    return tuple(
        {
            "fact_id": fact_id,
            "statement": str(facts[fact_id].get("statement", "")),
            "quote": str(facts[fact_id].get("quote", ""))[:160],
        }
        for fact_id in referenced
    )


def collect_weekly_rows(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> tuple[WeeklyRow, ...]:
    rows: list[WeeklyRow] = []
    for record in connection.execute(_ROW_SQL, [run_id]).fetchall():
        (
            code,
            name,
            fundamental,
            momentum,
            raw_total,
            final_total,
            stars,
            is_yellow,
            is_veto,
            tier,
            outlook,
            audit_status,
            tier2_payload,
            dossier_payload,
            data_flag,
            is_imputed,
        ) = record
        reasons, bear_points, risk_tags = _tier2_parts(tier2_payload)
        imputed = _load_json(is_imputed, {})
        if not isinstance(imputed, dict):
            imputed = {}
        rows.append(
            WeeklyRow(
                code=str(code),
                name=str(name),
                fundamental=fundamental,
                momentum=momentum,
                quant_total=(
                    fundamental + momentum
                    if fundamental is not None and momentum is not None
                    else None
                ),
                outlook=outlook,
                raw_total=raw_total,
                final_total=final_total,
                stars=stars,
                tier=tier,
                is_yellow=bool(is_yellow),
                is_veto=bool(is_veto),
                audit_status=audit_status,
                reasons=reasons,
                bear_points=bear_points,
                risk_tags=risk_tags,
                evidence=_evidence(dossier_payload, reasons, bear_points),
                data_flag=data_flag,
                peg_unavailable=bool(
                    imputed.get("peg_unavailable") or imputed.get("consensus_cagr")
                ),
            )
        )
    return tuple(rows)


def _cell(value: object, *, limit: int = 80) -> str:
    text = str(value).replace("|", "｜").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _stars(stars: int | None) -> str:
    return "-" if stars is None else "★" * stars


def _risk_text(risk_tags: tuple[dict[str, Any], ...]) -> str:
    return "、".join(f"{tag.get('tag', '')}({tag.get('severity', '')})" for tag in risk_tags) or "-"


def _reason_text(row: WeeklyRow) -> str:
    if not row.reasons:
        return "-"
    return str(row.reasons[0].get("text", "")) or "-"


def _display_score(row: WeeklyRow) -> float | None:
    """未执行模型审计时 ``final_total`` 为空，用量化总分代替展示与排序。"""
    return row.final_total if row.final_total is not None else row.quant_total


def _score_text(row: WeeklyRow) -> str:
    score = _display_score(row)
    if score is None:
        return "-"
    if row.final_total is None:
        return f"量化 {score:g} 分"
    return f"{score:g} 分"


def _main_markdown(top: list[WeeklyRow], veto_count: int) -> str:
    lines: list[str] = []
    for index, row in enumerate(top[:3], start=1):
        lines.append(
            f"{index}. **{row.name}（{row.code}）** {_stars(row.stars)} {_score_text(row)}"
        )
        lines.append(f"   理由：{_cell(_reason_text(row), limit=120)}")
        lines.append(f"   风险：{_risk_text(row.risk_tags)}")
        if row.peg_unavailable:
            lines.append("   一致预期未使用，PEG 暂未评分（按 0 分计入）")
    if not lines:
        lines.append("本期没有进入推送区的股票。")
    lines.append(f"\n本周新增 Veto：{veto_count} 只")
    lines.append("质押数据不全：控股股东质押硬 Veto 已停用。")
    return "\n".join(lines)


def render_detail_markdown(row: WeeklyRow) -> str:
    lines = [
        f"**总分 {row.final_total:g}**"
        f"（基本面 {row.fundamental or 0:g}/40 · "
        f"前景 {row.outlook or 0:g}/40 · 动量 {row.momentum or 0:g}/20）",
        f"档位：{row.tier or '-'}　星级：{_stars(row.stars)}",
        "",
        "**打分理由**",
    ]
    if row.peg_unavailable:
        lines.insert(2, "一致预期未使用，PEG 暂未评分（按 0 分计入）")
    for index, reason in enumerate(row.reasons[:3], start=1):
        lines.append(f"{index}. {reason.get('text', '')}")
    lines.append("")
    lines.append("**看空理由**")
    for index, point in enumerate(row.bear_points[:2], start=1):
        lines.append(f"{index}. {point.get('text', '')}")
    lines.append("")
    lines.append(f"**风险标签**：{_risk_text(row.risk_tags)}")
    if row.evidence:
        lines.append("")
        lines.append("**证据链**")
        for item in row.evidence:
            lines.append(f"- {item['fact_id']}：{item['statement']}（原文：{item['quote']}）")
    return "\n".join(lines)


def render_weekly_markdown(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        f"# 周报 {payload['run_id']}",
        "",
        f"- 数据日期：{payload['as_of']}",
        f"- 运行状态：{payload['status']}",
        f"- 审计范围：Stage 0 通过 {counts['stage0_passed']} / "
        f"评分 {counts['scored']} 只；LLM 池 {counts['pool']} 只",
        f"- LLM token：{counts['llm_tokens']}；费用：{counts['llm_cost']:.4f} 元",
    ]
    lines.append("- 风控提示：质押数据不全，控股股东质押硬 Veto 已停用。")
    missing_peg = [row for row in payload["top"] if row.get("peg_unavailable")]
    if missing_peg:
        lines.append(
            "- 一致预期未使用或缺失，PEG 暂未评分（按 0 分计入）："
            + "、".join(row["code"] for row in missing_peg)
        )
    for warning in payload.get("material_warnings", []):
        lines.append(f"- 公告正文提示：{warning}")
    if payload.get("audit_skipped"):
        skip_reason = payload.get("audit_skip_reason") or "LLM 未配置"
        lines.append(f"- 模型审计：未执行（{skip_reason}）")
    if payload.get("ranked_by") == "quant" and payload["top"]:
        lines.append("- 排序：按量化总分（模型审计未执行）")
    if payload.get("chart_path"):
        lines.append(f"- 图表：{payload['chart_path']}")
    lines.extend(
        [
            "",
            "## 本周 Top 20",
            "",
            "| 排名 | 代码 | 名称 | 星级 | 总分 | 量化 | 前景 | 档位 | 风险标签 | 一句话理由 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for index, row in enumerate(payload["top"], start=1):
        lines.append(
            f"| {index} | {row['code']} | {row['name']} | {_stars(row['stars'])} | "
            f"{_score(row['final_total'])} | {_score(row['quant_total'])} | "
            f"{_score(row['outlook'])} | {row['tier'] or '-'} | "
            f"{_cell(_risk_text(tuple(row['risk_tags'])))} | "
            f"{_cell(_reason_text_dict(row))} |"
        )
    if not payload["top"]:
        lines.append("| - | - | 本期无 | - | - | - | - | - | - | - |")

    lines.extend(["", "## 黄牌观察区", ""])
    lines.extend(_simple_table(payload["yellow"], "本期无黄牌。"))
    lines.extend(["", "## 否决池", ""])
    lines.extend(_simple_table(payload["veto"], "本期无 Veto。"))
    lines.extend(["", "## 模型审计失败", ""])
    failures = payload["audit_failures"]
    if payload.get("audit_skipped"):
        skip_reason = payload.get("audit_skip_reason") or "LLM 未配置"
        lines.append(f"本次未执行模型审计：{skip_reason}。")
    elif failures:
        for item in failures:
            lines.append(
                f"- {item['code']} {item['name']}："
                f"Tier-1 {item['tier1_status']} / Tier-2 {item['tier2_status']}"
            )
    else:
        lines.append("本期无。")
    lines.append("")
    return "\n".join(lines)


def _score(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _reason_text_dict(row: dict[str, Any]) -> str:
    reasons = row.get("reasons") or []
    if not reasons:
        return "-"
    return str(reasons[0].get("text", "")) or "-"


def _simple_table(rows: list[dict[str, Any]], empty: str) -> list[str]:
    if not rows:
        return [empty]
    lines = [
        "| 代码 | 名称 | 星级 | 总分 | 风险标签 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['code']} | {row['name']} | {_stars(row['stars'])} | "
            f"{_score(row['final_total'])} | "
            f"{_cell(_risk_text(tuple(row['risk_tags'])))} |"
        )
    return lines


def _duration(started: Any, finished: Any) -> str:
    if not isinstance(started, datetime) or not isinstance(finished, datetime):
        return "-"
    seconds = max(0, int((finished - started).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes} 分 {seconds} 秒"


def _push(
    connection: duckdb.DuckDBPyConnection,
    channel: FeishuChannel,
    payload: dict[str, Any],
    rows: tuple[WeeklyRow, ...],
    *,
    chart_path: Path | None,
    duration: str,
) -> bool:
    from stock_auditor.pipeline.outbox import deliver, enqueue

    image_key = None
    if channel.configured and chart_path is not None and chart_path.is_file():
        try:
            image_key = channel.upload_image(chart_path)
        except FeishuError as exc:
            log.warning("weekly.chart_upload_failed", error=str(exc))
    cards = [
        ("main", build_main_card(payload, show_button=channel.name == "app", image_key=image_key))
    ]
    for row in rows:
        if row.is_detail:
            detail = row.to_dict()
            detail["markdown"] = render_detail_markdown(row)
            cards.append((f"detail:{row.code}", build_detail_card(detail)))
    counts = payload["counts"]
    cards.append(
        (
            "receipt",
            build_receipt_card(
                run_id=payload["run_id"],
                status=payload["status"],
                duration=duration,
                llm_tokens=counts["llm_tokens"],
                llm_cost=counts["llm_cost"],
            ),
        )
    )
    ids = [
        enqueue(connection, card, key=f"weekly:{payload['run_id']}:{kind}") for kind, card in cards
    ]
    deliver(connection, channel)
    placeholders = ", ".join("?" for _ in ids)
    pending = connection.execute(
        f"SELECT count(*) FROM alert_outbox WHERE id IN ({placeholders}) AND status <> 'sent'", ids
    ).fetchone()[0]
    return pending == 0


def _audit_skip_reason(value: Any) -> str | None:
    data = _load_json(value, {})
    if not isinstance(data, dict):
        return None
    for status in data.values():
        text = str(status)
        if text.startswith("skipped"):
            _, _, reason = text.partition(":")
            return reason or "LLM 未配置"
    return None


def build_weekly_report(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    *,
    as_of: date | None = None,
    push: bool = False,
    channel: FeishuChannel | None = None,
) -> WeeklyReport:
    log_row = connection.execute(
        "SELECT pipeline, started_at, finished_at, status, llm_tokens, llm_cost, "
        "step_status FROM run_log WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if log_row is None:
        raise ValueError(f"找不到运行记录：{run_id}")
    _, started_at, finished_at, status, llm_tokens, llm_cost, step_status = log_row
    audit_skip_reason = _audit_skip_reason(step_status)
    step_data = _load_json(step_status, {})
    material_warnings = (
        [
            str(value).removeprefix("warning: ")
            for key, value in step_data.items()
            if key in {"S1_data", "S5_materials"} and str(value).startswith("warning:")
        ]
        if isinstance(step_data, dict)
        else []
    )
    if as_of is None:
        as_of = started_at.date() if isinstance(started_at, datetime) else date.today()

    scored = connection.execute(
        "SELECT count(*), sum(CASE WHEN passed THEN 1 ELSE 0 END) FROM filter_log WHERE run_id = ?",
        [run_id],
    ).fetchone()
    pool = connection.execute(
        "SELECT count(*) FROM llm_pool WHERE run_id = ?",
        [run_id],
    ).fetchone()[0]
    rows = collect_weekly_rows(connection, run_id)
    fallback_to_quant = audit_skip_reason is not None or not any(
        row.final_total is not None for row in rows
    )
    if fallback_to_quant:
        ranked = [row for row in rows if not row.is_veto and _display_score(row) is not None]
        ranked.sort(key=lambda row: (-(_display_score(row) or 0.0), row.code))
        ranked_by = "quant"
    else:
        ranked = [row for row in rows if row.final_total is not None and not row.is_veto]
        ranked_by = "final"
    top = [row.to_dict() for row in ranked[:20]]
    yellow = [row.to_dict() for row in rows if row.is_yellow and row.final_total is not None]
    veto = [row.to_dict() for row in rows if row.is_veto]
    failures = (
        []
        if audit_skip_reason
        else [
            {
                "code": str(code),
                "name": str(name),
                "tier1_status": tier1_status or "missing",
                "tier2_status": tier2_status or "missing",
            }
            for code, name, tier1_status, tier2_status in connection.execute(
                _FAILURE_SQL, [run_id]
            ).fetchall()
        ]
    )

    path = paths.reports_dir() / f"{run_id}.md"
    counts = {
        "scored": int(scored[0] or 0),
        "stage0_passed": int(scored[1] or 0),
        "pool": int(pool or 0),
        "llm_tokens": int(llm_tokens or 0),
        "llm_cost": float(llm_cost or 0.0),
    }
    payload: dict[str, Any] = {
        "run_id": run_id,
        "as_of": as_of.isoformat(),
        "status": status or "unknown",
        "counts": counts,
        "top": top,
        "yellow": yellow,
        "veto": veto,
        "audit_failures": failures,
        "audit_skipped": audit_skip_reason is not None,
        "audit_skip_reason": audit_skip_reason,
        "ranked_by": ranked_by,
        "material_warnings": material_warnings,
        "main_markdown": _main_markdown(ranked, len(veto))
        + ("\n公告正文提示：" + "；".join(material_warnings) if material_warnings else ""),
        "footer": f"完整周报：{path}",
        "report_url": path.resolve().as_uri(),
    }
    chart_path: Path | None = None
    try:
        chart_path = render_weekly_chart(payload, paths.reports_dir() / f"{run_id}.png")
    except Exception as exc:  # 图表是可选产出，渲染失败不能阻断周报
        log.warning("weekly.chart_failed", error=str(exc))
    payload["chart_path"] = str(chart_path) if chart_path is not None else None

    markdown = render_weekly_markdown(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    pushed_at = None
    pushed = False
    if push:
        target = channel or create_feishu_channel()
        pushed = _push(
            connection,
            target,
            payload,
            rows,
            chart_path=chart_path,
            duration=_duration(started_at, finished_at),
        )
        if pushed:
            pushed_at = datetime.now()
        else:
            log.warning("weekly.push_pending", run_id=run_id)

    connection.execute(
        _REPORT_SQL,
        [
            run_id,
            json.dumps(payload, ensure_ascii=False),
            markdown,
            pushed_at,
            datetime.now(),
        ],
    )
    return WeeklyReport(
        run_id=run_id,
        as_of=as_of,
        markdown=markdown,
        payload=payload,
        path=path,
        chart_path=chart_path,
        pushed=pushed,
    )


def load_weekly_markdown(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
) -> str | None:
    row = connection.execute(
        "SELECT markdown FROM weekly_reports WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if row is not None and row[0]:
        return str(row[0])
    path = paths.reports_dir() / f"{run_id}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return None
