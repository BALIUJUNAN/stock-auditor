"""评分与过滤共享的领域数据结构。

采集层负责把数据库记录转成这些不可变对象；过滤、评分、漏斗等模块只依赖
这里的数据结构，便于用离线 fixture 做单元测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str
    board: str | None
    list_date: date | None
    sw_l1: str | None
    sw_l2: str | None
    is_st: bool = False


@dataclass(frozen=True)
class QuoteBar:
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None
    turnover: float | None
    is_suspended: bool = False


@dataclass(frozen=True)
class FinancialRow:
    code: str
    report_period: date
    ann_date: date | None
    revenue: float | None = None
    net_profit_parent: float | None = None
    ocf: float | None = None
    total_assets: float | None = None
    total_liab: float | None = None
    cash: float | None = None
    interest_debt: float | None = None
    receivables: float | None = None
    roe: float | None = None
    roic: float | None = None


@dataclass(frozen=True)
class ValuationRow:
    trade_date: date
    pe_ttm: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None


@dataclass(frozen=True)
class ConsensusRow:
    fetch_date: date
    fiscal_year: int
    np_forecast: float | None = None
    revenue_forecast: float | None = None
    analyst_count: int | None = None


@dataclass(frozen=True)
class AnnouncementRow:
    ann_date: date | None
    title: str
    category: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class PledgeRow:
    date: date
    controlling_pledge_ratio: float | None = None


@dataclass(frozen=True)
class ResearchRow:
    visit_date: date
    org: str


@dataclass(frozen=True)
class StockData:
    stock: StockInfo
    quotes: tuple[QuoteBar, ...] = ()
    financials: tuple[FinancialRow, ...] = ()
    valuations: tuple[ValuationRow, ...] = ()
    consensus: tuple[ConsensusRow, ...] = ()
    announcements: tuple[AnnouncementRow, ...] = ()
    pledge: tuple[PledgeRow, ...] = ()
    research: tuple[ResearchRow, ...] = ()


@dataclass(frozen=True)
class FilterResult:
    code: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
