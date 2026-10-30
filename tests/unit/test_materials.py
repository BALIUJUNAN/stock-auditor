from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_auditor.config import Settings, load_settings
from stock_auditor.domain import AnnouncementRow
from stock_auditor.llm.materials import (
    INQUIRY,
    LEGAL,
    MEETING,
    NEWS,
    MaterialInput,
    assemble_materials,
    classify_announcement,
    estimate_tokens,
    materials_from_announcements,
    truncate_to_tokens,
)

AS_OF = date(2026, 10, 29)


def _settings(budget: int = 60000) -> Settings:
    base = load_settings()
    return base.model_copy(
        update={"llm": base.llm.model_copy(update={"tier1_input_token_budget": budget})}
    )


def _material(
    source_type: str,
    days_ago: int,
    text: str,
    *,
    title: str = "材料",
) -> MaterialInput:
    return MaterialInput(
        source_type=source_type,
        date=AS_OF - timedelta(days=days_ago),
        title=title,
        text=text,
    )


def test_estimate_tokens_handles_chinese_and_ascii() -> None:
    estimate = _settings().llm.token_estimate
    assert estimate_tokens("中" * 10, estimate) == 11
    assert estimate_tokens("a" * 7, estimate) == 3
    assert estimate_tokens("", estimate) == 0


def test_truncate_to_tokens_returns_prefix_within_budget() -> None:
    estimate = _settings().llm.token_estimate
    text = "中" * 100
    result = truncate_to_tokens(text, 30, estimate)
    assert result == "中" * len(result)
    assert len(result) < len(text)
    assert estimate_tokens(result, estimate) <= 30


def test_materials_sorted_by_priority_then_recency() -> None:
    materials = [
        _material(NEWS, 1, "新闻最近"),
        _material(MEETING, 2, "纪要"),
        _material(LEGAL, 5, "公告较旧"),
        _material(LEGAL, 1, "公告较新"),
        _material(INQUIRY, 20, "问询函"),
    ]
    bundle = assemble_materials(materials, _settings(), as_of=AS_OF)
    assert [item.source_type for item in bundle.items] == [
        INQUIRY,
        LEGAL,
        LEGAL,
        MEETING,
        NEWS,
    ]
    assert [item.text for item in bundle.items[:3]] == [
        "问询函",
        "公告较新",
        "公告较旧",
    ]
    assert [item.source_id for item in bundle.items] == [
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
    ]
    assert bundle.by_id["A05"].source_type == NEWS


def test_old_materials_are_dropped() -> None:
    materials = [
        _material(LEGAL, 90, "刚好在窗口内"),
        _material(LEGAL, 91, "超出窗口"),
    ]
    bundle = assemble_materials(materials, _settings(), as_of=AS_OF)
    assert [item.text for item in bundle.items] == ["刚好在窗口内"]


def test_budget_truncates_the_boundary_material() -> None:
    settings = _settings(budget=200)
    materials = [
        _material(INQUIRY, 1, "问" * 50),
        _material(LEGAL, 1, "告" * 50),
        _material(MEETING, 1, "会" * 50),
        _material(NEWS, 1, "闻" * 50),
    ]
    bundle = assemble_materials(materials, settings, as_of=AS_OF)
    estimate = settings.llm.token_estimate
    total = sum(estimate_tokens(item.text, estimate) for item in bundle.items)
    assert total <= 200
    assert len(bundle.items) == 4
    assert bundle.items[-1].source_type == NEWS
    assert bundle.items[-1].truncated is True
    assert bundle.items[-1].text == "闻" * len(bundle.items[-1].text)
    assert len(bundle.items[-1].text) < 50


def test_zero_budget_drops_everything() -> None:
    bundle = assemble_materials([_material(LEGAL, 1, "公告")], _settings(budget=1), as_of=AS_OF)
    assert bundle.items == ()
    assert bundle.dropped == 1


def test_bundle_text_contains_ids_and_metadata() -> None:
    bundle = assemble_materials(
        [_material(INQUIRY, 1, "原文", title="关于问询函的回复")],
        _settings(),
        as_of=AS_OF,
    )
    text = bundle.text
    assert "[A01] 类型：问询函" in text
    assert f"日期：{(AS_OF - timedelta(days=1)).isoformat()}" in text
    assert "标题：关于问询函的回复" in text
    assert "原文" in text


def test_classify_announcement() -> None:
    assert classify_announcement("关于问询函的回复公告") == INQUIRY
    assert classify_announcement("2026年半年度业绩说明会召开情况") == MEETING
    assert classify_announcement("投资者关系活动记录表") == MEETING
    assert classify_announcement("关于重大合同的公告") == LEGAL


def test_materials_from_announcements_uses_title_when_text_missing() -> None:
    rows = [
        AnnouncementRow(
            ann_date=AS_OF,
            title="关于问询函的回复公告",
            category="问询函",
        ),
        AnnouncementRow(ann_date=None, title="无日期公告"),
    ]
    materials = materials_from_announcements(rows)
    assert materials == []


def test_same_source_type_and_date_keeps_input_order() -> None:
    materials = [
        _material(LEGAL, 1, "第一条", title="一"),
        _material(LEGAL, 1, "第二条", title="二"),
    ]
    bundle = assemble_materials(materials, _settings(), as_of=AS_OF)
    assert [item.text for item in bundle.items] == ["第一条", "第二条"]


def test_token_budget_is_not_exceeded_for_whole_items() -> None:
    settings = _settings(budget=1000)
    materials = [_material(LEGAL, index, f"材料{index}" * 10) for index in range(10)]
    bundle = assemble_materials(materials, settings, as_of=AS_OF)
    estimate = settings.llm.token_estimate
    assert sum(estimate_tokens(item.text, estimate) for item in bundle.items) <= 1000
    assert bundle.dropped >= 0
    assert len(bundle.items) < 10 or bundle.dropped == 0


def test_unknown_source_type_is_lowest_priority() -> None:
    materials = [
        _material("其他", 1, "其他"),
        _material(NEWS, 30, "新闻"),
    ]
    bundle = assemble_materials(materials, _settings(), as_of=AS_OF)
    assert [item.source_type for item in bundle.items] == [NEWS, "其他"]


@pytest.mark.parametrize("budget", [10, 50, 200])
def test_assembly_respects_budget_boundaries(budget: int) -> None:
    settings = _settings(budget=budget)
    materials = [_material(LEGAL, 1, "中" * 100)]
    bundle = assemble_materials(materials, settings, as_of=AS_OF)
    estimate = settings.llm.token_estimate
    assert sum(estimate_tokens(item.text, estimate) for item in bundle.items) <= budget
