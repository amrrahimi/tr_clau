"""Phase 2 analysis: market state plus indicator lines for one chart.

Flow: candles -> keep closed ones -> detect market state ->
choose settings (automatic preset, or the user's manual ones) -> indicator lines.
"""

from __future__ import annotations

import time
from typing import Optional, Sequence

from . import config
from . import indicators as ind
from .catalog import Instance, compute_instances, parse_instances
from .presets import IndicatorSettings, auto_instances, auto_settings, settings_to_instances
from .regime import detect

# Candles fetched for the analysis. Indicators need earlier candles to "warm
# up"; without them the first values differ from TradingView's.
ANALYSIS_CANDLES = 1000
# Points of each line sent back to the chart (the warm-up part is dropped).
RETURNED_POINTS = 500


def closed_only(candles: Sequence[dict], timeframe: str, now: float) -> list[dict]:
    """Drop the candle that is still forming (its end time is in the future)."""
    length = config.TIMEFRAME_SECONDS[timeframe]
    return [c for c in candles if c["time"] + length <= now]


def _line(candles: Sequence[dict], values: Sequence[Optional[float]]) -> list[dict]:
    return [{"time": c["time"], "value": v} for c, v in zip(candles, values) if v is not None]


def analyze(
    candles: Sequence[dict],
    timeframe: str,
    trading_mode: str,
    manual: Optional[IndicatorSettings] = None,
    now: Optional[float] = None,
    instances: Optional[list[Instance]] = None,
    returned_points: int = RETURNED_POINTS,
) -> dict:
    """`instances` (a list of indicators) wins over `manual`; with neither, the bot chooses (automatic)."""
    closed = closed_only(candles, timeframe, time.time() if now is None else now)
    states, reading = detect(closed, trading_mode)
    settings = manual if manual is not None else auto_settings(reading.state, trading_mode)
    is_auto = manual is None and instances is None
    if instances is None:
        chosen = auto_instances(reading.state, trading_mode) if manual is None else settings_to_instances(manual)
        instances = parse_instances(chosen)

    closes = [c["close"] for c in closed]
    highs = [c["high"] for c in closed]
    lows = [c["low"] for c in closed]
    shown = closed[-returned_points:]
    cut = len(closed) - len(shown)

    def tail(values):
        return _line(shown, values[cut:])

    lines: dict[str, list[dict]] = {}
    if settings.ema_fast_on:
        lines["emaFast"] = tail(ind.ema(closes, settings.ema_fast))
    if settings.ema_slow_on:
        lines["emaSlow"] = tail(ind.ema(closes, settings.ema_slow))
    if settings.bb_on:
        upper, middle, lower = ind.bollinger(closes, settings.bb_period, settings.bb_mult)
        lines["bbUpper"], lines["bbMiddle"], lines["bbLower"] = tail(upper), tail(middle), tail(lower)
    if settings.rsi_on:
        lines["rsi"] = tail(ind.rsi(closes, settings.rsi_period))
    atr = ind.atr(highs, lows, closes, settings.atr_period)

    # State changes only (not one entry per candle), for marking on the chart later.
    changes = []
    for i in range(cut, len(closed)):
        if i == cut or states[i] != states[i - 1]:
            changes.append({"time": closed[i]["time"], "state": states[i]})

    return {
        "auto": is_auto,
        # Phase 2b: one entry per indicator on the chart (replaces "settings"/"lines" in the new screen).
        "indicators": compute_instances(closed, instances, returned_points),
        "tradingMode": trading_mode,
        "settings": settings.to_dict(),
        "state": {
            "current": reading.state,
            "since": reading.since,
            "adx": reading.adx,
            "atrRatio": reading.atr_ratio,
        },
        "atr": atr[-1] if atr else None,
        "lastClosedTime": closed[-1]["time"] if closed else None,
        "lines": lines,
        "stateChanges": changes,
    }
