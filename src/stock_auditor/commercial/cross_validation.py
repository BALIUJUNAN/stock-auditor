"""开源源与商业源财务数据交叉验证。

营收、归母净利润、经营现金流三项，任一报告期任一项偏差超过阈值即标记
「数据存疑」；没有任何可比数据时标记「未交叉验证」。标记写入
``quant_scores.data_flag``（由评分层负责落库），存疑股票不进入 LLM 环节。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from stock_auditor.commercial.base import FinancialRecord

FIELDS = ("revenue", "net_profit_parent", "ocf")


def relative_deviation(open_value: float, commercial_value: float) -> float:
    """以两值绝对值较大者为分母，避免开源源为 0 时除零。"""
    scale = max(abs(open_value), abs(commercial_value))
    if scale == 0:
        return 0.0
    return abs(open_value - commercial_value) / scale


def _index(records: Iterable[FinancialRecord]) -> dict[str, dict[date, FinancialRecord]]:
    indexed: dict[str, dict[date, FinancialRecord]] = {}
    for record in records:
        indexed.setdefault(record.code, {})[record.report_period] = record
    return indexed


def cross_validate(
    codes: Sequence[str],
    open_records: Iterable[FinancialRecord],
    commercial_records: Iterable[FinancialRecord],
    *,
    max_deviation: float,
    missing_label: str,
    suspect_label: str,
) -> dict[str, str | None]:
    """返回每只股票的数据标记：``None`` 表示校验通过。"""
    open_index = _index(open_records)
    commercial_index = _index(commercial_records)
    flags: dict[str, str | None] = {}
    for code in codes:
        open_periods = open_index.get(code, {})
        commercial_periods = commercial_index.get(code, {})
        compared = False
        suspect = False
        for period, open_row in open_periods.items():
            commercial_row = commercial_periods.get(period)
            if commercial_row is None:
                continue
            for field in FIELDS:
                open_value = getattr(open_row, field)
                commercial_value = getattr(commercial_row, field)
                if open_value is None or commercial_value is None:
                    continue
                compared = True
                if relative_deviation(open_value, commercial_value) > max_deviation:
                    suspect = True
        if suspect:
            flags[code] = suspect_label
        elif compared:
            flags[code] = None
        else:
            flags[code] = missing_label
    return flags
