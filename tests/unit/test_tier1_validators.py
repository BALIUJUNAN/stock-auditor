from __future__ import annotations

from datetime import date
from typing import Any

from stock_auditor.llm.materials import MaterialItem
from stock_auditor.llm.validators import Tier1Validation, validate_tier1

QUOTE = ("公司于本报告期内实现营业收入同比增长，主要得益于新产品放量。" * 8)[:100]


def _materials() -> dict[str, MaterialItem]:
    return {
        "A01": MaterialItem(
            source_id="A01",
            source_type="法定公告",
            date=date(2026, 10, 1),
            title="公告",
            text="开头。" + QUOTE + "结尾。",
        ),
        "A02": MaterialItem(
            source_id="A02",
            source_type="业绩说明会",
            date=date(2026, 9, 20),
            title="纪要",
            text="另一段材料。" + QUOTE + "结束。",
        ),
    }


def _fact(fact_id: str = "F01", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "fact_id": fact_id,
        "category": "业绩",
        "statement": "营业收入同比增长",
        "source_id": "A01",
        "source_type": "法定公告",
        "date": "2026-10-01",
        "quote": QUOTE,
        "context_tags": [],
        "anomaly_flag": False,
        "anomaly_description": "",
    }
    data.update(overrides)
    return data


def _check(
    claim: str = "F02",
    finding: str = "未找到相关信息",
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "claim_fact_id": claim,
        "finding": finding,
        "evidence_fact_ids": evidence or [],
    }


def _dossier(
    facts: list[dict[str, Any]] | None = None,
    *,
    red_flags: list[dict[str, Any]] | None = None,
    counter_checks: list[dict[str, Any]] | None = None,
    summary: str = "本期收入增长，需关注后续订单兑现。",
) -> dict[str, Any]:
    return {
        "key_facts": facts if facts is not None else [_fact()],
        "red_flags": red_flags or [],
        "counter_checks": counter_checks or [],
        "summary": summary,
    }


def _validate(payload: Any, materials: dict[str, MaterialItem] | None = None) -> Tier1Validation:
    return validate_tier1(payload, materials or _materials())


def test_valid_payload_is_accepted() -> None:
    payload = _dossier(
        [
            _fact("F01"),
            _fact(
                "F02",
                category="管理层陈述",
                source_id="A02",
                source_type="业绩说明会",
                date="2026-09-20",
            ),
        ],
        counter_checks=[_check("F02", "支持", ["F01"])],
    )
    result = _validate(payload)
    assert result.dossier is not None
    assert result.issues == []
    assert result.dropped_facts == []
    assert [fact.fact_id for fact in result.dossier.key_facts] == ["F01", "F02"]
    assert result.dossier.counter_checks[0].finding == "支持"
    assert result.retryable is False


def test_mapping_payload_is_accepted() -> None:
    result = _validate(_dossier())
    assert result.dossier is not None
    assert result.dossier.summary.startswith("本期收入增长")


def test_invalid_json_is_retryable() -> None:
    result = _validate("{not json")
    assert result.dossier is None
    assert result.retryable is True
    assert any("JSON" in issue for issue in result.issues)


def test_unknown_enum_is_retryable() -> None:
    result = _validate(_dossier([_fact(category="传闻")]))
    assert result.dossier is None
    assert result.retryable is True
    assert any("结构校验失败" in issue for issue in result.issues)


def test_missing_summary_is_retryable() -> None:
    payload = _dossier()
    del payload["summary"]
    result = _validate(payload)
    assert result.dossier is None
    assert result.retryable is True


def test_statement_over_80_chars_is_retryable() -> None:
    result = _validate(_dossier([_fact(statement="事" * 81)]))
    assert result.dossier is None
    assert result.retryable is True


