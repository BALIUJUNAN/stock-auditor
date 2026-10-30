"""Tier-1 / Tier-2 输出的 Pydantic 结构（任务书 12.3、12.4 节）。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactCategory = Literal[
    "业绩",
    "业务进展",
    "订单",
    "产能",
    "研发管线",
    "管理层陈述",
    "监管",
    "股东",
    "其他",
]
SourceType = Literal["问询函", "法定公告", "业绩说明会", "新闻"]
Severity = Literal["critical", "high", "medium"]
Finding = Literal["支持", "矛盾", "未找到相关信息"]
TierLabel = Literal["0-10", "11-20", "21-30", "31-35", "36-40"]
RiskTagName = Literal["疑似炒作", "叙事背离", "业绩变脸风险", "治理风险", "估值透支"]
Confidence = Literal["low", "medium", "high"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class KeyFact(_StrictModel):
    fact_id: str = Field(pattern=r"^F\d{2,}$")
    category: FactCategory
    statement: str = Field(min_length=1, max_length=80)
    source_id: str = Field(pattern=r"^A\d{2,}$")
    source_type: SourceType
    date: date
    quote: str = Field(min_length=100, max_length=300)
    context_tags: list[str] = Field(default_factory=list)
    anomaly_flag: bool = False
    anomaly_description: str = ""


class RedFlag(_StrictModel):
    flag_id: str = Field(pattern=r"^R\d{2,}$")
    severity: Severity
    description: str = Field(min_length=1)
    fact_ids: list[str] = Field(default_factory=list)


class CounterCheck(_StrictModel):
    claim_fact_id: str = Field(pattern=r"^F\d{2,}$")
    finding: Finding
    evidence_fact_ids: list[str] = Field(default_factory=list)


class Tier1Dossier(_StrictModel):
    key_facts: list[KeyFact]
    red_flags: list[RedFlag] = Field(default_factory=list)
    counter_checks: list[CounterCheck] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=500)


class BearPoint(_StrictModel):
    text: str = Field(min_length=1)
    fact_ids: list[str] = Field(min_length=1)


class Tier2Reason(_StrictModel):
    text: str = Field(min_length=1)
    fact_ids: list[str] = Field(min_length=1)


class RiskTag(_StrictModel):
    tag: RiskTagName
    severity: Severity


class Tier2Score(_StrictModel):
    bear_points: list[BearPoint] = Field(min_length=2, max_length=2)
    tier: TierLabel
    score: int = Field(ge=0, le=40)
    reasons: list[Tier2Reason] = Field(min_length=2, max_length=3)
    risk_tags: list[RiskTag] = Field(default_factory=list)
    confidence: Confidence
