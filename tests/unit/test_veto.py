from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from stock_auditor.config import Settings, load_settings
from stock_auditor.db import apply_migrations
from stock_auditor.domain import (
    AnnouncementRow,
    FilterResult,
    FinancialRow,
    PledgeRow,
    StockData,
    StockInfo,
)
from stock_auditor.filters.service import store_filter_results, store_veto_events
from stock_auditor.filters.veto import (
    VetoEvent,
    check_hard_veto,
    check_soft_downgrade,
)

AS_OF = date(2026, 10, 29)
STOCK = StockInfo(
    code="002773",
    name="康弘药业",
    board="sz_main",
    list_date=date(2015, 6, 26),
    sw_l1="医药生物",
    sw_l2="生物制品",
)


def _settings() -> Settings:
    return load_settings()


def _data(**overrides: object) -> StockData:
    values: dict[str, object] = {"stock": STOCK}
    values.update(overrides)
    return StockData(**values)  # type: ignore[arg-type]


def _ann(title: str, day: date | None) -> AnnouncementRow:
    return AnnouncementRow(ann_date=day, title=title)


def _annual(
    period: date,
    *,
    revenue: float = 100.0,
    revenue_growth: float = 0.1,
    net_profit: float = 10.0,
    ocf: float = 10.0,
    total_assets: float = 100.0,
    total_liab: float = 40.0,
    cash: float = 10.0,
    interest_debt: float = 10.0,
    receivables: float = 10.0,
    prior_receivables: float | None = None,
    prior_revenue: float | None = None,
) -> tuple[FinancialRow, FinancialRow]:
    prior = FinancialRow(
        code=STOCK.code,
        report_period=date(period.year - 1, 12, 31),
        ann_date=date(period.year, 4, 20),
        revenue=prior_revenue if prior_revenue is not None else revenue / (1 + revenue_growth),
        net_profit_parent=net_profit,
        ocf=ocf,
        total_assets=total_assets,
        total_liab=total_liab,
        cash=cash,
        interest_debt=interest_debt,
        receivables=(
            prior_receivables if prior_receivables is not None else receivables
        ),
    )
    current = FinancialRow(
        code=STOCK.code,
        report_period=period,
        ann_date=date(period.year + 1, 4, 20),
        revenue=revenue,
        net_profit_parent=net_profit,
        ocf=ocf,
        total_assets=total_assets,
        total_liab=total_liab,
        cash=cash,
        interest_debt=interest_debt,
        receivables=receivables,
    )
    return prior, current


def test_no_events_for_clean_stock() -> None:
    assert check_hard_veto(_data(), _settings(), AS_OF) == []
    assert check_soft_downgrade(_data(), _settings(), AS_OF) == []


def test_open_investigation_is_hard_veto() -> None:
    data = _data(announcements=(_ann("关于收到立案告知书的公告", date(2026, 1, 5)),))
    events = check_hard_veto(data, _settings(), AS_OF)
    assert [event.rule for event in events] == ["investigation"]


def test_investigation_closed_is_not_veto() -> None:
    data = _data(
        announcements=(
            _ann("关于收到立案告知书的公告", date(2026, 1, 5)),
            _ann("关于调查结案的公告", date(2026, 3, 1)),
        )
    )
    assert check_hard_veto(data, _settings(), AS_OF) == []


def test_reopened_investigation_is_veto() -> None:
    data = _data(
        announcements=(
            _ann("立案调查公告", date(2026, 1, 5)),
            _ann("终止调查公告", date(2026, 2, 1)),
            _ann("再次立案调查公告", date(2026, 5, 1)),
        )
    )
    events = check_hard_veto(data, _settings(), AS_OF)
    assert [event.rule for event in events] == ["investigation"]


def test_regulatory_penalty_within_lookback() -> None:
    data = _data(
        announcements=(_ann("关于收到行政处罚决定书的公告", date(2026, 6, 1)),)
    )
    events = check_hard_veto(data, _settings(), AS_OF)
    assert [event.rule for event in events] == ["regulatory_penalty"]


def test_regulatory_penalty_outside_lookback() -> None:
    data = _data(
        announcements=(_ann("关于收到行政处罚决定书的公告", date(2024, 1, 1)),)
    )
    assert check_hard_veto(data, _settings(), AS_OF) == []


def test_pledge_ratio_above_threshold() -> None:
    data = _data(pledge=(PledgeRow(date=date(2026, 9, 30), controlling_pledge_ratio=0.75),))
    events = check_hard_veto(data, _settings(), AS_OF)
    assert [event.rule for event in events] == ["pledge_ratio"]


def test_pledge_ratio_at_threshold_passes() -> None:
    data = _data(pledge=(PledgeRow(date=date(2026, 9, 30), controlling_pledge_ratio=0.70),))
    assert check_hard_veto(data, _settings(), AS_OF) == []


def test_pledge_after_as_of_is_ignored() -> None:
    data = _data(
        pledge=(PledgeRow(date=date(2026, 12, 31), controlling_pledge_ratio=0.90),)
    )
    assert check_hard_veto(data, _settings(), AS_OF) == []


