"""总分合成、星级、软降级封顶（任务书第 7.2、10 节）。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from stock_auditor.config import Settings
from stock_auditor.filters.veto import VetoEvent
from stock_auditor.scoring.common import round_half_up


@dataclass(frozen=True)
class CompositeResult:
    raw_total: float | None
    final_total: float | None
    quant_total: float
    stars: int | None
    is_yellow: bool
    is_veto: bool
    soft_events: list[VetoEvent] = field(default_factory=list)


def compose_score(
    fundamental: float,
    momentum: float,
    outlook: float | None,
    settings: Settings,
    *,
    hard_veto: bool = False,
    soft_events: Sequence[VetoEvent] = (),
) -> CompositeResult:
    """``outlook`` 为 None 表示未进入 LLM 池，只保留量化 60 分、不评星。"""
    quant_total = round_half_up(fundamental + momentum)
    events = list(soft_events)

    if hard_veto:
        return CompositeResult(
            raw_total=quant_total,
            final_total=0.0,
            quant_total=quant_total,
            stars=0,
            is_yellow=bool(events),
            is_veto=True,
            soft_events=events,
        )

    if outlook is None:
        return CompositeResult(
            raw_total=None,
            final_total=None,
            quant_total=quant_total,
            stars=None,
            is_yellow=bool(events),
            is_veto=False,
            soft_events=events,
        )

    raw_total = round_half_up(quant_total + outlook)
    penalty = sum(event.penalty for event in events)
    if penalty > 0:
        final_total = round_half_up(
            min(raw_total - penalty, settings.soft_downgrade.cap)
        )
    else:
        final_total = raw_total

    if final_total >= settings.score.star5:
        stars = 5
    elif final_total >= settings.score.star4:
        stars = 4
    else:
        stars = 0

    return CompositeResult(
        raw_total=raw_total,
        final_total=final_total,
        quant_total=quant_total,
        stars=stars,
        is_yellow=bool(events),
        is_veto=False,
        soft_events=events,
    )
