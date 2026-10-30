from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_auditor.config import PegRule, Settings, load_industry_peg, load_settings
from stock_auditor.domain import (
    ConsensusRow,
    FinancialRow,
    StockData,
    StockInfo,
    ValuationRow,
)
from stock_auditor.scoring.fundamental import (
    FundamentalResult,
    build_snapshot,
    score_fundamentals,
)

AS_OF = date(2026, 10, 29)


def _settings() -> Settings:
    base = load_settings()
    return base.model_copy(
        update={"fundamental": base.fundamental.model_copy(update={"use_consensus": True})}
    )


def _peg_rules() -> list[PegRule]:
    return load_industry_peg()


def _row(
    code: str,
    period: date,
    *,
    revenue: float | None = 100.0,
    net_profit: float | None = 10.0,
    ocf: float | None = 12.0,
    total_assets: float | None = 500.0,
    total_liab: float | None = 200.0,
    cash: float | None = 50.0,
    interest_debt: float | None = 50.0,
    receivables: float | None = 60.0,
    roe: float | None = 0.12,
    roic: float | None = 0.09,
    ann_date: date | None = None,
) -> FinancialRow:
    return FinancialRow(
        code=code,
        report_period=period,
        ann_date=ann_date or date(period.year + 1, 4, 20),
        revenue=revenue,
        net_profit_parent=net_profit,
        ocf=ocf,
        total_assets=total_assets,
        total_liab=total_liab,
        cash=cash,
        interest_debt=interest_debt,
        receivables=receivables,
        roe=roe,
        roic=roic,
    )


def _annuals(code: str, *, roe: float | None = 0.12) -> list[FinancialRow]:
    values = [
        (2022, 200.0, 40.0, 50.0, 50.0),
        (2023, 250.0, 60.0, 80.0, 60.0),
        (2024, 320.0, 70.0, 90.0, 55.0),
        (2025, 400.0, 80.0, 100.0, 60.0),
    ]
    return [
        _row(
            code,
            date(year, 12, 31),
            revenue=revenue,
            net_profit=profit,
            ocf=ocf,
            receivables=receivables,
            roe=roe,
            roic=roe * 0.75 if roe is not None else 0.09,
        )
        for year, revenue, profit, ocf, receivables in values
    ]


def _quarterlies(code: str) -> list[FinancialRow]:
    result: list[FinancialRow] = []
    for year, quarter_values in {
        2024: (80.0, 160.0, 240.0),
        2025: (100.0, 200.0, 300.0),
        2026: (110.0, 220.0, 330.0),
    }.items():
        for index, revenue in enumerate(quarter_values, start=1):
            month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30)}[index]
            result.append(
                _row(
                    code,
                    date(year, *month_day),
                    revenue=revenue,
                    net_profit=revenue * 0.15,
                    ocf=revenue * 0.1,
                    roe=None,
                    roic=None,
                    ann_date=date(year, {1: 4, 2: 8, 3: 10}[index], 25),
                )
            )
    return result


def _valuations(
    *,
    pe: float = 20.0,
    pb: float = 2.0,
    ps: float = 5.0,
) -> tuple[ValuationRow, ...]:
    rows = []
    for index in range(699):
        below = index < 349
        rows.append(
            ValuationRow(
                trade_date=AS_OF - timedelta(days=699 - index),
                pe_ttm=10.0 + index * 0.01 if below else 21.0 + (index - 349) * 0.01,
                pb=1.0 + index * 0.001 if below else 2.1 + (index - 349) * 0.001,
                ps_ttm=2.0 + index * 0.001 if below else 5.1 + (index - 349) * 0.001,
            )
        )
    rows.append(ValuationRow(trade_date=AS_OF, pe_ttm=pe, pb=pb, ps_ttm=ps))
    return tuple(rows)


def _consensus() -> tuple[ConsensusRow, ...]:
    return (
        ConsensusRow(
            fetch_date=AS_OF,
            fiscal_year=2026,
            np_forecast=100.0,
            analyst_count=5,
        ),
        ConsensusRow(
            fetch_date=AS_OF,
            fiscal_year=2027,
            np_forecast=125.0,
            analyst_count=5,
        ),
    )


