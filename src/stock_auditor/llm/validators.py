"""模型输出校验（任务书 12.5 节）。

Tier-1：结构与枚举不合格时重试；quote 不是材料原文时丢弃该条 fact；
``counter_checks`` 必须覆盖所有「管理层陈述」事实。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from stock_auditor.llm.materials import MaterialItem
from stock_auditor.llm.schemas import (
    CounterCheck,
    KeyFact,
    Tier1Dossier,
    Tier2Score,
)

_MANAGEMENT = "管理层陈述"
_TIER_RANGES: dict[str, tuple[int, int]] = {
    "0-10": (0, 10),
    "11-20": (11, 20),
    "21-30": (21, 30),
    "31-35": (31, 35),
    "36-40": (36, 40),
}
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True)
class Tier1Validation:
    dossier: Tier1Dossier | None
    issues: list[str] = field(default_factory=list)
    dropped_facts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def retryable(self) -> bool:
        return bool(self.issues)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _reference_ids(dossier: Tier1Dossier) -> list[str]:
    refs: list[str] = []
    for flag in dossier.red_flags:
        refs.extend(flag.fact_ids)
    for check in dossier.counter_checks:
        refs.append(check.claim_fact_id)
        refs.extend(check.evidence_fact_ids)
    return refs


def validate_tier1(
    payload: str | Mapping[str, Any],
    materials: Mapping[str, MaterialItem],
) -> Tier1Validation:
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return Tier1Validation(None, issues=[f"JSON 解析失败：{exc}"])
    else:
        data = payload

    try:
        dossier = Tier1Dossier.model_validate(data)
    except ValidationError as exc:
        return Tier1Validation(None, issues=[f"结构校验失败：{exc}"])

    issues: list[str] = []
    warnings: list[str] = []
    dropped: list[str] = []

    parsed_ids = [fact.fact_id for fact in dossier.key_facts]
    if len(set(parsed_ids)) != len(parsed_ids):
        issues.append("fact_id 重复")

    for ref in _reference_ids(dossier):
        if ref not in parsed_ids:
            issues.append(f"引用了不存在的 fact_id：{ref}")

    source_texts = {
        source_id: _squash(item.text) for source_id, item in materials.items()
    }
    kept_facts: list[KeyFact] = []
    for fact in dossier.key_facts:
        source_text = source_texts.get(fact.source_id)
        if source_text is None:
            issues.append(f"{fact.fact_id} 引用了不存在的材料 {fact.source_id}")
            dropped.append(fact.fact_id)
            continue
        if _squash(fact.quote) not in source_text:
            dropped.append(fact.fact_id)
            continue
        if fact.anomaly_flag and not fact.anomaly_description.strip():
            warnings.append(f"{fact.fact_id} 标记异常但未填写说明")
        kept_facts.append(fact)

    if dropped:
        warnings.append(f"丢弃引用不实的 fact：{', '.join(dropped)}")

    kept_ids = {fact.fact_id for fact in kept_facts}

    def clean_refs(ids: list[str], owner: str) -> list[str]:
        valid = [fact_id for fact_id in ids if fact_id in kept_ids]
        if len(valid) != len(ids):
            warnings.append(f"{owner} 的部分 fact 已被丢弃")
        return valid

    red_flags = [
        flag.model_copy(
            update={"fact_ids": clean_refs(flag.fact_ids, flag.flag_id)}
        )
        for flag in dossier.red_flags
    ]

    counter_checks: list[CounterCheck] = []
    for check in dossier.counter_checks:
        if check.claim_fact_id not in kept_ids:
            if check.claim_fact_id in dropped:
                warnings.append(
                    f"counter_check 的 claim {check.claim_fact_id} 已被丢弃"
                )
            continue
        counter_checks.append(
            check.model_copy(
                update={
                    "evidence_fact_ids": clean_refs(
                        check.evidence_fact_ids,
                        f"counter_check {check.claim_fact_id}",
                    )
                }
            )
        )

    checked_claims = {check.claim_fact_id for check in counter_checks}
    for fact in kept_facts:
        if fact.category == _MANAGEMENT and fact.fact_id not in checked_claims:
            issues.append(f"管理层陈述 {fact.fact_id} 缺少反向检验")

    result = Tier1Dossier(
        key_facts=kept_facts,
        red_flags=red_flags,
        counter_checks=counter_checks,
        summary=dossier.summary,
    )
    return Tier1Validation(
        dossier=result,
        issues=issues,
        dropped_facts=dropped,
        warnings=warnings,
    )


@dataclass(frozen=True)
class Tier2Validation:
    score: Tier2Score | None
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def retryable(self) -> bool:
        return bool(self.issues)


def _numbers(text: str) -> list[float]:
    return [float(match) for match in _NUMBER.findall(text)]


def _within_one_percent(value: float, reference: float) -> bool:
    if reference == 0:
        return value == 0
    return abs(value - reference) <= abs(reference) * 0.01 + 1e-9


def validate_tier2(
    payload: str | Mapping[str, Any],
    dossier: Tier1Dossier,
    *,
    metric_texts: Sequence[str] | str = (),
) -> Tier2Validation:
    """校验 Tier-2 输出；数字对不上只记告警，不触发重试。"""
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            return Tier2Validation(None, issues=[f"JSON 解析失败：{exc}"])
    else:
        data = payload

    try:
        score = Tier2Score.model_validate(data)
    except ValidationError as exc:
        return Tier2Validation(None, issues=[f"结构校验失败：{exc}"])

    issues: list[str] = []
    warnings: list[str] = []

    low, high = _TIER_RANGES[score.tier]
    if not low <= score.score <= high:
        issues.append(f"score {score.score} 不在档位 {score.tier} 的范围内")

    known_ids = {fact.fact_id for fact in dossier.key_facts}
    referenced = {
        fact_id
        for item in [*score.bear_points, *score.reasons]
        for fact_id in item.fact_ids
    }
    for fact_id in sorted(referenced - known_ids):
        issues.append(f"引用了不存在的 fact_id：{fact_id}")

    if isinstance(metric_texts, str):
        metric_texts = [metric_texts]
    reference_texts = [*metric_texts]
    for fact in dossier.key_facts:
        reference_texts.extend([fact.quote, fact.statement, fact.date.isoformat()])
    references = [
        number for text in reference_texts for number in _numbers(text)
    ]

    seen: set[float] = set()
    for item in [*score.bear_points, *score.reasons]:
        for value in _numbers(item.text):
            if value in seen:
                continue
            seen.add(value)
            if not any(_within_one_percent(value, ref) for ref in references):
                warnings.append(
                    f"数字 {value:g} 未在硬指标表或卷宗中找到"
                )

    return Tier2Validation(score=score, issues=issues, warnings=warnings)