def test_quote_outside_material_is_dropped() -> None:
    result = _validate(_dossier([_fact(quote="这段内容并不存在于任何材料之中。" * 8)]))
    assert result.dossier is not None
    assert result.dossier.key_facts == []
    assert result.dropped_facts == ["F01"]
    assert result.issues == []
    assert result.retryable is False
    assert any("丢弃引用不实的 fact" in warning for warning in result.warnings)


def test_quote_match_ignores_whitespace() -> None:
    raw = ("甲乙丙丁戊己庚辛壬癸" * 10)[:100]
    material_text = "\n".join(raw[index : index + 10] for index in range(0, 100, 10))
    quote = " ".join(raw[index : index + 10] for index in range(0, 100, 10))
    materials = {
        "A01": MaterialItem(
            source_id="A01",
            source_type="法定公告",
            date=date(2026, 10, 1),
            title="公告",
            text=material_text,
        )
    }
    result = _validate(_dossier([_fact(quote=quote)]), materials)
    assert result.dropped_facts == []
    assert result.dossier is not None
    assert len(result.dossier.key_facts) == 1


def test_management_claim_without_counter_check_is_retryable() -> None:
    result = _validate(
        _dossier([_fact("F01", category="管理层陈述")])
    )
    assert result.dossier is not None
    assert result.retryable is True
    assert any("缺少反向检验" in issue for issue in result.issues)


def test_unknown_source_id_is_retryable_and_dropped() -> None:
    result = _validate(_dossier([_fact(source_id="A99")]))
    assert result.dropped_facts == ["F01"]
    assert result.retryable is True
    assert any("不存在的材料 A99" in issue for issue in result.issues)
    assert result.dossier is not None
    assert result.dossier.key_facts == []


def test_dangling_fact_reference_is_retryable() -> None:
    result = _validate(
        _dossier(
            red_flags=[
                {
                    "flag_id": "R01",
                    "severity": "high",
                    "description": "风险",
                    "fact_ids": ["F99"],
                }
            ]
        )
    )
    assert result.retryable is True
    assert any("F99" in issue for issue in result.issues)


def test_duplicate_fact_ids_are_retryable() -> None:
    result = _validate(_dossier([_fact("F01"), _fact("F01")]))
    assert result.retryable is True
    assert any("fact_id 重复" in issue for issue in result.issues)


def test_counter_check_for_dropped_claim_is_removed() -> None:
    result = _validate(
        _dossier(
            [_fact("F01", quote="完全不存在的引文。" * 12)],
            counter_checks=[_check("F01", "矛盾")],
        )
    )
    assert result.dossier is not None
    assert result.dossier.counter_checks == []
    assert any("已被丢弃" in warning for warning in result.warnings)


def test_red_flag_references_are_cleaned_after_drop() -> None:
    result = _validate(
        _dossier(
            [
                _fact("F01", quote="完全不存在的引文。" * 12),
                _fact("F02"),
            ],
            red_flags=[
                {
                    "flag_id": "R01",
                    "severity": "critical",
                    "description": "风险",
                    "fact_ids": ["F01", "F02"],
                }
            ],
        )
    )
    assert result.dossier is not None
    assert result.dossier.red_flags[0].fact_ids == ["F02"]
    assert any("部分 fact 已被丢弃" in warning for warning in result.warnings)


def test_anomaly_without_description_warns() -> None:
    result = _validate(_dossier([_fact(anomaly_flag=True)]))
    assert result.retryable is False
    assert any("标记异常但未填写说明" in warning for warning in result.warnings)


def test_counter_check_evidence_must_exist() -> None:
    result = _validate(
        _dossier(
            [_fact("F01"), _fact("F02", category="管理层陈述")],
            counter_checks=[_check("F02", "支持", ["F99"])],
        )
    )
    assert result.retryable is True
    assert any("F99" in issue for issue in result.issues)


def test_empty_facts_are_allowed() -> None:
    result = _validate(_dossier([], summary="材料不足，无法形成事实。"))
    assert result.dossier is not None
    assert result.dossier.key_facts == []
    assert result.retryable is False
