from __future__ import annotations

from stock_auditor.config import Settings, load_settings
from stock_auditor.filters.veto import VetoEvent
from stock_auditor.scoring.composite import compose_score

FUNDAMENTAL = 40.0
MOMENTUM = 20.0


def _settings() -> Settings:
    return load_settings()


def _soft(penalty: float, rule: str = "cfo_or_auditor_change") -> VetoEvent:
    return VetoEvent(rule=rule, level="soft", detail="test", penalty=penalty)


def test_raw_total_and_four_stars() -> None:
    result = compose_score(FUNDAMENTAL, MOMENTUM, 20.0, _settings())
    assert result.quant_total == 60.0
    assert result.raw_total == 80.0
    assert result.final_total == 80.0
    assert result.stars == 4
    assert result.is_yellow is False
    assert result.is_veto is False


def test_five_stars_at_threshold() -> None:
    result = compose_score(FUNDAMENTAL, MOMENTUM, 25.0, _settings())
    assert result.final_total == 85.0
    assert result.stars == 5


def test_below_four_stars_is_not_pushed() -> None:
    result = compose_score(30.0, 15.0, 20.0, _settings())
    assert result.final_total == 65.0
    assert result.stars == 0


def test_soft_downgrade_caps_at_sixty_nine() -> None:
    result = compose_score(
        FUNDAMENTAL, MOMENTUM, 25.0, _settings(), soft_events=[_soft(10.0)]
    )
    assert result.raw_total == 85.0
    assert result.final_total == 69.0
    assert result.is_yellow is True
    assert result.stars == 0


def test_multiple_soft_penalties_accumulate() -> None:
    events = [_soft(10.0), _soft(10.0, "negative_ocf")]
    result = compose_score(
        FUNDAMENTAL, MOMENTUM, 25.0, _settings(), soft_events=events
    )
    assert result.final_total == 65.0
    assert result.is_yellow is True


def test_soft_penalty_below_cap_is_not_clamped_up() -> None:
    result = compose_score(
        30.0, 15.0, 15.0, _settings(), soft_events=[_soft(10.0)]
    )
    assert result.raw_total == 60.0
    assert result.final_total == 50.0


def test_hard_veto_forces_zero() -> None:
    result = compose_score(
        FUNDAMENTAL,
        MOMENTUM,
        30.0,
        _settings(),
        hard_veto=True,
        soft_events=[_soft(10.0)],
    )
    assert result.raw_total == 60.0
    assert result.final_total == 0.0
    assert result.stars == 0
    assert result.is_veto is True
    assert result.is_yellow is True


def test_without_outlook_only_quant_score_and_no_stars() -> None:
    result = compose_score(FUNDAMENTAL, MOMENTUM, None, _settings())
    assert result.quant_total == 60.0
    assert result.raw_total is None
    assert result.final_total is None
    assert result.stars is None


def test_score_rounding_uses_half_up() -> None:
    result = compose_score(20.15, 10.15, 20.0, _settings())
    assert result.quant_total == 30.3
    assert result.raw_total == 50.3
