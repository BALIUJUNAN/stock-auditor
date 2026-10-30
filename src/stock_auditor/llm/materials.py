"""Tier-1 输入材料组装与截断（任务书 12.2 节）。

优先级：问询函 > 法定公告 > 业绩说明会 > 新闻；同级按日期从近到远。
按 ``llm.tier1_input_token_budget`` 截断，超长材料截取前缀。
每段材料编号 ``A01``、``A02``…，并保留类型与日期。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from stock_auditor.config import Settings, TokenEstimateSettings
from stock_auditor.domain import AnnouncementRow

INQUIRY = "问询函"
LEGAL = "法定公告"
MEETING = "业绩说明会"
NEWS = "新闻"

# 数值越小优先级越高
PRIORITY: dict[str, int] = {
    INQUIRY: 0,
    LEGAL: 1,
    MEETING: 2,
    NEWS: 3,
}


@dataclass(frozen=True)
class MaterialInput:
    source_type: str
    date: date
    title: str
    text: str


@dataclass(frozen=True)
class MaterialItem:
    source_id: str
    source_type: str
    date: date
    title: str
    text: str
    truncated: bool = False


@dataclass(frozen=True)
class MaterialBundle:
    items: tuple[MaterialItem, ...] = ()
    dropped: int = 0
    by_id: dict[str, MaterialItem] = field(default_factory=dict)

    @property
    def text(self) -> str:
        blocks = []
        for item in self.items:
            heading = (
                f"[{item.source_id}] 类型：{item.source_type} | "
                f"日期：{item.date.isoformat()} | 标题：{item.title}"
            )
            blocks.append(f"{heading}\n{item.text}")
        return "\n\n".join(blocks)


def estimate_tokens(text: str, estimate: TokenEstimateSettings) -> int:
    """按中文 1 字 1 token、其余字符 3.5 字符 1 token 估算，再乘安全系数。"""
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = len(text) - cjk
    raw = cjk / estimate.cjk_chars_per_token + other / estimate.ascii_chars_per_token
    return math.ceil(raw * (1 + estimate.safety_margin))


def truncate_to_tokens(
    text: str,
    budget: int,
    estimate: TokenEstimateSettings,
) -> str:
    if budget <= 0:
        return ""
    if estimate_tokens(text, estimate) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle], estimate) <= budget:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def classify_announcement(title: str, category: str | None = None) -> str:
    combined = f"{title} {category or ''}"
    if "问询" in combined:
        return INQUIRY
    if "业绩说明会" in combined or "投资者关系活动" in combined:
        return MEETING
    return LEGAL


def materials_from_announcements(
    announcements: Sequence[AnnouncementRow],
) -> list[MaterialInput]:
    materials = []
    for row in announcements:
        if row.ann_date is None:
            continue
        body = (row.text or "").strip()
        if len(body) < 100:
            continue
        materials.append(
            MaterialInput(
                source_type=classify_announcement(row.title, row.category),
                date=row.ann_date,
                title=row.title,
                text=body,
            )
        )
    return materials


def assemble_materials(
    materials: Sequence[MaterialInput],
    settings: Settings,
    *,
    as_of: date,
) -> MaterialBundle:
    estimate = settings.llm.token_estimate
    start = as_of - timedelta(days=settings.llm.material_lookback_days)
    recent = [
        material
        for material in materials
        if start <= material.date <= as_of
    ]
    # 两次稳定排序：先按日期倒序，再按优先级分组，组内保持日期倒序
    recent.sort(key=lambda material: material.date, reverse=True)
    recent.sort(key=lambda material: _priority(material.source_type))

    budget = settings.llm.tier1_input_token_budget
    used = 0
    items: list[MaterialItem] = []
    dropped = 0
    for material in recent:
        remaining = budget - used
        if remaining <= 0:
            dropped += 1
            continue
        tokens = estimate_tokens(material.text, estimate)
        truncated = tokens > remaining
        text = (
            truncate_to_tokens(material.text, remaining, estimate)
            if truncated
            else material.text
        )
        if truncated and not text:
            dropped += 1
            continue
        used += estimate_tokens(text, estimate)
        items.append(
            MaterialItem(
                source_id=f"A{len(items) + 1:02d}",
                source_type=material.source_type,
                date=material.date,
                title=material.title,
                text=text,
                truncated=truncated,
            )
        )
    by_id = {item.source_id: item for item in items}
    return MaterialBundle(items=tuple(items), dropped=dropped, by_id=by_id)


def _priority(source_type: str) -> int:
    return PRIORITY.get(source_type, len(PRIORITY))