def test_cash_and_debt_both_high() -> None:
    _, current = _annual(
        date(2025, 12, 31), total_assets=100.0, cash=25.0, interest_debt=25.0
    )
    events = check_hard_veto(_data(financials=(current,)), _settings(), AS_OF)
    assert [event.rule for event in events] == ["cash_debt_both_high"]


def test_only_one_of_cash_debt_high_passes() -> None:
    _, current = _annual(
        date(2025, 12, 31), total_assets=100.0, cash=25.0, interest_debt=10.0
    )
    assert check_hard_veto(_data(financials=(current,)), _settings(), AS_OF) == []


def test_receivable_inflation() -> None:
    prior, current = _annual(
        date(2025, 12, 31),
        revenue=120.0,
        prior_revenue=100.0,
        receivables=80.0,
        prior_receivables=50.0,
    )
    events = check_hard_veto(
        _data(financials=(prior, current)), _settings(), AS_OF
    )
    assert [event.rule for event in events] == ["receivable_inflation"]


def test_receivable_gap_without_high_ratio_passes() -> None:
    prior, current = _annual(
        date(2025, 12, 31),
        revenue=120.0,
        prior_revenue=100.0,
        receivables=20.0,
        prior_receivables=10.0,
    )
    assert check_hard_veto(_data(financials=(prior, current)), _settings(), AS_OF) == []


def test_pit_ignores_unannounced_report() -> None:
    prior, current = _annual(
        date(2025, 12, 31), total_assets=100.0, cash=10.0, interest_debt=10.0
    )
    unannounced = FinancialRow(
        code=STOCK.code,
        report_period=date(2026, 9, 30),
        ann_date=date(2026, 12, 1),
        total_assets=100.0,
        cash=90.0,
        interest_debt=90.0,
    )
    events = check_hard_veto(
        _data(financials=(prior, current, unannounced)), _settings(), AS_OF
    )
    assert events == []


def test_cfo_change_is_soft_downgrade() -> None:
    data = _data(
        announcements=(_ann("关于财务总监辞职的公告", date(2026, 9, 1)),)
    )
    events = check_soft_downgrade(data, _settings(), AS_OF)
    assert [event.rule for event in events] == ["cfo_or_auditor_change"]
    assert events[0].penalty == _settings().soft_downgrade.penalty_cfo_or_auditor_change


def test_cfo_change_outside_lookback_passes() -> None:
    data = _data(
        announcements=(_ann("关于财务总监辞职的公告", date(2026, 1, 1)),)
    )
    assert check_soft_downgrade(data, _settings(), AS_OF) == []


def test_negative_ocf_with_high_growth_is_soft_downgrade() -> None:
    prior, current = _annual(
        date(2025, 12, 31), revenue=130.0, prior_revenue=100.0, ocf=-10.0
    )
    events = check_soft_downgrade(
        _data(financials=(prior, current)), _settings(), AS_OF
    )
    assert [event.rule for event in events] == ["negative_ocf"]


def test_negative_ocf_with_low_growth_passes() -> None:
    prior, current = _annual(
        date(2025, 12, 31), revenue=110.0, prior_revenue=100.0, ocf=-10.0
    )
    assert check_soft_downgrade(
        _data(financials=(prior, current)), _settings(), AS_OF
    ) == []


def test_one_positive_ocf_year_passes() -> None:
    prior, current = _annual(
        date(2025, 12, 31), revenue=130.0, prior_revenue=100.0, ocf=5.0
    )
    assert check_soft_downgrade(
        _data(financials=(prior, current)), _settings(), AS_OF
    ) == []


def test_llm_critical_risk_adds_soft_penalty() -> None:
    events = check_soft_downgrade(_data(), _settings(), AS_OF, llm_critical_risk=True)
    assert [event.rule for event in events] == ["llm_critical_risk"]
    assert events[0].penalty == _settings().soft_downgrade.penalty_llm_critical_risk


def test_results_are_written_to_database(tmp_path: Path) -> None:
    with duckdb.connect(str(tmp_path / "test.duckdb")) as connection:
        apply_migrations(connection)
        store_filter_results(
            connection,
            "weekly-20261029-200000",
            [FilterResult(code="002773", passed=False, reasons=["板块不在范围：bse"])],
        )
        store_veto_events(
            connection,
            "weekly-20261029-200000",
            {
                "002773": [
                    VetoEvent(
                        rule="pledge_ratio",
                        level="hard",
                        detail="质押比例过高",
                    )
                ]
            },
        )

        passed, reasons = connection.execute(
            "SELECT passed, reasons FROM filter_log"
        ).fetchone()
        assert passed is False
        assert json.loads(reasons) == ["板块不在范围：bse"]

        rule, level, detail, penalty = connection.execute(
            "SELECT rule, level, detail, penalty FROM veto_events"
        ).fetchone()
        assert (rule, level, detail, penalty) == (
            "pledge_ratio",
            "hard",
            "质押比例过高",
            0.0,
        )
