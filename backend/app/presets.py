"""Indicator settings: the shape of a settings set, and the automatic presets.

Automatic mode does not search for the "best" numbers on past data (that
tends to fit the past and fail later). It picks a well-known, conventional
set for the current market state and trading mode.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class IndicatorSettings:
    ema_fast_on: bool = True
    ema_fast: int = 20
    ema_slow_on: bool = True
    ema_slow: int = 50
    bb_on: bool = True
    bb_period: int = 20
    bb_mult: float = 2.0
    rsi_on: bool = True
    rsi_period: int = 14
    atr_period: int = 14  # ATR is always shown as a number

    def to_dict(self) -> dict:
        return asdict(self)


# Limits for manual settings, so a typo cannot ask for a 0- or 50000-candle average.
PERIOD_MIN, PERIOD_MAX = 2, 400
MULT_MIN, MULT_MAX = 0.5, 5.0

# Moving-average lengths per trading mode. Short for scalping, longer for daily.
MODE_EMAS = {
    "scalping": (9, 21),
    "daily": (20, 50),
}

# What each market state shows, on top of the mode's base settings:
# - trending:  follow the trend with the two EMAs; bands are less useful
# - ranging:   price swings between the bands; EMAs cross back and forth
# - volatile:  wider bands so normal swings are not mistaken for breakouts
# - unknown:   not enough history yet: show everything with standard values
_STATE_CHANGES = {
    "trend_up": dict(bb_on=False),
    "trend_down": dict(bb_on=False),
    "range": dict(ema_fast_on=False),
    "volatile": dict(bb_mult=2.5),
    "unknown": dict(),
}

STATES = list(_STATE_CHANGES)


def base_settings(trading_mode: str) -> IndicatorSettings:
    fast, slow = MODE_EMAS[trading_mode]
    return IndicatorSettings(ema_fast=fast, ema_slow=slow)


def auto_settings(state: str, trading_mode: str) -> IndicatorSettings:
    """The preset for a market state and trading mode ("scalping" or "daily")."""
    return replace(base_settings(trading_mode), **_STATE_CHANGES[state])


def validate(settings: IndicatorSettings) -> list[str]:
    """Problems with manual settings, as messages; empty when they are fine."""
    problems = []
    for name in ("ema_fast", "ema_slow", "bb_period", "rsi_period", "atr_period"):
        value = getattr(settings, name)
        if not PERIOD_MIN <= value <= PERIOD_MAX:
            problems.append(f"{name} must be between {PERIOD_MIN} and {PERIOD_MAX}")
    if not MULT_MIN <= settings.bb_mult <= MULT_MAX:
        problems.append(f"bb_mult must be between {MULT_MIN} and {MULT_MAX}")
    return problems
