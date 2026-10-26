"""Indicator formulas, written to give the same numbers as TradingView.

Every function takes plain lists (oldest first) and returns a list of the
same length. Positions where there is not enough history yet hold None,
the way TradingView leaves the start of a line empty.

Two details matter for matching TradingView exactly:
- EMA and RMA ("Wilder's smoothing") start from a simple average of the
  first `length` values, then continue with their own formula.
- Bollinger Bands use the population standard deviation (divide by n).
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

Series = list[Optional[float]]


def _first_full_window(values: Sequence[Optional[float]], length: int) -> Optional[int]:
    """Index where the first `length` values in a row (no None) end."""
    run = 0
    for i, value in enumerate(values):
        run = run + 1 if value is not None else 0
        if run == length:
            return i
    return None


def sma(values: Sequence[Optional[float]], length: int) -> Series:
    """Simple moving average: the plain average of the last `length` values."""
    out: Series = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if all(v is not None for v in window):
            out[i] = sum(window) / length  # type: ignore[arg-type]
    return out


def _smoothed(values: Sequence[Optional[float]], length: int, alpha: float) -> Series:
    """Shared engine of EMA and RMA: start with an SMA, then
    new = alpha * value + (1 - alpha) * previous."""
    out: Series = [None] * len(values)
    start = _first_full_window(values, length)
    if start is None:
        return out
    previous = sum(values[start - length + 1 : start + 1]) / length  # type: ignore[arg-type]
    out[start] = previous
    for i in range(start + 1, len(values)):
        value = values[i]
        if value is None:
            break
        previous = alpha * value + (1 - alpha) * previous
        out[i] = previous
    return out


def ema(values: Sequence[Optional[float]], length: int) -> Series:
    """Exponential moving average (TradingView ta.ema). Reacts faster than SMA."""
    return _smoothed(values, length, 2 / (length + 1))


def rma(values: Sequence[Optional[float]], length: int) -> Series:
    """Wilder's moving average (TradingView ta.rma), used inside RSI, ATR and ADX."""
    return _smoothed(values, length, 1 / length)


def rsi(closes: Sequence[float], length: int = 14) -> Series:
    """Relative Strength Index, 0 to 100 (TradingView ta.rsi).

    Compares the average size of up moves with the average size of down moves.
    Above 70 is usually called "overbought", below 30 "oversold".
    """
    gains: Series = [None]
    losses: Series = [None]
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = rma(gains, length)
    avg_loss = rma(losses, length)
    out: Series = [None] * len(closes)
    for i, (gain, loss) in enumerate(zip(avg_gain, avg_loss)):
        if gain is None or loss is None:
            continue
        if loss == 0:
            out[i] = 100.0
        elif gain == 0:
            out[i] = 0.0
        else:
            out[i] = 100 - 100 / (1 + gain / loss)
    return out


def stdev(values: Sequence[float], length: int) -> Series:
    """Population standard deviation over the last `length` values (TradingView ta.stdev)."""
    out: Series = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        mean = sum(window) / length
        out[i] = math.sqrt(sum((v - mean) ** 2 for v in window) / length)
    return out


def bollinger(closes: Sequence[float], length: int = 20, mult: float = 2.0) -> tuple[Series, Series, Series]:
    """Bollinger Bands: (upper, middle, lower).

    The middle line is an SMA; the bands sit `mult` standard deviations away.
    Wide bands = big swings; narrow bands = a quiet market.
    """
    middle = sma(closes, length)
    deviation = stdev(closes, length)
    upper: Series = []
    lower: Series = []
    for m, d in zip(middle, deviation):
        upper.append(None if m is None or d is None else m + mult * d)
        lower.append(None if m is None or d is None else m - mult * d)
    return upper, middle, lower


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               first_is_high_low: bool = True) -> Series:
    """The full size of each candle's move, including a gap from the previous close.

    TradingView's ATR uses high - low for the very first candle; its DMI/ADX
    leaves the first candle empty. `first_is_high_low` chooses between the two.
    """
    out: Series = [(highs[0] - lows[0]) if first_is_high_low and highs else None] + [None] * (len(highs) - 1)
    for i in range(1, len(highs)):
        out[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    return out


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = 14) -> Series:
    """Average True Range (TradingView ta.atr): the typical candle size, in price units."""
    return rma(true_range(highs, lows, closes), length)


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        length: int = 14, smoothing: int = 14) -> Series:
    """Average Directional Index, 0 to 100 (TradingView's built-in DMI / ADX).

    Measures how strong a trend is, not its direction. Roughly: above 25 the
    market is trending, below 20 it is moving sideways.
    """
    n = len(highs)
    plus_dm: Series = [None] * n
    minus_dm: Series = [None] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    tr_avg = rma(true_range(highs, lows, closes, first_is_high_low=False), length)
    plus_avg = rma(plus_dm, length)
    minus_avg = rma(minus_dm, length)

    dx: Series = [None] * n
    for i in range(n):
        if tr_avg[i] is None or plus_avg[i] is None or minus_avg[i] is None:
            continue
        if tr_avg[i] == 0:
            plus_di = minus_di = 0.0
        else:
            plus_di = 100 * plus_avg[i] / tr_avg[i]
            minus_di = 100 * minus_avg[i] / tr_avg[i]
        total = plus_di + minus_di
        dx[i] = abs(plus_di - minus_di) / (total if total != 0 else 1)
    return [None if v is None else 100 * v for v in rma(dx, smoothing)]
