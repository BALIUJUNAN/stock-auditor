from __future__ import annotations

from datetime import date, timedelta

from stock_auditor.config import Settings, load_settings
from stock_auditor.domain import QuoteBar, StockInfo
from stock_auditor.filters.stage0 import evaluate_stage0

AS_OF = date(2026, 10, 29)
WINDOW = 20


def _stock(**overrides: object) -> StockInfo:
    values: dict[str, object] = {
        "code": "002773",
        "name": "康弘药业",
        "board": "sz_main",
        "list_date": date(2015, 6, 26),
        "sw_l1": "医药生物",
        "sw_l2": "生物制品",
        "is_st": False,
    }
    values.update(overrides)
    return StockInfo(**values)  # type: ignore[arg-type]


def _bar(index: int, **overrides: object) -> QuoteBar:
    values: dict[str, object] = {
        "trade_date": AS_OF - timedelta(days=WINDOW - index),
        "open": 10.0,
        "high": 10.5,
        "low": 9.5,
        "close": 10.0,
        "volume": 1_000_000.0,
        "amount": 100_000_000.0,
        "turnover": 0.05,
        "is_suspended": False,
    }
    values.update(overrides)
    return QuoteBar(**values)  # type: ignore[arg-type]


def _quotes(count: int = WINDOW, **overrides: object) -> list[QuoteBar]:
    return [_bar(index, **overrides) for index in range(count)]


def _settings() -> Settings:
    return load_settings()


def test_healthy_stock_passes() -> None:
    result = evaluate_stage0(_stock(), _quotes(), _settings(), AS_OF)
    assert result.passed
    assert result.reasons == []


def test_board_not_allowed() -> None:
    result = evaluate_stage0(_stock(board="bse"), _quotes(), _settings(), AS_OF)
    assert not result.passed
    assert any("板块" in reason for reason in result.reasons)


def test_st_name_is_excluded() -> None:
    result = evaluate_stage0(_stock(name="*ST康弘"), _quotes(), _settings(), AS_OF)
    assert not result.passed
    assert any("排除词" in reason for reason in result.reasons)


def test_new_listing_is_excluded() -> None:
    result = evaluate_stage0(
        _stock(list_date=AS_OF - timedelta(days=100)), _quotes(), _settings(), AS_OF
    )
    assert not result.passed
    assert any("上市不足" in reason for reason in result.reasons)


def test_missing_list_date_is_excluded() -> None:
    result = evaluate_stage0(_stock(list_date=None), _quotes(), _settings(), AS_OF)
    assert not result.passed
    assert any("上市日期" in reason for reason in result.reasons)


def test_excluded_industry() -> None:
    result = evaluate_stage0(
        _stock(sw_l1="银行"), _quotes(), _settings(), AS_OF
    )
    assert not result.passed
    assert any("行业排除" in reason for reason in result.reasons)


def test_insufficient_quotes() -> None:
    result = evaluate_stage0(_stock(), _quotes(count=10), _settings(), AS_OF)
    assert not result.passed
    assert any("数据不足" in reason for reason in result.reasons)


def test_too_many_suspended_days() -> None:
    quotes = _quotes()
    for index in range(6):
        quotes[index] = _bar(index, is_suspended=True, volume=0.0)
    result = evaluate_stage0(_stock(), quotes, _settings(), AS_OF)
    assert not result.passed
    assert any("停牌" in reason for reason in result.reasons)


def test_turnover_out_of_range() -> None:
    low = evaluate_stage0(_stock(), _quotes(turnover=0.01), _settings(), AS_OF)
    high = evaluate_stage0(_stock(), _quotes(turnover=0.25), _settings(), AS_OF)
    assert not low.passed and any("换手率" in reason for reason in low.reasons)
    assert not high.passed and any("换手率" in reason for reason in high.reasons)


def test_missing_turnover() -> None:
    result = evaluate_stage0(_stock(), _quotes(turnover=None), _settings(), AS_OF)
    assert not result.passed
    assert any("换手率数据缺失" in reason for reason in result.reasons)


def test_low_amount() -> None:
    result = evaluate_stage0(
        _stock(), _quotes(amount=10_000_000.0), _settings(), AS_OF
    )
    assert not result.passed
    assert any("成交额" in reason for reason in result.reasons)


def test_all_reasons_are_collected() -> None:
    result = evaluate_stage0(
        _stock(name="ST测试", board="bse", sw_l1="房地产"),
        _quotes(turnover=0.01, amount=1.0),
        _settings(),
        AS_OF,
    )
    assert not result.passed
    assert len(result.reasons) >= 4
    joined = " ".join(result.reasons)
    assert "板块" in joined
    assert "排除词" in joined
    assert "行业排除" in joined
    assert "换手率" in joined
    assert "成交额" in joined
