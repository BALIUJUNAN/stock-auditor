"""财务三表与财务指标采集，按报告期合并成一行。"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import structlog

from stock_auditor.config import Settings
from stock_auditor.ingest.common import (
    DataClient,
    clean_number,
    em_symbol,
    exchange_prefix,
    frame_records,
    normalize_code,
    to_date,
)

log = structlog.get_logger(__name__)

FINANCIAL_COLUMNS = (
    "code",
    "report_period",
    "source",
    "ann_date",
    "revenue",
    "net_profit_parent",
    "ocf",
    "total_assets",
    "total_liab",
    "cash",
    "interest_debt",
    "receivables",
    "roe",
    "roic",
)

SOURCE = "akshare"


def _ak() -> Any:
    import akshare as ak

    return ak


def _by_period(frame: Any) -> dict[date, dict[str, Any]]:
    indexed: dict[date, dict[str, Any]] = {}
    for record in frame_records(frame):
        period = to_date(record.get("REPORT_DATE"))
        if period is not None:
            indexed[period] = record
    return indexed


def _number(record: dict[str, Any] | None, key: str) -> float | None:
    if record is None:
        return None
    return clean_number(record.get(key))


def _first_number(record: dict[str, Any] | None, *keys: str) -> float | None:
    for key in keys:
        value = _number(record, key)
        if value is not None:
            return value
    return None


def _sum_present(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return math.fsum(present)


def _ratio(record: dict[str, Any] | None, key: str) -> float | None:
    value = _number(record, key)
    return None if value is None else value / 100.0


def fetch_financial_rows(
    client: DataClient,
    code: str,
    periods: int,
) -> list[tuple[Any, ...]]:
    em_code = em_symbol(code)
    indicator_symbol = f"{code}.{exchange_prefix(code).upper()}"
    balance = client.call(
        lambda: _ak().stock_balance_sheet_by_report_em(symbol=em_code),
        description=f"资产负债表 {code}",
    )
    profit = client.call(
        lambda: _ak().stock_profit_sheet_by_report_em(symbol=em_code),
        description=f"利润表 {code}",
    )
    cashflow = client.call(
        lambda: _ak().stock_cash_flow_sheet_by_report_em(symbol=em_code),
        description=f"现金流量表 {code}",
    )
    indicators = client.call(
        lambda: _ak().stock_financial_analysis_indicator_em(
            symbol=indicator_symbol, indicator="按报告期"
        ),
        description=f"财务指标 {code}",
    )

    balances = _by_period(balance)
    profits = _by_period(profit)
    cashflows = _by_period(cashflow)
    metrics = _by_period(indicators)

    report_periods = sorted(
        set(balances) | set(profits) | set(cashflows) | set(metrics),
        reverse=True,
    )[:periods]

    rows: list[tuple[Any, ...]] = []
    for period in report_periods:
        balance_row = balances.get(period)
        profit_row = profits.get(period)
        cash_row = cashflows.get(period)
        metric_row = metrics.get(period)

        revenue = _first_number(profit_row, "OPERATE_INCOME", "TOTAL_OPERATE_INCOME")
        net_profit = _number(profit_row, "PARENT_NETPROFIT")
        ocf = _number(cash_row, "NETCASH_OPERATE")
        total_assets = _number(balance_row, "TOTAL_ASSETS")
        if revenue is None and net_profit is None and total_assets is None:
            continue

        receivables = _first_number(balance_row, "NOTE_ACCOUNTS_RECE", "ACCOUNTS_RECE")
        interest_debt = _sum_present(
            _number(balance_row, "SHORT_LOAN"),
            _number(balance_row, "LONG_LOAN"),
            _number(balance_row, "BOND_PAYABLE"),
            _number(balance_row, "SHORT_BOND_PAYABLE"),
        )
        ann_date = (
            to_date(metric_row.get("NOTICE_DATE")) if metric_row else None
        ) or (to_date(balance_row.get("NOTICE_DATE")) if balance_row else None)

        rows.append(
            (
                code,
                period,
                SOURCE,
                ann_date,
                revenue,
                net_profit,
                ocf,
                total_assets,
                _number(balance_row, "TOTAL_LIABILITIES"),
                _number(balance_row, "MONETARYFUNDS"),
                interest_debt,
                receivables,
                _ratio(metric_row, "ROEJQ"),
                _ratio(metric_row, "ROIC"),
            )
        )
    return rows


def collect_financials(
    client: DataClient,
    settings: Settings,
    codes: list[str],
) -> list[tuple[Any, ...]]:
    """抓取每只股票最近 ``ingest.financial_periods`` 个报告期。"""
    rows: list[tuple[Any, ...]] = []
    for raw_code in codes:
        code = normalize_code(raw_code)
        try:
            rows.extend(
                fetch_financial_rows(client, code, settings.ingest.financial_periods)
            )
        except Exception as exc:  # noqa: BLE001 - 单只失败不阻塞整批
            log.error("ingest.financials.failed", code=code, error=str(exc))
    log.info("ingest.financials.collected", rows=len(rows))
    return rows
