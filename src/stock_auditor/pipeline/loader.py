"""从 DuckDB 批量装载评分所需的 ``StockData``。

一次查询各表并按股票代码分组，避免逐只股票多次往返数据库。
所有查询都以 ``as_of`` 截断，Point-in-Time 的公告日判断仍在评分层完成。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import duckdb

from stock_auditor.domain import (
    AnnouncementRow,
    ConsensusRow,
    FinancialRow,
    PledgeRow,
    QuoteBar,
    ResearchRow,
    StockData,
    StockInfo,
    ValuationRow,
)


@dataclass(frozen=True)
class UniverseData:
    stocks: tuple[StockInfo, ...]
    data: dict[str, StockData]


def _code_filter(codes: Sequence[str] | None) -> tuple[str, list[str]]:
    if codes is None:
        return "", []
    placeholders = ", ".join("?" for _ in codes)
    return f" AND code IN ({placeholders})", list(codes)


def _stock_info(row: tuple[object, ...]) -> StockInfo:
    code, name, board, list_date, sw_l1, sw_l2, is_st = row
    return StockInfo(
        code=str(code),
        name=str(name),
        board=str(board) if board is not None else None,
        list_date=list_date,  # type: ignore[arg-type]
        sw_l1=str(sw_l1) if sw_l1 is not None else None,
        sw_l2=str(sw_l2) if sw_l2 is not None else None,
        is_st=bool(is_st),
    )


def load_universe(
    connection: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    codes: Sequence[str] | None = None,
) -> UniverseData:
    """装载股票池及交易、财务、估值、公告、质押、调研数据。"""
    where, params = _code_filter(codes)

    stocks = tuple(
        _stock_info(row)
        for row in connection.execute(
            "SELECT code, name, board, list_date, sw_l1, sw_l2, is_st "
            f"FROM stock_universe WHERE 1=1{where} ORDER BY code",
            params,
        ).fetchall()
    )

    quotes: dict[str, list[QuoteBar]] = {}
    for row in connection.execute(
        "SELECT code, trade_date, open, high, low, close, volume, amount, "
        "turnover, is_suspended FROM daily_quotes "
        f"WHERE trade_date <= ?{where} ORDER BY code, trade_date",
        [as_of, *params],
    ).fetchall():
        quotes.setdefault(str(row[0]), []).append(
            QuoteBar(
                trade_date=row[1],
                open=row[2],
                high=row[3],
                low=row[4],
                close=row[5],
                volume=row[6],
                amount=row[7],
                turnover=row[8],
                is_suspended=bool(row[9]),
            )
        )

    financials: dict[str, list[FinancialRow]] = {}
    for row in connection.execute(
        "SELECT code, report_period, ann_date, revenue, net_profit_parent, ocf, "
        "total_assets, total_liab, cash, interest_debt, receivables, roe, roic "
        f"FROM financials WHERE report_period <= ?{where} "
        "ORDER BY code, report_period, source",
        [as_of, *params],
    ).fetchall():
        financials.setdefault(str(row[0]), []).append(
            FinancialRow(
                code=str(row[0]),
                report_period=row[1],
                ann_date=row[2],
                revenue=row[3],
                net_profit_parent=row[4],
                ocf=row[5],
                total_assets=row[6],
                total_liab=row[7],
                cash=row[8],
                interest_debt=row[9],
                receivables=row[10],
                roe=row[11],
                roic=row[12],
            )
        )

    valuations: dict[str, list[ValuationRow]] = {}
    for row in connection.execute(
        "SELECT code, trade_date, pe_ttm, pb, ps_ttm FROM valuation_daily "
        f"WHERE trade_date <= ?{where} ORDER BY code, trade_date",
        [as_of, *params],
    ).fetchall():
        valuations.setdefault(str(row[0]), []).append(
            ValuationRow(
                trade_date=row[1],
                pe_ttm=row[2],
                pb=row[3],
                ps_ttm=row[4],
            )
        )

    consensus: dict[str, list[ConsensusRow]] = {}
    for row in connection.execute(
        "SELECT code, fetch_date, fiscal_year, np_forecast, revenue_forecast, "
        f"analyst_count FROM consensus WHERE fetch_date <= ?{where} "
        "ORDER BY code, fetch_date, fiscal_year",
        [as_of, *params],
    ).fetchall():
        consensus.setdefault(str(row[0]), []).append(
            ConsensusRow(
                fetch_date=row[1],
                fiscal_year=row[2],
                np_forecast=row[3],
                revenue_forecast=row[4],
                analyst_count=row[5],
            )
        )

    announcements: dict[str, list[AnnouncementRow]] = {}
    for row in connection.execute(
        "SELECT code, ann_date, title, category, text FROM announcements "
        f"WHERE ann_date IS NOT NULL AND ann_date <= ?{where} "
        "ORDER BY code, ann_date",
        [as_of, *params],
    ).fetchall():
        announcements.setdefault(str(row[0]), []).append(
            AnnouncementRow(
                ann_date=row[1],
                title=str(row[2] or ""),
                category=row[3],
                text=row[4],
            )
        )

    pledge: dict[str, list[PledgeRow]] = {}
    for row in connection.execute(
        "SELECT code, date, controlling_pledge_ratio FROM pledge "
        f"WHERE date <= ?{where} ORDER BY code, date",
        [as_of, *params],
    ).fetchall():
        pledge.setdefault(str(row[0]), []).append(
            PledgeRow(date=row[1], controlling_pledge_ratio=row[2])
        )

    research: dict[str, list[ResearchRow]] = {}
    for row in connection.execute(
        "SELECT code, visit_date, org FROM research_visits "
        f"WHERE visit_date <= ?{where} ORDER BY code, visit_date",
        [as_of, *params],
    ).fetchall():
        research.setdefault(str(row[0]), []).append(
            ResearchRow(visit_date=row[1], org=str(row[2]))
        )

    data = {
        stock.code: StockData(
            stock=stock,
            quotes=tuple(quotes.get(stock.code, ())),
            financials=tuple(financials.get(stock.code, ())),
            valuations=tuple(valuations.get(stock.code, ())),
            consensus=tuple(consensus.get(stock.code, ())),
            announcements=tuple(announcements.get(stock.code, ())),
            pledge=tuple(pledge.get(stock.code, ())),
            research=tuple(research.get(stock.code, ())),
        )
        for stock in stocks
    }
    return UniverseData(stocks=stocks, data=data)
