"""单股即时评分：``/查`` 指令与每日流水线共用（复用最近一期量化分，重跑 S5~S8）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from stock_auditor.config import Settings
from stock_auditor.filters.stage0 import evaluate_stage0
from stock_auditor.filters.veto import check_hard_veto, check_soft_downgrade
from stock_auditor.llm.audit import (
    LlmCompleter,
    run_tier1,
    run_tier2,
    store_tier1,
    store_tier2,
)
from stock_auditor.llm.materials import (
    assemble_materials,
    materials_from_announcements,
)
from stock_auditor.llm.metrics import build_metric_text
from stock_auditor.llm.schemas import Tier1Dossier, Tier2Score
from stock_auditor.pipeline.loader import load_universe
from stock_auditor.pipeline.weekly import load_quant_state
from stock_auditor.scoring import (
    CompositeResult,
    FundamentalResult,
    MomentumResult,
    compose_score,
    score_momentum,
    store_final_scores,
)

AUDIT_OK = "ok"
AUDIT_FAILED = "audit_failed"
AUDIT_SKIPPED = "skipped"


@dataclass(frozen=True)
class StockReview:
    code: str
    name: str
    as_of: date
    stage0_passed: bool
    hard_veto: bool
    stage0_reasons: tuple[str, ...]
    data_flag: str | None
    fundamental: FundamentalResult | None
    momentum: MomentumResult | None
    dossier: Tier1Dossier | None
    tier2: Tier2Score | None
    final: CompositeResult | None
    audit_status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    llm_tokens: int = 0
    llm_cost: float = 0.0

    @property
    def quant_total(self) -> float | None:
        if self.fundamental is None or self.momentum is None:
            return None
        return self.fundamental.total + self.momentum.score

    def to_row(self) -> dict[str, Any]:
        reasons = (
            [item.model_dump(mode="json") for item in self.tier2.reasons]
            if self.tier2 is not None
            else []
        )
        bear_points = (
            [item.model_dump(mode="json") for item in self.tier2.bear_points]
            if self.tier2 is not None
            else []
        )
        risk_tags = (
            [item.model_dump(mode="json") for item in self.tier2.risk_tags]
            if self.tier2 is not None
            else []
        )
        return {
            "code": self.code,
            "name": self.name,
            "fundamental": self.fundamental.total if self.fundamental else None,
            "momentum": self.momentum.score if self.momentum else None,
            "quant_total": self.quant_total,
            "outlook": self.tier2.score if self.tier2 else None,
            "raw_total": self.final.raw_total if self.final else None,
            "final_total": self.final.final_total if self.final else None,
            "stars": self.final.stars if self.final else None,
            "tier": self.tier2.tier if self.tier2 else None,
            "is_yellow": self.final.is_yellow if self.final else False,
            "is_veto": self.final.is_veto if self.final else self.hard_veto,
            "audit_status": self.audit_status,
            "reasons": reasons,
            "bear_points": bear_points,
            "risk_tags": risk_tags,
            "evidence": _evidence(self.dossier, reasons, bear_points),
            "data_flag": self.data_flag,
        }


def latest_run_id(
    connection: duckdb.DuckDBPyConnection,
    pipeline: str,
    *,
    as_of: date | None = None,
) -> str | None:
    sql = (
        "SELECT run_id, status, step_status FROM run_log "
        "WHERE pipeline = ? AND status IN ('success', 'partial')"
    )
    params: list[Any] = [pipeline]
    if as_of is not None:
        sql += " AND CAST(started_at AS DATE) <= ?"
        params.append(as_of)
    sql += " ORDER BY started_at DESC"
    for run_id, status, raw_steps in connection.execute(sql, params).fetchall():
        if pipeline != "weekly":
            if status == "success":
                return str(run_id)
            continue
        try:
            steps = json.loads(raw_steps or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(steps, dict):
            continue
        failed = [key for key, value in steps.items() if str(value).startswith("failed")]
        usable = status == "success" and not failed
        # Legacy partial runs with only an announcement-text warning are usable.
        usable = usable or (status == "partial" and failed == ["S1_data"])
        if usable and steps.get("S7") == "done" and steps.get("S8") == "done":
            exists = connection.execute(
                "SELECT 1 FROM weekly_reports WHERE run_id = ?", [run_id]
            ).fetchone()
            if exists:
                return str(run_id)
    return None


def _evidence(
    dossier: Tier1Dossier | None,
    reasons: list[dict[str, Any]],
    bear_points: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if dossier is None:
        return []
    facts = {fact.fact_id: fact for fact in dossier.key_facts}
    referenced: list[str] = []
    for item in [*reasons, *bear_points]:
        for fact_id in item.get("fact_ids", []):
            if str(fact_id) in facts and str(fact_id) not in referenced:
                referenced.append(str(fact_id))
    return [
        {
            "fact_id": fact_id,
            "statement": facts[fact_id].statement,
            "quote": facts[fact_id].quote[:160],
        }
        for fact_id in referenced
    ]


def review_stock(
    connection: duckdb.DuckDBPyConnection,
    settings: Settings,
    code: str,
    *,
    as_of: date,
    client: LlmCompleter | None = None,
    run_id: str | None = None,
    prompt_dir: Path | None = None,
    quant: tuple[FundamentalResult, MomentumResult, str | None] | None = None,
) -> StockReview:
    """重跑单只股票的 S5~S8；量化分默认复用最近一期周流水线结果。

    ``quant`` 用于财报 T+1 全量重算：由调用方按最新全市场截面算好分后传入。
    """
    universe = load_universe(connection, as_of=as_of, codes=[code])
    data = universe.data.get(code)
    if data is None:
        raise ValueError(f"股票池中没有该代码：{code}")

    base = evaluate_stage0(data.stock, data.quotes, settings, as_of)
    hard_events = check_hard_veto(data, settings, as_of)
    reasons = list(base.reasons)
    reasons.extend(f"硬 Veto：{event.rule}（{event.detail}）" for event in hard_events)

    fundamental: FundamentalResult | None = None
    momentum: MomentumResult | None = None
    data_flag: str | None = None
    if quant is not None:
        fundamental, momentum, data_flag = quant
    else:
        weekly_run = latest_run_id(connection, "weekly", as_of=as_of)
        if weekly_run is not None:
            fundamentals, momentums, flags = load_quant_state(connection, weekly_run)
            fundamental = fundamentals.get(code)
            momentum = momentums.get(code)
            data_flag = flags.get(code)
        if momentum is None:
            momentum = score_momentum(data.quotes, settings)

    dossier: Tier1Dossier | None = None
    tier2: Tier2Score | None = None
    audit_status = AUDIT_SKIPPED
    warnings: list[str] = ["质押数据不全：控股股东质押硬 Veto 已停用"]
    if fundamental is not None and fundamental.imputed.get("peg_unavailable"):
        warnings.append("一致预期未使用或缺失，PEG 暂未评分（按 0 分计入）")
    llm_tokens = 0
    llm_cost = 0.0
    if client is not None and fundamental is not None:
        materials = assemble_materials(
            materials_from_announcements(data.announcements),
            settings,
            as_of=as_of,
        )
        if not materials.items:
            audit_status = AUDIT_FAILED
            warnings.append("近窗口内无可用材料")
        else:
            tier1 = run_tier1(
                client,
                stock_code=code,
                stock_name=data.stock.name,
                materials=materials,
                settings=settings,
                as_of=as_of,
                prompt_dir=prompt_dir,
            )
            dossier = tier1.dossier
            llm_tokens += tier1.usage.total_tokens
            llm_cost += tier1.usage.cost
            warnings.extend(tier1.warnings)
            if run_id is not None:
                store_tier1(connection, run_id, code, tier1)
            if dossier is None:
                audit_status = AUDIT_FAILED
                if tier1.error:
                    warnings.append(tier1.error)
            else:
                metric_text = build_metric_text(
                    code=code,
                    name=data.stock.name,
                    fundamental=fundamental,
                    momentum=momentum,
                )
                tier2_outcome = run_tier2(
                    client,
                    stock_code=code,
                    stock_name=data.stock.name,
                    dossier=dossier,
                    metric_text=metric_text,
                    settings=settings,
                    as_of=as_of,
                    prompt_dir=prompt_dir,
                )
                tier2 = tier2_outcome.score
                llm_tokens += tier2_outcome.usage.total_tokens
                llm_cost += tier2_outcome.usage.cost
                warnings.extend(tier2_outcome.warnings)
                audit_status = AUDIT_OK if tier2 is not None else AUDIT_FAILED
                if tier2_outcome.error:
                    warnings.append(tier2_outcome.error)
                if run_id is not None:
                    store_tier2(connection, run_id, code, tier2_outcome)

    outlook = tier2.score if tier2 is not None else None
    risk_tags = tier2.risk_tags if tier2 is not None else []
    critical = any(
        tag.severity == "critical" and tag.tag in ("疑似炒作", "叙事背离") for tag in risk_tags
    )
    soft_events = check_soft_downgrade(
        data,
        settings,
        as_of,
        llm_critical_risk=critical,
    )
    final = compose_score(
        fundamental.total if fundamental is not None else 0.0,
        momentum.score,
        outlook,
        settings,
        hard_veto=bool(hard_events),
        soft_events=soft_events,
    )
    if run_id is not None:
        store_final_scores(connection, run_id, {code: final})

    return StockReview(
        code=code,
        name=data.stock.name,
        as_of=as_of,
        stage0_passed=base.passed and not hard_events,
        hard_veto=bool(hard_events),
        stage0_reasons=tuple(reasons),
        data_flag=data_flag,
        fundamental=fundamental,
        momentum=momentum,
        dossier=dossier,
        tier2=tier2,
        final=final,
        audit_status=audit_status,
        warnings=tuple(warnings),
        llm_tokens=llm_tokens,
        llm_cost=llm_cost,
    )
