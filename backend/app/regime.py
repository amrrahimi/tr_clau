"""Market state detection: trending up, trending down, ranging or volatile.

Agreed rules (phase 2 design):
- Only closed candles are judged; the candle still forming is left out.
- "Slower but more certain": a new state is adopted only after its
  conditions hold for CONFIRM_CANDLES closed candles in a row.
- ADX between RANGE_BELOW and TREND_FROM is a grey zone: the previous
  state stays, so the label does not flip back and forth around one number.
- Volatile wins over the others: big swings matter most to a beginner.

The detection uses fixed settings, independent of what the user chose to
draw on the chart, so manual chart settings never change the label.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from . import indicators as ind
from .presets import MODE_EMAS

CONFIRM_CANDLES = 3
TREND_FROM = 25.0     # ADX at or above: trending
RANGE_BELOW = 20.0    # ADX below: ranging
VOLATILE_RATIO = 1.5  # ATR at least this many times its recent average: volatile
ATR_AVERAGE = 50      # candles in that recent average
ADX_LENGTH = 14
ATR_LENGTH = 14


@dataclass
class StateReading:
    """Everything the label needs about the latest closed candle."""
    state: str                 # trend_up, trend_down, range, volatile or unknown
    since: Optional[int]       # time the current state was adopted (seconds)
    adx: Optional[float]
    atr: Optional[float]
    atr_ratio: Optional[float]  # ATR / its recent average


def raw_state(adx: Optional[float], ema_fast: Optional[float], ema_slow: Optional[float],
              atr: Optional[float], atr_avg: Optional[float]) -> Optional[str]:
    """The state one candle points to, before confirmation. None = no clear answer."""
    if atr is not None and atr_avg and atr >= VOLATILE_RATIO * atr_avg:
        return "volatile"
    if adx is None:
        return None
    if adx >= TREND_FROM:
        if ema_fast is None or ema_slow is None:
            return None
        return "trend_up" if ema_fast > ema_slow else "trend_down"
    if adx < RANGE_BELOW:
        return "range"
    return None  # grey zone


def confirm(raw: Sequence[Optional[str]], needed: int = CONFIRM_CANDLES) -> list[str]:
    """Turn per-candle readings into confirmed states.

    A new state is adopted on the `needed`-th candle in a row that points to it.
    A candle with no clear answer (grey zone) interrupts the count.
    """
    confirmed = "unknown"
    candidate: Optional[str] = None
    count = 0
    out = []
    for reading in raw:
        if reading is None or reading == confirmed:
            candidate, count = None, 0
        elif reading == candidate:
            count += 1
        else:
            candidate, count = reading, 1
        if candidate is not None and count >= needed:
            confirmed, candidate, count = candidate, None, 0
        out.append(confirmed)
    return out


def detect(candles: Sequence[dict], trading_mode: str) -> tuple[list[str], StateReading]:
    """Confirmed state for every candle given (all must be closed), plus a summary of the last."""
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    fast_len, slow_len = MODE_EMAS[trading_mode]

    adx = ind.adx(highs, lows, closes, ADX_LENGTH, ADX_LENGTH)
    fast = ind.ema(closes, fast_len)
    slow = ind.ema(closes, slow_len)
    atr = ind.atr(highs, lows, closes, ATR_LENGTH)
    atr_avg = ind.sma(atr, ATR_AVERAGE)

    raw = [raw_state(adx[i], fast[i], slow[i], atr[i], atr_avg[i]) for i in range(len(candles))]
    states = confirm(raw)

    if not candles:
        return states, StateReading("unknown", None, None, None, None)
    last = len(candles) - 1
    since = None
    if states[last] != "unknown":
        i = last
        while i > 0 and states[i - 1] == states[last]:
            i -= 1
        since = candles[i]["time"]
    ratio = atr[last] / atr_avg[last] if atr[last] is not None and atr_avg[last] else None
    return states, StateReading(states[last], since, adx[last], atr[last], ratio)
