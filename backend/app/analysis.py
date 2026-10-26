"""Analysis for one chart: market state plus the lines of each indicator.

Flow: candles -> keep closed ones -> detect market state ->
choose the indicator list (the bot's automatic list, or the user's) -> lines.
"""

from __future__ import annotations

import time
from typing import Optional, Sequence

from . import config
from . import indicators as ind
from .catalog import Instance, compute_instances, parse_instances
from .presets import auto_instances
from .regime import ATR_LENGTH, detect

# Candles fetched for the analysis. Indicators need earlier candles to "warm
# up"; without them the first values differ from TradingView's.
ANALYSIS_CANDLES = 1000
# Points of each line sent back to the chart (the warm-up part is dropped).
RETURNED_POINTS = 500


def closed_only(candles: Sequence[dict], timeframe: str, now: float) -> list[dict]:
    """Drop the candle that is still forming (its end time is in the future)."""
    length = config.TIMEFRAME_SECONDS[timeframe]
    return [c for c in candles if c["time"] + length <= now]


def analyze(
    candles: Sequence[dict],
    timeframe: str,
    trading_mode: str,
    instances: Optional[list[Instance]] = None,
    now: Optional[float] = None,
    returned_points: int = RETURNED_POINTS,
) -> dict:
    """With `instances` the user's list is drawn; without, the bot chooses (automatic)."""
    closed = closed_only(candles, timeframe, time.time() if now is None else now)
    states, reading = detect(closed, trading_mode)
    is_auto = instances is None
    if instances is None:
        instances = parse_instances(auto_instances(reading.state, trading_mode))

    highs = [c["high"] for c in closed]
    lows = [c["low"] for c in closed]
    closes = [c["close"] for c in closed]
    atr = ind.atr(highs, lows, closes, ATR_LENGTH)

    # State changes only (not one entry per candle), for marking on the chart later.
    cut = max(0, len(closed) - returned_points)
    changes = []
    for i in range(cut, len(closed)):
        if i == cut or states[i] != states[i - 1]:
            changes.append({"time": closed[i]["time"], "state": states[i]})

    return {
        "auto": is_auto,
        "tradingMode": trading_mode,
        "indicators": compute_instances(closed, instances, returned_points),
        "state": {
            "current": reading.state,
            "since": reading.since,
            "adx": reading.adx,
            "atrRatio": reading.atr_ratio,
        },
        "atr": atr[-1] if atr else None,
        "atrLength": ATR_LENGTH,
        "lastClosedTime": closed[-1]["time"] if closed else None,
        "stateChanges": changes,
    }
