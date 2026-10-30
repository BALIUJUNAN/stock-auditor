"""评分引擎公共数学工具。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from stock_auditor.domain import FinancialRow


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def round_half_up(value: float, digits: int = 1) -> float:
    """财务口径四舍五入，避免 Python 的银行家舍入造成分差。"""
    quantizer = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def percentile_rank(value: float, values: Sequence[float]) -> float | None:
    """平均秩百分位：最好为 1，最差为 0；单样本返回 0.5。"""
    valid = [item for item in values if item is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return 0.5
    less = sum(1 for item in valid if item < value)
    equal = sum(1 for item in valid if item == value)
    average_rank = less + (equal + 1) / 2
    return (average_rank - 1) / (len(valid) - 1)


def mean(values: Sequence[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    return current / prior - 1


def cagr(current: float | None, prior: float | None, years: int) -> float | None:
    if current is None or prior is None or current <= 0 or prior <= 0 or years <= 0:
        return None
    return (current / prior) ** (1 / years) - 1


def is_annual(period: date) -> bool:
    return period.month == 12 and period.day == 31


def pit_rows(
    financials: Sequence[FinancialRow],
    as_of: date,
) -> dict[date, FinancialRow]:
    """按公告日过滤，同一报告期保留最新公告的一行。"""
    rows: dict[date, FinancialRow] = {}
    for row in financials:
        if row.ann_date is not None and row.ann_date > as_of:
            continue
        if row.report_period > as_of:
            continue
        existing = rows.get(row.report_period)
        if existing is None or (row.ann_date or date.min) >= (
            existing.ann_date or date.min
        ):
            rows[row.report_period] = row
    return rows


def annual_rows(rows: Mapping[date, FinancialRow]) -> list[FinancialRow]:
    return [rows[period] for period in sorted(rows) if is_annual(period)]


def ttm_value(
    rows: Mapping[date, FinancialRow],
    period: date,
    field: str,
) -> float | None:
    """把累计报表值还原成 TTM；缺失上年同期或上年年报时返回 None。"""
    row = rows.get(period)
    if row is None:
        return None
    current = getattr(row, field)
    if current is None:
        return None
    if is_annual(period):
        return current
    prior_annual = rows.get(date(period.year - 1, 12, 31))
    prior_same = rows.get(date(period.year - 1, period.month, period.day))
    if prior_annual is None or prior_same is None:
        return None
    annual_value = getattr(prior_annual, field)
    same_value = getattr(prior_same, field)
    if annual_value is None or same_value is None:
        return None
    return current + annual_value - same_value


def ttm_growth(
    rows: Mapping[date, FinancialRow],
    period: date,
    field: str,
) -> float | None:
    if is_annual(period):
        prior = rows.get(date(period.year - 1, 12, 31))
    else:
        prior = rows.get(date(period.year - 1, period.month, period.day))
    if prior is None:
        return None
    current_ttm = ttm_value(rows, period, field)
    prior_ttm = ttm_value(rows, prior.report_period, field)
    return growth(current_ttm, prior_ttm)