def _data(
    code: str = "002773",
    *,
    sw_l1: str = "医药生物",
    sw_l2: str = "生物制品",
    roe: float | None = 0.12,
    valuations: tuple[ValuationRow, ...] | None = None,
    consensus: tuple[ConsensusRow, ...] | None = None,
    financials: list[FinancialRow] | None = None,
) -> StockData:
    return StockData(
        stock=StockInfo(
            code=code,
            name=code,
            board="sz_main",
            list_date=date(2015, 6, 26),
            sw_l1=sw_l1,
            sw_l2=sw_l2,
        ),
        financials=tuple(
            financials
            if financials is not None
            else [*_annuals(code, roe=roe), *_quarterlies(code)]
        ),
        valuations=_valuations() if valuations is None else valuations,
        consensus=_consensus() if consensus is None else consensus,
    )


def _score(data: StockData, settings: Settings | None = None) -> FundamentalResult:
    resolved = settings or _settings()
    results = score_fundamentals([data], resolved, _peg_rules(), AS_OF)
    return results[data.stock.code]


def test_ttm_growth_uses_cumulative_quarters() -> None:
    snapshot = build_snapshot(_data(), _settings(), AS_OF)
    assert snapshot.revenue_growth_ttm == pytest.approx(430.0 / 380.0 - 1)
    assert snapshot.profit_growth_ttm == pytest.approx(84.5 / 79.0 - 1)


def test_healthy_company_scores_expected_subitems() -> None:
    result = _score(_data())
    assert result.profitability == pytest.approx(5.0, abs=0.1)
    assert result.growth == pytest.approx(5.0, abs=0.1)
    assert result.health == pytest.approx(5.0, abs=0.1)
    assert result.valuation == pytest.approx(6.5, abs=0.1)
    assert result.total == pytest.approx(21.5, abs=0.2)
    assert result.raw_values["peg"] == pytest.approx(0.8)
    assert result.imputed == {}


def test_loss_making_stock_uses_ps_and_tag() -> None:
    data = _data(valuations=_valuations(pe=-5.0, pb=2.0, ps=5.0))
    result = _score(data)
    assert "亏损股，用市销率" in result.tags
    assert result.raw_values["pe_ttm"] == -5.0
    assert result.valuation == pytest.approx(3.5, abs=0.1)


def test_missing_consensus_discounts_growth() -> None:
    result = _score(_data(consensus=()))
    assert "无一致预期" in result.tags
    assert result.imputed["growth_subitem"] is True
    assert result.growth == pytest.approx(4.3, abs=0.1)
    assert result.valuation == pytest.approx(3.5, abs=0.1)
    assert result.total == pytest.approx(17.8, abs=0.2)


def test_missing_data_is_imputed_and_discounted() -> None:
    data = StockData(stock=_data().stock)
    result = _score(data)
    assert result.total == pytest.approx(15.9, abs=0.2)
    assert result.imputed["profitability_subitem"] is True
    assert result.imputed["growth_subitem"] is True
    assert result.imputed["valuation_subitem"] is True
    assert result.imputed["health_subitem"] is True


def test_single_missing_metric_discounts_only_that_subitem() -> None:
    result = _score(_data(roe=None))
    assert result.imputed["roe_avg"] is True
    assert result.imputed["profitability_subitem"] is True
    assert result.profitability == pytest.approx(4.3, abs=0.1)
    assert "growth_subitem" not in result.imputed


def test_industry_sample_falls_back_to_l1() -> None:
    stocks = [
        _data(f"00000{index}", sw_l2="半导体", roe=0.05 + index * 0.01, valuations=(), consensus=())
        for index in range(9)
    ]
    stocks += [
        _data(f"00001{index}", sw_l2="元件", roe=0.01 + index * 0.01, valuations=(), consensus=())
        for index in range(3)
    ]
    results = score_fundamentals(stocks, _settings(), _peg_rules(), AS_OF)
    best = results["000008"]
    worst = results["000010"]
    assert best.percentiles["roe_avg"] == pytest.approx(1.0)
    assert worst.percentiles["roe_avg"] == pytest.approx(0.0)


