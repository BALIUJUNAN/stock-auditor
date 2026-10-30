"""一票否决与软降级规则（任务书第 7 节）。

硬 Veto 只由代码触发；模型层只能通过 ``llm_critical_risk`` 标记软降级。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from stock_auditor.config import Settings
from stock_auditor.domain import AnnouncementRow, FinancialRow, StockData

Level = Literal["hard", "soft"]


@dataclass(frozen=True)
class VetoEvent:
    rule: str
    level: Level
    detail: str
    penalty: float = 0.0


def _annual_rows(rows: list[FinancialRow]) -> list[FinancialRow]:
    return sorted(
        (row for row in rows if row.report_period.month == 12 and row.report_period.day == 31),
        key=lambda row: row.report_period,
    )


def _annual_rows_as_of(
    financials: tuple[FinancialRow, ...],
    as_of: date,
) -> list[FinancialRow]:
    return _annual_rows(
        [
            row
            for row in financials
            if row.ann_date is None or row.ann_date <= as_of
        ]
    )


def _contains_any(title: str, keywords: list[str]) -> str | None:
    for keyword in keywords:
        if keyword in title:
            return keyword
    return None


def _matching_announcements(
    announcements: tuple[AnnouncementRow, ...],
    keywords: list[str],
) -> list[tuple[date, str]]:
    matches: list[tuple[date, str]] = []
    for row in announcements:
        keyword = _contains_any(row.title, keywords)
        if keyword is not None:
            matches.append((row.ann_date or date.min, row.title))
    return matches


def _check_investigation(
    announcements: tuple[AnnouncementRow, ...],
    settings: Settings,
) -> VetoEvent | None:
    keywords = settings.veto.keywords
    opened = _matching_announcements(announcements, keywords.investigation)
    if not opened:
        return None
    closed = _matching_announcements(announcements, keywords.investigation_closed)
    latest_open = max(day for day, _ in opened)
    latest_closed = max((day for day, _ in closed), default=date.min)
    if latest_closed >= latest_open:
        return None
    return VetoEvent(
        rule="investigation",
        level="hard",
        detail=f"立案调查未结案：{opened[-1][1]}",
    )


def _check_regulatory_penalty(
    announcements: tuple[AnnouncementRow, ...],
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    lookback = settings.veto.regulatory_lookback_days
    cutoff = as_of - timedelta(days=lookback)
    matches = [
        title
        for day, title in _matching_announcements(
            announcements, settings.veto.keywords.regulatory_penalty
        )
        if cutoff <= day <= as_of
    ]
    if not matches:
        return None
    return VetoEvent(
        rule="regulatory_penalty",
        level="hard",
        detail=f"近 {lookback} 天行政处罚/公开谴责：{matches[-1]}",
    )


def _check_pledge(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    history = [row for row in data.pledge if row.date <= as_of]
    if not history:
        return None
    latest = max(history, key=lambda row: row.date)
    ratio = latest.controlling_pledge_ratio
    if ratio is None or ratio <= settings.veto.pledge_ratio_max:
        return None
    return VetoEvent(
        rule="pledge_ratio",
        level="hard",
        detail=f"控股股东质押比例 {ratio:.2%} 超过 {settings.veto.pledge_ratio_max:.0%}",
    )


def _check_cash_debt(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    annual = _annual_rows_as_of(data.financials, as_of)
    if not annual:
        return None
    latest = annual[-1]
    if latest.total_assets in (None, 0):
        return None
    cash_ratio = (latest.cash or 0.0) / latest.total_assets
    debt_ratio = (latest.interest_debt or 0.0) / latest.total_assets
    limits = settings.veto.cash_debt_both_high
    if cash_ratio >= limits.cash_to_assets and debt_ratio >= limits.interest_debt_to_assets:
        return VetoEvent(
            rule="cash_debt_both_high",
            level="hard",
            detail=(
                f"货币资金/总资产 {cash_ratio:.2%}，"
                f"有息负债/总资产 {debt_ratio:.2%}"
            ),
        )
    return None


def _check_receivable_inflation(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    annual = _annual_rows_as_of(data.financials, as_of)
    if len(annual) < 2:
        return None
    latest, prior = annual[-1], annual[-2]
    if (
        latest.revenue in (None, 0)
        or prior.revenue in (None, 0)
        or latest.receivables in (None, 0)
        or prior.receivables in (None, 0)
        or latest.revenue <= 0
        or prior.revenue <= 0
        or prior.receivables <= 0
    ):
        return None
    revenue_growth = latest.revenue / prior.revenue - 1
    receivable_growth = latest.receivables / prior.receivables - 1
    ar_to_revenue = latest.receivables / latest.revenue
    limits = settings.veto.receivable_inflation
    if (
        receivable_growth - revenue_growth > limits.growth_gap
        and ar_to_revenue > limits.ar_to_revenue
    ):
        return VetoEvent(
            rule="receivable_inflation",
            level="hard",
            detail=(
                f"应收增速 {receivable_growth:.2%} 高于营收增速 "
                f"{revenue_growth:.2%}，应收/营收 {ar_to_revenue:.2%}"
            ),
        )
    return None


def check_hard_veto(data: StockData, settings: Settings, as_of: date) -> list[VetoEvent]:
    """返回全部硬 Veto 事件；任一事件即剔除该股。"""
    checks = [
        _check_investigation(data.announcements, settings),
        _check_regulatory_penalty(data.announcements, settings, as_of),
        _check_pledge(data, settings, as_of),
        _check_cash_debt(data, settings, as_of),
        _check_receivable_inflation(data, settings, as_of),
    ]
    return [event for event in checks if event is not None]


def _check_cfo_or_auditor_change(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    cutoff = as_of - timedelta(days=settings.soft_downgrade.cfo_lookback_days)
    matches = [
        title
        for day, title in _matching_announcements(
            data.announcements, settings.soft_downgrade.keywords.cfo_or_auditor_change
        )
        if cutoff <= day <= as_of
    ]
    if not matches:
        return None
    lookback = settings.soft_downgrade.cfo_lookback_days
    return VetoEvent(
        rule="cfo_or_auditor_change",
        level="soft",
        detail=f"近 {lookback} 天财务负责人/审计机构变更：{matches[-1]}",
        penalty=settings.soft_downgrade.penalty_cfo_or_auditor_change,
    )


def _check_negative_ocf(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> VetoEvent | None:
    annual = _annual_rows_as_of(data.financials, as_of)
    if len(annual) < 2:
        return None
    latest, prior = annual[-1], annual[-2]
    if latest.ocf is None or prior.ocf is None:
        return None
    if latest.ocf >= 0 or prior.ocf >= 0:
        return None
    if (
        latest.revenue is None
        or prior.revenue is None
        or prior.revenue <= 0
    ):
        return None
    growth = latest.revenue / prior.revenue - 1
    if growth <= settings.soft_downgrade.negative_ocf_revenue_growth_min:
        return None
    return VetoEvent(
        rule="negative_ocf",
        level="soft",
        detail=f"营收同比增长 {growth:.2%}，最近两个完整年度经营现金流均为负",
        penalty=settings.soft_downgrade.penalty_negative_ocf,
    )


def check_soft_downgrade(
    data: StockData,
    settings: Settings,
    as_of: date,
    *,
    llm_critical_risk: bool = False,
) -> list[VetoEvent]:
    """代码软降级两条规则；``llm_critical_risk`` 由 Tier-2 结果传入。"""
    events = [
        _check_cfo_or_auditor_change(data, settings, as_of),
        _check_negative_ocf(data, settings, as_of),
    ]
    if llm_critical_risk:
        events.append(
            VetoEvent(
                rule="llm_critical_risk",
                level="soft",
                detail="Tier-2 给出 critical 级「疑似炒作」或「叙事背离」",
                penalty=settings.soft_downgrade.penalty_llm_critical_risk,
            )
        )
    return [event for event in events if event is not None]
