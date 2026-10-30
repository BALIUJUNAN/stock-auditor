"""Stage 0 硬过滤：板块、名称、上市天数、行业、流动性与停牌。

按任务书第 6 节顺序检查；所有不通过原因都会保留，便于写入 ``filter_log``。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from stock_auditor.config import Settings
from stock_auditor.domain import FilterResult, QuoteBar, StockInfo


def _mean(values: Sequence[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def evaluate_stage0(
    stock: StockInfo,
    quotes: Sequence[QuoteBar],
    settings: Settings,
    as_of: date,
) -> FilterResult:
    """返回是否通过及全部剔除原因；``quotes`` 为按日期升序的日线。"""
    rules = settings.stage0
    universe = settings.universe
    reasons: list[str] = []

    if stock.board not in universe.boards:
        reasons.append(f"板块不在范围：{stock.board or '未知'}")

    for keyword in universe.exclude_name_keywords:
        if keyword in stock.name:
            reasons.append(f"简称含排除词：{keyword}")
            break

    if stock.list_date is None:
        reasons.append("上市日期缺失")
    else:
        listed_days = (as_of - stock.list_date).days
        if listed_days < universe.min_listing_days:
            reasons.append(f"上市不足 {universe.min_listing_days} 天：{listed_days} 天")

    if stock.sw_l1 in universe.exclude_sw_l1:
        reasons.append(f"申万一级行业排除：{stock.sw_l1}")

    recent = list(quotes[-rules.turnover_window :])
    if len(recent) < rules.turnover_window:
        reasons.append(
            f"行情数据不足：{len(recent)}/{rules.turnover_window} 个交易日"
        )
    else:
        suspended = sum(1 for bar in recent if bar.is_suspended)
        if suspended > rules.max_suspended_days_20:
            reasons.append(f"近 {rules.turnover_window} 日停牌 {suspended} 天")

        avg_turnover = _mean([bar.turnover for bar in recent])
        if avg_turnover is None:
            reasons.append("换手率数据缺失")
        elif not (rules.turnover_min <= avg_turnover <= rules.turnover_max):
            reasons.append(
                f"平均换手率 {avg_turnover:.2%} 不在 "
                f"[{rules.turnover_min:.0%}, {rules.turnover_max:.0%}]"
            )

        avg_amount = _mean([bar.amount for bar in recent])
        if avg_amount is None:
            reasons.append("成交额数据缺失")
        elif avg_amount < rules.min_avg_amount_cny:
            reasons.append(
                f"日均成交额 {avg_amount:.0f} 低于 {rules.min_avg_amount_cny:.0f}"
            )

    return FilterResult(code=stock.code, passed=not reasons, reasons=reasons)