def test_peg_floor_blocks_high_valuation_growth_stock() -> None:
    data = _data(sw_l1="电子", sw_l2="半导体")
    annuals = [
        _row(
            data.stock.code,
            date(year, 12, 31),
            revenue=revenue,
            net_profit=profit,
            receivables=60.0,
        )
        for year, revenue, profit in [
            (2022, 300.0, 40.0),
            (2023, 330.0, 50.0),
            (2024, 360.0, 60.0),
            (2025, 400.0, 80.0),
        ]
    ]
    data = StockData(
        stock=data.stock,
        financials=tuple([*annuals, *_quarterlies(data.stock.code)]),
        valuations=_valuations(pe=20.0),
        consensus=_consensus(),
    )
    result = _score(data)
    assert result.raw_values["revenue_cagr"] == pytest.approx(0.10, abs=0.01)
    assert "PEG 赛道增速不达标" in result.tags
    assert result.valuation == pytest.approx(3.5, abs=0.1)


def test_consensus_uses_only_fy0_plus_two():
    rows = (
        ConsensusRow(fetch_date=AS_OF, fiscal_year=2027, np_forecast=125, analyst_count=5),
        ConsensusRow(fetch_date=AS_OF, fiscal_year=2029, np_forecast=500, analyst_count=5),
    )
    result = build_snapshot(_data(consensus=rows), _settings(), AS_OF)
    assert result.consensus_cagr == pytest.approx((125 / 80) ** 0.5 - 1)
    result = build_snapshot(_data(consensus=rows[1:]), _settings(), AS_OF)
    assert result.consensus_cagr is None


def test_peer_pool_is_independent_of_candidates():
    candidates = [_data("000001", roe=0.10, valuations=(), consensus=())]
    peers = candidates + [_data("000002", roe=0.20, valuations=(), consensus=())]
    result = score_fundamentals(candidates, _settings(), _peg_rules(), AS_OF, peer_data=peers)
    assert result["000001"].percentiles["roe_avg"] == 0.0


@pytest.mark.parametrize(("ocf", "expected"), [(1.0, 2.0), (-1.0, 0.0)])
def test_negative_profit_uses_fixed_cashflow_score(ocf, expected):
    financials = [
        _row("002773", date(y, 12, 31), net_profit=-1, ocf=ocf) for y in (2023, 2024, 2025)
    ]
    snapshot = build_snapshot(_data(financials=financials), _settings(), AS_OF)
    assert snapshot.ocf_fixed_score == expected
    assert "经营现金流比率不适用" in snapshot.tags


def test_industry_fallback_counts_valid_values_per_metric():
    target = _data("000001", sw_l2="A", roe=0.1, valuations=(), consensus=())
    missing = [
        _data(f"0000{i:02}", sw_l2="A", roe=None, valuations=(), consensus=()) for i in range(2, 11)
    ]
    others = [
        _data(f"0000{i:02}", sw_l2="B", roe=0.2, valuations=(), consensus=()) for i in range(11, 21)
    ]
    result = score_fundamentals(
        [target], _settings(), _peg_rules(), AS_OF, peer_data=[target, *missing, *others]
    )
    assert result[target.stock.code].percentiles["roe_avg"] == 0.0


def test_default_history_only_ignores_existing_forecast():
    settings = load_settings()
    assert settings.fundamental.use_consensus is False
    result = _score(_data(consensus=_consensus()), settings)
    assert result.raw_values["consensus_cagr"] is None
    assert result.imputed["peg_unavailable"] is True
    assert "PEG 暂未评分（按 0 分计入）" in result.tags
    assert result.growth == pytest.approx(4.3, abs=0.1)
    assert result.valuation == pytest.approx(3.5, abs=0.1)
