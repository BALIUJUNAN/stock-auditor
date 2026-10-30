"""Tier-1 / Tier-2 调用、校验重试与结果落库。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

import duckdb
import structlog

from stock_auditor.config import Settings
from stock_auditor.domain import StockData
from stock_auditor.llm.client import LlmCallError, LlmNotConfiguredError, LlmUsage
from stock_auditor.llm.materials import (
    MaterialBundle,
    assemble_materials,
    materials_from_announcements,
)
from stock_auditor.llm.metrics import build_metric_text
from stock_auditor.llm.prompts import load_prompt, render_prompt
from stock_auditor.llm.schemas import Tier1Dossier, Tier2Score
from stock_auditor.llm.validators import validate_tier1, validate_tier2
from stock_auditor.scoring import FundamentalResult, MomentumResult

log = structlog.get_logger(__name__)

MAX_VALIDATION_RETRIES = 2

_TIER1_SQL = """
INSERT OR REPLACE INTO tier1_dossiers
    (run_id, code, input_hash, model, prompt_version, payload, status, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""
_TIER2_SQL = """
INSERT OR REPLACE INTO tier2_scores
    (run_id, code, input_hash, model, prompt_version, tier, score, payload,
     status, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class LlmCompleter(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        model: str,
        prompt_version: str,
        input_hash: str | None = None,
        response_format: Any | None = None,
        messages: Sequence[dict[str, str]] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class Tier1Outcome:
    dossier: Tier1Dossier | None
    status: str
    model: str
    prompt_version: str
    input_hash: str
    usage: LlmUsage
    warnings: tuple[str, ...] = ()
    error: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class Tier2Outcome:
    score: Tier2Score | None
    status: str
    model: str
    prompt_version: str
    input_hash: str
    usage: LlmUsage
    warnings: tuple[str, ...] = ()
    error: str | None = None
    attempts: int = 1


@dataclass(frozen=True)
class StockAudit:
    code: str
    tier1: Tier1Outcome
    tier2: Tier2Outcome | None = None
    status: str = "audit_failed"
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _merge_usage(usages: Sequence[LlmUsage]) -> LlmUsage:
    return LlmUsage(
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        total_tokens=sum(item.total_tokens for item in usages),
        cost=sum(item.cost for item in usages),
        duration_seconds=sum(item.duration_seconds for item in usages),
        cached=bool(usages) and all(item.cached for item in usages),
    )


def _digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def _retry_prompt(base: str, errors: Sequence[str]) -> str:
    details = "\n".join(f"- {error}" for error in errors)
    return (
        f"{base}\n\n## 上一次输出不合格\n\n{details}\n\n"
        "请修正以上问题，重新输出完整的 JSON。"
    )


def _dossier_json(dossier: Tier1Dossier) -> str:
    return json.dumps(
        dossier.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )


def run_tier1(
    client: LlmCompleter,
    *,
    stock_code: str,
    stock_name: str,
    materials: MaterialBundle,
    settings: Settings,
    as_of: date,
    prompt_dir: Path | None = None,
) -> Tier1Outcome:
    template = load_prompt("tier1_extract", directory=prompt_dir)
    model = settings.llm.tier1_model
    base = render_prompt(
        template,
        stock_code=stock_code,
        stock_name=stock_name,
        as_of=as_of.isoformat(),
        materials=materials.text,
    )

    prompt = base
    usages: list[LlmUsage] = []
    errors: list[str] = []
    attempts = MAX_VALIDATION_RETRIES + 1
    for attempt in range(1, attempts + 1):
        digest = _digest(prompt)
        try:
            response = client.complete(
                prompt,
                model=model,
                prompt_version=template.version,
                input_hash=digest,
            )
        except LlmCallError as exc:
            return Tier1Outcome(
                dossier=None,
                status="audit_failed",
                model=model,
                prompt_version=template.version,
                input_hash=digest,
                usage=_merge_usage(usages),
                error=str(exc),
                attempts=attempt,
            )
        usages.append(response.usage)
        validation = validate_tier1(response.content, materials.by_id)
        if not validation.issues:
            return Tier1Outcome(
                dossier=validation.dossier,
                status="ok",
                model=model,
                prompt_version=template.version,
                input_hash=digest,
                usage=_merge_usage(usages),
                warnings=tuple(validation.warnings),
                attempts=attempt,
            )
        errors = validation.issues
        log.warning(
            "llm.tier1_invalid",
            code=stock_code,
            attempt=attempt,
            issues=errors,
        )
        if attempt < attempts:
            prompt = _retry_prompt(base, errors)

    return Tier1Outcome(
        dossier=None,
        status="audit_failed",
        model=model,
        prompt_version=template.version,
        input_hash=_digest(prompt),
        usage=_merge_usage(usages),
        error="；".join(errors),
        attempts=attempts,
    )


def run_tier2(
    client: LlmCompleter,
    *,
    stock_code: str,
    stock_name: str,
    dossier: Tier1Dossier,
    metric_text: str,
    settings: Settings,
    as_of: date,
    prompt_dir: Path | None = None,
) -> Tier2Outcome:
    template = load_prompt("tier2_audit", directory=prompt_dir)
    model = settings.llm.tier2_model
    base = render_prompt(
        template,
        stock_code=stock_code,
        stock_name=stock_name,
        as_of=as_of.isoformat(),
        metrics=metric_text,
        dossier=_dossier_json(dossier),
    )

    prompt = base
    usages: list[LlmUsage] = []
    errors: list[str] = []
    attempts = MAX_VALIDATION_RETRIES + 1
    for attempt in range(1, attempts + 1):
        digest = _digest(prompt)
        try:
            response = client.complete(
                prompt,
                model=model,
                prompt_version=template.version,
                input_hash=digest,
            )
        except LlmCallError as exc:
            return Tier2Outcome(
                score=None,
                status="audit_failed",
                model=model,
                prompt_version=template.version,
                input_hash=digest,
                usage=_merge_usage(usages),
                error=str(exc),
                attempts=attempt,
            )
        usages.append(response.usage)
        validation = validate_tier2(
            response.content,
            dossier,
            metric_texts=[metric_text],
        )
        if not validation.issues:
            return Tier2Outcome(
                score=validation.score,
                status="ok",
                model=model,
                prompt_version=template.version,
                input_hash=digest,
                usage=_merge_usage(usages),
                warnings=tuple(validation.warnings),
                attempts=attempt,
            )
        errors = validation.issues
        log.warning(
            "llm.tier2_invalid",
            code=stock_code,
            attempt=attempt,
            issues=errors,
        )
        if attempt < attempts:
            prompt = _retry_prompt(base, errors)

    return Tier2Outcome(
        score=None,
        status="audit_failed",
        model=model,
        prompt_version=template.version,
        input_hash=_digest(prompt),
        usage=_merge_usage(usages),
        error="；".join(errors),
        attempts=attempts,
    )


def store_tier1(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    code: str,
    outcome: Tier1Outcome,
) -> None:
    payload = (
        json.dumps(outcome.dossier.model_dump(mode="json"), ensure_ascii=False)
        if outcome.dossier is not None
        else None
    )
    connection.execute(
        _TIER1_SQL,
        [
            run_id,
            code,
            outcome.input_hash,
            outcome.model,
            outcome.prompt_version,
            payload,
            outcome.status,
            datetime.now(),
        ],
    )


def store_tier2(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    code: str,
    outcome: Tier2Outcome,
) -> None:
    score = outcome.score
    payload = (
        json.dumps(score.model_dump(mode="json"), ensure_ascii=False)
        if score is not None
        else None
    )
    connection.execute(
        _TIER2_SQL,
        [
            run_id,
            code,
            outcome.input_hash,
            outcome.model,
            outcome.prompt_version,
            score.tier if score is not None else None,
            float(score.score) if score is not None else None,
            payload,
            outcome.status,
            datetime.now(),
        ],
    )


def audit_stock(
    connection: duckdb.DuckDBPyConnection,
    client: LlmCompleter,
    run_id: str,
    *,
    data: StockData,
    settings: Settings,
    as_of: date,
    fundamental: FundamentalResult | None = None,
    momentum: MomentumResult | None = None,
    prompt_dir: Path | None = None,
) -> StockAudit:
    code = data.stock.code
    materials = assemble_materials(
        materials_from_announcements(data.announcements),
        settings,
        as_of=as_of,
    )
    if not materials.items:
        return StockAudit(
            code=code,
            tier1=Tier1Outcome(
                dossier=None,
                status="audit_failed",
                model=settings.llm.tier1_model,
                prompt_version="",
                input_hash="",
                usage=LlmUsage(),
                error="近窗口内无可用材料",
            ),
            status="audit_failed",
        )

    tier1 = run_tier1(
        client,
        stock_code=code,
        stock_name=data.stock.name,
        materials=materials,
        settings=settings,
        as_of=as_of,
        prompt_dir=prompt_dir,
    )
    store_tier1(connection, run_id, code, tier1)
    if tier1.dossier is None:
        return StockAudit(code=code, tier1=tier1, status="audit_failed")

    metric_text = build_metric_text(
        code=code,
        name=data.stock.name,
        fundamental=fundamental,
        momentum=momentum,
    )
    tier2 = run_tier2(
        client,
        stock_code=code,
        stock_name=data.stock.name,
        dossier=tier1.dossier,
        metric_text=metric_text,
        settings=settings,
        as_of=as_of,
        prompt_dir=prompt_dir,
    )
    store_tier2(connection, run_id, code, tier2)
    return StockAudit(
        code=code,
        tier1=tier1,
        tier2=tier2,
        status=tier2.status,
        warnings=(*tier1.warnings, *tier2.warnings),
    )


__all__ = [
    "MAX_VALIDATION_RETRIES",
    "LlmCompleter",
    "LlmNotConfiguredError",
    "StockAudit",
    "Tier1Outcome",
    "Tier2Outcome",
    "audit_stock",
    "run_tier1",
    "run_tier2",
    "store_tier1",
    "store_tier2",
]
