"""动量 20 分（任务书第 9 节）：防追高、看回调企稳、扣破位。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from stock_auditor.config import Settings
from stock_auditor.domain import QuoteBar
from stock_auditor.scoring.common import clamp, mean


@dataclass(frozen=True)
class MomentumResult:
    score: float
    base: float
    penalty: float
    tags: list[str] = field(default_factory=list)
    raw: dict[str, float | None] = field(default_factory=dict)
    available: bool = True


def _rolling_mean(values: Sequence[float | None], window: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
            continue
        window_values = values[index + 1 - window : index + 1]
        result.append(mean(window_values))
    return result


def _prepare(quotes: Sequence[QuoteBar]) -> list[QuoteBar]:
    ordered = sorted(quotes, key=lambda bar: bar.trade_date)
    return [bar for bar in ordered if bar.close is not None]


def score_momentum(quotes: Sequence[QuoteBar], settings: Settings) -> MomentumResult:
    rules = settings.momentum
    bars = _prepare(quotes)
    required = max(rules.ma_long, rules.high_window, rules.ma_mid) + 1
    if len(bars) < required:
        return MomentumResult(
            score=0.0,
            base=0.0,
            penalty=0.0,
            tags=["数据不足"],
            raw={},
            available=False,
        )

    closes = [float(bar.close) for bar in bars if bar.close is not None]
    highs = [
        float(bar.high) if bar.high is not None else float(bar.close)
        for bar in bars
    ]
    lows = [
        float(bar.low) if bar.low is not None else float(bar.close)
        for bar in bars
    ]
    volumes = [bar.volume for bar in bars]

    ma_short = _rolling_mean(closes, rules.ma_short)
    ma_mid = _rolling_mean(closes, rules.ma_mid)
    ma_long = _rolling_mean(closes, rules.ma_long)
    volume_mid = _rolling_mean(volumes, rules.ma_mid)

    latest_close = closes[-1]
    r5 = latest_close / closes[-6] - 1
    r20 = latest_close / closes[-21] - 1
    dev20 = latest_close / ma_mid[-1] - 1 if ma_mid[-1] else None
    recent_high = max(highs[-rules.high_window :])
    drawdown = 1 - latest_close / recent_high if recent_high > 0 else None
    volume_ratio = (
        mean(volumes[-rules.ma_short :]) / mean(volumes[-rules.ma_mid :])
        if mean(volumes[-rules.ma_mid :])
        else None
    )

    raw = {
        "r5": r5,
        "r20": r20,
        "dev20": dev20,
        "drawdown": drawdown,
        "volume_ratio": volume_ratio,
        "close": latest_close,
        "ma20": ma_mid[-1],
        "ma60": ma_long[-1],
    }

    if r5 > rules.overheat_r5 or (dev20 is not None and dev20 > rules.overheat_dev_ma20):
        return MomentumResult(
            score=0.0,
            base=0.0,
            penalty=0.0,
            tags=["过热超买"],
            raw=raw,
        )

    condition_drawdown = (
        drawdown is not None
        and rules.pullback_drawdown_min <= drawdown <= rules.pullback_drawdown_max
    )
    condition_shrink = (
        volume_ratio is not None and volume_ratio < rules.shrink_volume_ratio
    )
    recent_low = min(lows[-rules.low_window :])
    ma_short_three_days_ago = ma_short[-4] if len(ma_short) >= 4 else None
    condition_stabilize = (
        latest_close >= recent_low * (1 + rules.stabilize_rebound)
        and ma_short_three_days_ago is not None
        and ma_short[-1] is not None
        and ma_short[-1] >= ma_short_three_days_ago
    )

    conditions = sum(
        [condition_drawdown, condition_shrink, condition_stabilize]
    )
    if conditions == 3:
        base = 17.0
        if ma_mid[-1] is not None and latest_close >= ma_mid[-1]:
            base = 20.0
    elif conditions == 2:
        base = 12.0
    elif conditions == 1:
        base = 8.0
    elif (
        drawdown is not None
        and drawdown < rules.pullback_drawdown_min
        and r20 < rules.low_position_r20_max
    ):
        base = 10.0
    else:
        base = 5.0

    penalty = 0.0
    breakdown = _has_breakdown(
        closes,
        volumes,
        ma_long,
        volume_mid,
        rules.breakdown_lookback_days,
        rules.breakdown_volume_ratio,
        rules.breakdown_confirm_days,
    )
    tags: list[str] = []
    if breakdown:
        penalty = float(rules.breakdown_penalty)
        tags.append("破位")

    score = clamp(base - penalty, 0.0, 20.0)
    return MomentumResult(
        score=score,
        base=base,
        penalty=penalty,
        tags=tags,
        raw=raw,
    )


def _has_breakdown(
    closes: Sequence[float],
    volumes: Sequence[float | None],
    ma_long: Sequence[float | None],
    volume_mid: Sequence[float | None],
    lookback_days: int,
    volume_ratio: float,
    confirm_days: int,
) -> bool:
    total = len(closes)
    for day in range(max(0, total - lookback_days), total):
        if day + confirm_days >= total:
            continue
        ma_value = ma_long[day]
        volume_average = volume_mid[day]
        volume = volumes[day]
        if ma_value is None or volume_average is None or volume is None:
            continue
        if closes[day] >= ma_value or volume <= volume_average * volume_ratio:
            continue
        if all(
            ma_long[day + offset] is not None
            and closes[day + offset] < ma_long[day + offset]
            for offset in range(1, confirm_days + 1)
        ):
            return True
    return False
