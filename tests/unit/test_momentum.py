from __future__ import annotations

from datetime import date, timedelta

import pytest

from stock_auditor.config import Settings, load_settings
from stock_auditor.domain import QuoteBar
from stock_auditor.scoring.momentum import score_momentum

AS_OF = date(2026, 10, 29)


def _settings() -> Settings:
    return load_settings()


def _bars(
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[QuoteBar]:
    start = AS_OF - timedelta(days=len(closes) - 1)
    bars = []
    for index, close in enumerate(closes):
        bars.append(
            QuoteBar(
                trade_date=start + timedelta(days=index),
                open=close,
                high=close,
                low=lows[index] if lows is not None else close * 0.97,
                close=close,
                volume=volumes[index] if volumes is not None else 1_000_000.0,
                amount=close * 1_000_000.0,
                turnover=0.05,
            )
        )
    return bars


def _pullback_closes() -> list[float]:
    decline = [11.0 - 0.1 * index for index in range(15)]
    rebound = [10.2, 10.3, 10.4, 10.5, 10.6]
    return [12.0] * 60 + decline + rebound


def _score(bars: list[QuoteBar]) -> object:
    return score_momentum(bars, _settings())


def test_insufficient_history_returns_zero() -> None:
    result = _score(_bars([10.0] * 30))
    assert result.available is False
    assert result.score == 0
    assert "数据不足" in result.tags


def test_overheated_stock_scores_zero() -> None:
    closes = [12.0] * 74 + [12.0, 12.0, 12.0, 12.0, 12.0, 14.0]
    result = _score(_bars(closes))
    assert result.score == 0
    assert result.base == 0
    assert "过热超买" in result.tags


def test_three_conditions_with_ma20_scores_twenty() -> None:
    closes = _pullback_closes()
    volumes = [1_000_000.0] * 75 + [400_000.0] * 5
    result = _score(_bars(closes, volumes=volumes))
    assert result.base == 20
    assert result.score == 20
    assert result.tags == []


def test_two_conditions_score_twelve() -> None:
    closes = _pullback_closes()
    result = _score(_bars(closes))
    assert result.base == 12
    assert result.score == 12


def test_one_condition_scores_eight() -> None:
    closes = _pullback_closes()
    lows = [close * 0.97 for close in closes]
    for index in range(70, 80):
        lows[index] = 10.4
    result = _score(_bars(closes, lows=lows))
    assert result.base == 8
    assert result.score == 8


def test_low_position_without_gain_scores_ten() -> None:
    closes = [12.0] * 79 + [11.9]
    result = _score(_bars(closes))
    assert result.base == 10
    assert result.score == 10


def test_no_conditions_after_large_twenty_day_gain_scores_five() -> None:
    last_twenty = [10.1 + 0.2 * index for index in range(11)]
    last_twenty += [12.2, 12.3, 12.0, 11.9, 11.8, 12.0, 12.1, 11.9, 11.6]
    result = _score(_bars([10.0] * 60 + last_twenty))
    assert result.raw["r20"] == pytest.approx(0.16)
    assert result.base == 5
    assert result.score == 5


def test_breakdown_penalty_is_applied_and_clamped() -> None:
    decline = [11.9 - 0.1 * index for index in range(20)]
    volumes = [1_000_000.0] * 80
    volumes[76] = 10_000_000.0
    result = _score(_bars([12.0] * 60 + decline, volumes=volumes))
    assert result.base == 8
    assert result.penalty == 10
    assert result.score == 0
    assert "破位" in result.tags
