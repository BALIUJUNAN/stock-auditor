from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from stock_auditor.llm.schemas import KeyFact, Tier1Dossier, Tier2Score
from stock_auditor.llm.validators import Tier2Validation, validate_tier2

QUOTE = ("公司于本报告期内实现营业收入同比增长，主要得益于新产品放量。" * 8)[:100]
PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "prompts" / "tier2_audit.md"
)
METRICS = ["毛利率：32.1%；营业收入：10.0 亿元"]


def _fact(
    fact_id: str,
    *,
    quote: str = QUOTE,
    statement: str = "营业收入同比增长",
) -> KeyFact:
    return KeyFact(
        fact_id=fact_id,
        category="业绩",
        statement=statement,
        source_id="A01",
        source_type="法定公告",
        date=date(2026, 10, 1),
        quote=quote,
    )


def _dossier(*facts: KeyFact) -> Tier1Dossier:
    return Tier1Dossier(
        key_facts=list(facts) or [_fact("F01"), _fact("F02")],
        summary="本期收入增长，需关注后续订单兑现。",
    )


def _payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "bear_points": [
            {"text": "毛利率 32.1% 低于同业", "fact_ids": ["F01"]},
            {"text": "经营现金流下降", "fact_ids": ["F02"]},
        ],
        "tier": "31-35",
        "score": 33,
        "reasons": [
            {"text": "收入保持增长", "fact_ids": ["F01"]},
            {"text": "订单充足", "fact_ids": ["F02"]},
        ],
        "risk_tags": [],
        "confidence": "medium",
    }
    data.update(overrides)
    return data


def _validate(
    payload: Any,
    dossier: Tier1Dossier | None = None,
    metrics: list[str] | None = None,
) -> Tier2Validation:
    return validate_tier2(
        payload,
        dossier or _dossier(),
        metric_texts=METRICS if metrics is None else metrics,
    )


def test_valid_payload_is_accepted() -> None:
    result = _validate(_payload())
    assert result.score is not None
    assert result.issues == []
    assert result.warnings == []
    assert result.retryable is False


def test_invalid_json_is_retryable() -> None:
    result = _validate("{not json")
    assert result.score is None
    assert result.issues
    assert result.retryable is True


def test_unknown_tier_is_retryable() -> None:
    result = _validate(_payload(tier="30-40"))
    assert result.score is None
    assert result.retryable is True


def test_score_out_of_tier_range_is_retryable() -> None:
    result = _validate(_payload(tier="36-40", score=30))
    assert result.score is not None
    assert result.retryable is True
    assert any("不在档位" in issue for issue in result.issues)


@pytest.mark.parametrize(
    ("tier", "score"),
    [
        ("0-10", 0),
        ("0-10", 10),
        ("11-20", 11),
        ("11-20", 20),
        ("21-30", 21),
        ("21-30", 30),
        ("31-35", 31),
        ("31-35", 35),
        ("36-40", 36),
        ("36-40", 40),
    ],
)
def test_tier_boundaries_are_inclusive(tier: str, score: int) -> None:
    result = _validate(_payload(tier=tier, score=score))
    assert result.retryable is False


def test_score_above_40_is_retryable() -> None:
    result = _validate(_payload(score=41))
    assert result.score is None
    assert result.retryable is True


@pytest.mark.parametrize("count", [1, 3])
def test_bear_points_must_be_exactly_two(count: int) -> None:
    points = [
        {"text": f"看空理由 {index}", "fact_ids": ["F01"]} for index in range(count)
    ]
    result = _validate(_payload(bear_points=points))
    assert result.score is None
    assert result.retryable is True


@pytest.mark.parametrize("count", [1, 4])
def test_reasons_must_be_two_or_three(count: int) -> None:
    reasons = [
        {"text": f"理由 {index}", "fact_ids": ["F01"]} for index in range(count)
    ]
    result = _validate(_payload(reasons=reasons))
    assert result.score is None
    assert result.retryable is True


def test_blank_fact_ids_are_rejected() -> None:
    payload = _payload()
    payload["bear_points"][0]["fact_ids"] = []
    result = _validate(payload)
    assert result.score is None
    assert result.retryable is True


def test_dangling_fact_ids_are_retryable() -> None:
    result = _validate(
        _payload(
            bear_points=[
                {"text": "看空理由", "fact_ids": ["F99"]},
                {"text": "另一条看空理由", "fact_ids": ["F98"]},
            ],
            reasons=[
                {"text": "理由", "fact_ids": ["F99"]},
                {"text": "另一条理由", "fact_ids": ["F02"]},
            ],
        )
    )
    assert result.retryable is True
    messages = [issue for issue in result.issues if "不存在的 fact_id" in issue]
    assert len(messages) == 2
    assert any("F98" in issue for issue in messages)
    assert any("F99" in issue for issue in messages)


def test_extra_fields_are_rejected() -> None:
    result = _validate(_payload(note="多余字段"))
    assert result.score is None
    assert result.retryable is True


def test_unknown_number_warns_without_retry() -> None:
    payload = _payload()
    payload["bear_points"][0]["text"] = "毛利率 47.3% 低于同业"
    result = _validate(payload)
    assert result.retryable is False
    assert any("47.3" in warning for warning in result.warnings)


def test_number_from_metric_table_is_accepted() -> None:
    payload = _payload()
    payload["bear_points"][0]["text"] = "毛利率 32.1% 低于同业"
    result = _validate(payload)
    assert result.warnings == []


def test_number_tolerance_is_one_percent() -> None:
    within = _payload()
    within["bear_points"][0]["text"] = "毛利率 32.4% 低于同业"
    assert _validate(within).warnings == []

    outside = _payload()
    outside["bear_points"][0]["text"] = "毛利率 32.6% 低于同业"
    assert _validate(outside).warnings


def test_number_from_quote_is_accepted() -> None:
    quote = ("公司于本报告期内实现营业收入9.5亿元，主要得益于新产品放量。" * 4)[:120]
    dossier = _dossier(_fact("F01", quote=quote), _fact("F02"))
    payload = _payload()
    payload["reasons"][0]["text"] = "营业收入 9.5 亿元"
    result = _validate(payload, dossier)
    assert result.warnings == []


def test_fact_date_number_is_accepted() -> None:
    payload = _payload()
    payload["reasons"][0]["text"] = "2026 年收入保持增长"
    result = _validate(payload)
    assert result.warnings == []


def test_duplicate_missing_number_warns_once() -> None:
    payload = _payload()
    payload["bear_points"][0]["text"] = "毛利率 47.3% 低于同业"
    payload["reasons"][0]["text"] = "毛利率 47.3% 仍在下滑"
    result = _validate(payload)
    assert len([w for w in result.warnings if "47.3" in w]) == 1


def test_metric_texts_accepts_plain_string() -> None:
    result = validate_tier2(
        _payload(), _dossier(), metric_texts="毛利率：32.1%；营业收入：10.0 亿元"
    )
    assert result.warnings == []


def test_tier2_field_order() -> None:
    assert list(Tier2Score.model_fields) == [
        "bear_points",
        "tier",
        "score",
        "reasons",
        "risk_tags",
        "confidence",
    ]


def test_prompt_declares_version_and_field_order() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\nversion: 1\n---\n")
    json_block = text[text.rindex("```json") :]
    assert json_block.index('"bear_points"') < json_block.index('"tier"')
    assert json_block.index('"tier"') < json_block.index('"score"')
