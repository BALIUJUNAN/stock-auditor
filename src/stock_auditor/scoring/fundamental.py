"""基本面 40 分（任务书第 8 节）。

四个子项各 10 分：盈利能力、成长性、估值安全边际、财务健康度。
行业分位在同申万二级行业内计算，样本不足时回退到申万一级；个股历史分位
使用近 5 年估值序列。缺失指标以 0.5 分位补全，对应子项乘 ``imputed_discount``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from stock_auditor.config import PegRule, Settings
from stock_auditor.domain import (
    ConsensusRow,
    FinancialRow,
    StockData,
    ValuationRow,
)
from stock_auditor.scoring.common import (
    annual_rows,
    cagr,
    growth,
    mean,
    percentile_rank,
    pit_rows,
    round_half_up,
    safe_ratio,
    ttm_growth,
)

_PEER_METRICS = (
    "roe_avg",
    "roic_avg",
    "revenue_growth_ttm",
    "profit_growth_ttm",
    "consensus_cagr",
    "ocf_to_profit",
    "debt_ratio",
    "receivable_growth_gap",
)


@dataclass(frozen=True)
class FundamentalSnapshot:
    code: str
    sw_l1: str | None
    sw_l2: str | None
    roe_avg: float | None
    roic_avg: float | None
    revenue_growth_ttm: float | None
    profit_growth_ttm: float | None
    consensus_cagr: float | None
    revenue_cagr: float | None
    pe_ttm: float | None
    pb: float | None
    ps_ttm: float | None
    pe_history_pct: float | None
    pb_history_pct: float | None
    ps_history_pct: float | None
    ocf_to_profit: float | None
    debt_ratio: float | None
    receivable_growth_gap: float | None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FundamentalResult:
    code: str
    total: float
    profitability: float
    growth: float
    valuation: float
    health: float
    raw_values: dict[str, float | None] = field(default_factory=dict)
    percentiles: dict[str, float | None] = field(default_factory=dict)
    imputed: dict[str, bool] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


def _history_percentile(
    valuations: Sequence[ValuationRow],
    field: str,
    current: float | None,
    settings: Settings,
    as_of: date,
) -> float | None:
    cutoff = as_of - timedelta(days=365 * settings.fundamental.history_years)
    values = [
        value
        for row in valuations
        if cutoff <= row.trade_date <= as_of
        for value in [getattr(row, field)]
        if value is not None and value > 0
    ]
    if current is None or current <= 0:
        return None
    if len(values) < settings.fundamental.history_min_valid_days:
        return None
    return percentile_rank(current, values)


def _consensus_cagr(
    consensus: Sequence[ConsensusRow],
    annual: Sequence[FinancialRow],
    settings: Settings,
    as_of: date,
) -> float | None:
    if not consensus or not annual:
        return None
    fetch_dates = [row.fetch_date for row in consensus if row.fetch_date <= as_of]
    if not fetch_dates:
        return None
    latest_fetch = max(fetch_dates)
    forecasts = {
        row.fiscal_year: row.np_forecast
        for row in consensus
        if row.fetch_date == latest_fetch
        and row.np_forecast is not None
        and row.np_forecast > 0
        and (row.analyst_count or 0) >= settings.fundamental.min_analyst_count
    }
    if len(forecasts) < 2:
        return None
    base = annual[-1].net_profit_parent
    base_year = annual[-1].report_period.year
    end_year = max(forecasts)
    years = end_year - base_year
    if years <= 0:
        return None
    return cagr(forecasts[end_year], base, years)


def _revenue_cagr(annual: Sequence[FinancialRow], years: int) -> float | None:
    if not annual or years <= 0:
        return None
    latest = annual[-1]
    base_period = date(latest.report_period.year - years, 12, 31)
    base = next(
        (row.revenue for row in annual if row.report_period == base_period),
        None,
    )
    return cagr(latest.revenue, base, years)


def _last_annuals(annual: Sequence[FinancialRow], count: int) -> list[FinancialRow]:
    return list(annual[-count:])


def _ocf_to_profit(annual: Sequence[FinancialRow]) -> float | None:
    window = _last_annuals(annual, 3)
    if not window:
        return None
    ocf = [row.ocf for row in window]
    profit = [row.net_profit_parent for row in window]
    if any(value is None for value in ocf) or any(value is None for value in profit):
        return None
    profit_sum = sum(value for value in profit if value is not None)
    if profit_sum <= 0:
        return None
    return sum(value for value in ocf if value is not None) / profit_sum


def _debt_ratio(annual: Sequence[FinancialRow]) -> float | None:
    if not annual:
        return None
    latest = annual[-1]
    return safe_ratio(latest.total_liab, latest.total_assets)


def _receivable_growth_gap(annual: Sequence[FinancialRow]) -> float | None:
    if len(annual) < 2:
        return None
    latest, prior = annual[-1], annual[-2]
    revenue_growth = growth(latest.revenue, prior.revenue)
    receivable_growth = growth(latest.receivables, prior.receivables)
    if revenue_growth is None or receivable_growth is None:
        return None
    return receivable_growth - revenue_growth


def build_snapshot(
    data: StockData,
    settings: Settings,
    as_of: date,
) -> FundamentalSnapshot:
    rows = pit_rows(data.financials, as_of)
    annual = annual_rows(rows)
    periods = sorted(rows)
    latest_period = periods[-1] if periods else None

    revenue_growth_ttm = (
        ttm_growth(rows, latest_period, "revenue") if latest_period else None
    )
    profit_growth_ttm = (
        ttm_growth(rows, latest_period, "net_profit_parent") if latest_period else None
    )

    valuations = sorted(
        (row for row in data.valuations if row.trade_date <= as_of),
        key=lambda row: row.trade_date,
    )
    latest_valuation = valuations[-1] if valuations else None
    pe_ttm = latest_valuation.pe_ttm if latest_valuation else None
    pb = latest_valuation.pb if latest_valuation else None
    ps_ttm = latest_valuation.ps_ttm if latest_valuation else None

    tags: list[str] = []
    if pe_ttm is not None and pe_ttm <= 0:
        tags.append("亏损股，用市销率")
    if _consensus_cagr(data.consensus, annual, settings, as_of) is None:
        tags.append("无一致预期")

    return FundamentalSnapshot(
        code=data.stock.code,
        sw_l1=data.stock.sw_l1,
        sw_l2=data.stock.sw_l2,
        roe_avg=mean([row.roe for row in _last_annuals(annual, 3)]),
        roic_avg=mean([row.roic for row in _last_annuals(annual, 3)]),
        revenue_growth_ttm=revenue_growth_ttm,
        profit_growth_ttm=profit_growth_ttm,
        consensus_cagr=_consensus_cagr(data.consensus, annual, settings, as_of),
        revenue_cagr=_revenue_cagr(annual, settings.fundamental.revenue_cagr_years),
        pe_ttm=pe_ttm,
        pb=pb,
        ps_ttm=ps_ttm,
        pe_history_pct=_history_percentile(
            valuations, "pe_ttm", pe_ttm, settings, as_of
        ),
        pb_history_pct=_history_percentile(valuations, "pb", pb, settings, as_of),
        ps_history_pct=_history_percentile(
            valuations, "ps_ttm", ps_ttm, settings, as_of
        ),
        ocf_to_profit=_ocf_to_profit(annual),
        debt_ratio=_debt_ratio(annual),
        receivable_growth_gap=_receivable_growth_gap(annual),
        tags=tuple(tags),
    )


def _industry_keys(
    snapshots: Mapping[str, FundamentalSnapshot],
    min_sample: int,
) -> dict[str, tuple[str, str]]:
    l2_counts: dict[str, int] = {}
    for snapshot in snapshots.values():
        if snapshot.sw_l2:
            l2_counts[snapshot.sw_l2] = l2_counts.get(snapshot.sw_l2, 0) + 1
    keys: dict[str, tuple[str, str]] = {}
    for code, snapshot in snapshots.items():
        if snapshot.sw_l2 and l2_counts.get(snapshot.sw_l2, 0) >= min_sample:
            keys[code] = ("l2", snapshot.sw_l2)
        elif snapshot.sw_l1:
            keys[code] = ("l1", snapshot.sw_l1)
        else:
            keys[code] = ("all", "")
    return keys


def _industry_percentiles(
    snapshots: Mapping[str, FundamentalSnapshot],
    keys: Mapping[str, tuple[str, str]],
    metric: str,
) -> dict[str, float | None]:
    groups: dict[tuple[str, str], list[float]] = {}
    for code, snapshot in snapshots.items():
        value = getattr(snapshot, metric)
        if value is not None:
            groups.setdefault(keys[code], []).append(value)

    percentiles: dict[str, float | None] = {}
    for code, snapshot in snapshots.items():
        value = getattr(snapshot, metric)
        percentiles[code] = (
            percentile_rank(value, groups.get(keys[code], []))
            if value is not None
            else None
        )
    return percentiles


def _peg_score(
    snapshot: FundamentalSnapshot,
    settings: Settings,
    peg_rules: Sequence[PegRule],
) -> float:
    if (
        snapshot.pe_ttm is None
        or snapshot.pe_ttm <= 0
        or snapshot.consensus_cagr is None
        or snapshot.consensus_cagr <= 0
    ):
        return 0.0
    rule = next(
        (
            item
            for item in peg_rules
            if snapshot.sw_l2 is not None and snapshot.sw_l2 in item.match_sw_l2
        ),
        None,
    )
    cap = rule.peg_cap if rule is not None else settings.fundamental.default_peg_cap
    if rule is not None and (
        snapshot.revenue_cagr is None
        or snapshot.revenue_cagr < rule.revenue_cagr_min
    ):
        return 0.0
    peg = snapshot.pe_ttm / (snapshot.consensus_cagr * 100)
    half_cap = cap * 0.5
    if peg <= half_cap:
        return 3.0
    if peg >= cap:
        return 0.0
    return 3.0 * (cap - peg) / (cap - half_cap)


def _score_one(
    snapshot: FundamentalSnapshot,
    percentiles: Mapping[str, Mapping[str, float | None]],
    settings: Settings,
    peg_rules: Sequence[PegRule],
) -> FundamentalResult:
    discount = settings.fundamental.imputed_discount
    imputed: dict[str, bool] = {}
    pct: dict[str, float | None] = {}

    def percentile_of(metric: str) -> float:
        value = getattr(snapshot, metric)
        current = percentiles[metric].get(snapshot.code)
        pct[metric] = current
        if value is None or current is None:
            imputed[metric] = True
            return 0.5
        return current

    roe_pct = percentile_of("roe_avg")
    roic_pct = percentile_of("roic_avg")
    profitability = roe_pct * 6 + roic_pct * 4
    if imputed:
        profitability *= discount
        imputed["profitability_subitem"] = True

    growth_imputed_before = len(imputed)
    revenue_pct = percentile_of("revenue_growth_ttm")
    profit_pct = percentile_of("profit_growth_ttm")
    if snapshot.consensus_cagr is None:
        growth_score = revenue_pct * 5 + profit_pct * 5
        imputed["consensus_cagr"] = True
    else:
        consensus_pct = percentile_of("consensus_cagr")
        growth_score = revenue_pct * 3 + profit_pct * 3 + consensus_pct * 4
    if len(imputed) > growth_imputed_before:
        growth_score *= discount
        imputed["growth_subitem"] = True

    valuation_imputed = False
    if snapshot.pe_ttm is not None and snapshot.pe_ttm > 0:
        pe_pct = snapshot.pe_history_pct
        pct["pe_history"] = pe_pct
        if pe_pct is None:
            pe_pct = 0.5
            imputed["pe_history"] = True
            valuation_imputed = True
        pe_score = (1 - pe_pct) * 4
    else:
        ps_pct = snapshot.ps_history_pct
        pct["ps_history"] = ps_pct
        if snapshot.ps_ttm is None or snapshot.ps_ttm <= 0 or ps_pct is None:
            ps_pct = 0.5
            imputed["ps_history"] = True
            valuation_imputed = True
        pe_score = (1 - ps_pct) * 4

    pb_pct = snapshot.pb_history_pct
    pct["pb_history"] = pb_pct
    if snapshot.pb is None or snapshot.pb <= 0 or pb_pct is None:
        pb_pct = 0.5
        imputed["pb_history"] = True
        valuation_imputed = True
    pb_score = (1 - pb_pct) * 3

    peg_score = _peg_score(snapshot, settings, peg_rules)
    valuation = pe_score + pb_score + peg_score
    if valuation_imputed:
        valuation *= discount
        imputed["valuation_subitem"] = True

    health_imputed_before = len(imputed)
    ocf_pct = percentile_of("ocf_to_profit")
    debt_pct = percentile_of("debt_ratio")
    receivable_pct = percentile_of("receivable_growth_gap")
    health = ocf_pct * 4 + (1 - debt_pct) * 3 + (1 - receivable_pct) * 3
    if len(imputed) > health_imputed_before:
        health *= discount
        imputed["health_subitem"] = True

    profitability = round_half_up(profitability)
    growth_score = round_half_up(growth_score)
    valuation = round_half_up(valuation)
    health = round_half_up(health)
    total = round_half_up(profitability + growth_score + valuation + health)

    tags = list(snapshot.tags)
    rule = next(
        (
            item
            for item in peg_rules
            if snapshot.sw_l2 is not None and snapshot.sw_l2 in item.match_sw_l2
        ),
        None,
    )
    if (
        rule is not None
        and snapshot.pe_ttm is not None
        and snapshot.pe_ttm > 0
        and snapshot.consensus_cagr is not None
        and snapshot.consensus_cagr > 0
        and (
            snapshot.revenue_cagr is None
            or snapshot.revenue_cagr < rule.revenue_cagr_min
        )
    ):
        tags.append("PEG 赛道增速不达标")

    return FundamentalResult(
        code=snapshot.code,
        total=total,
        profitability=profitability,
        growth=growth_score,
        valuation=valuation,
        health=health,
        raw_values={
            "roe_avg": snapshot.roe_avg,
            "roic_avg": snapshot.roic_avg,
            "revenue_growth_ttm": snapshot.revenue_growth_ttm,
            "profit_growth_ttm": snapshot.profit_growth_ttm,
            "consensus_cagr": snapshot.consensus_cagr,
            "revenue_cagr": snapshot.revenue_cagr,
            "pe_ttm": snapshot.pe_ttm,
            "pb": snapshot.pb,
            "ps_ttm": snapshot.ps_ttm,
            "pe_history_pct": snapshot.pe_history_pct,
            "pb_history_pct": snapshot.pb_history_pct,
            "ps_history_pct": snapshot.ps_history_pct,
            "ocf_to_profit": snapshot.ocf_to_profit,
            "debt_ratio": snapshot.debt_ratio,
            "receivable_growth_gap": snapshot.receivable_growth_gap,
            "peg": (
                snapshot.pe_ttm / (snapshot.consensus_cagr * 100)
                if snapshot.pe_ttm is not None
                and snapshot.pe_ttm > 0
                and snapshot.consensus_cagr is not None
                and snapshot.consensus_cagr > 0
                else None
            ),
        },
        percentiles=pct,
        imputed=imputed,
        tags=tags,
    )


def score_fundamentals(
    data_list: Sequence[StockData],
    settings: Settings,
    peg_rules: Sequence[PegRule],
    as_of: date,
) -> dict[str, FundamentalResult]:
    """批量计算，保证行业分位在候选池内一致。"""
    snapshots = {
        data.stock.code: build_snapshot(data, settings, as_of) for data in data_list
    }
    if not snapshots:
        return {}
    keys = _industry_keys(snapshots, settings.fundamental.min_industry_sample)
    percentiles = {
        metric: _industry_percentiles(snapshots, keys, metric)
        for metric in _PEER_METRICS
    }
    return {
        code: _score_one(snapshot, percentiles, settings, peg_rules)
        for code, snapshot in snapshots.items()
    }
