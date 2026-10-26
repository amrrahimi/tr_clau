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


def dmi(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        length: int = 14, smoothing: int = 14) -> tuple[Series, Series, Series]:
    """Directional Movement Index (TradingView's built-in DMI): (+DI, -DI, ADX).

    +DI and -DI show how strongly price is pushing up versus down; ADX (0 to
    100) shows how strong the trend is, not its direction. Roughly: ADX above
    25 means trending, below 20 means sideways.
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

    plus_di: Series = [None] * n
    minus_di: Series = [None] * n
    dx: Series = [None] * n
    for i in range(n):
        if tr_avg[i] is None or plus_avg[i] is None or minus_avg[i] is None:
            continue
        if tr_avg[i] == 0:
            p_di = m_di = 0.0
        else:
            p_di = 100 * plus_avg[i] / tr_avg[i]
            m_di = 100 * minus_avg[i] / tr_avg[i]
        plus_di[i], minus_di[i] = p_di, m_di
        total = p_di + m_di
        dx[i] = abs(p_di - m_di) / (total if total != 0 else 1)
    adx_line = [None if v is None else 100 * v for v in rma(dx, smoothing)]
    return plus_di, minus_di, adx_line


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        length: int = 14, smoothing: int = 14) -> Series:
    """Only the ADX line of the DMI."""
    return dmi(highs, lows, closes, length, smoothing)[2]


def wma(values: Sequence[Optional[float]], length: int) -> Series:
    """Weighted moving average (TradingView ta.wma): the newest value counts most."""
    out: Series = [None] * len(values)
    weights = list(range(1, length + 1))  # oldest 1 ... newest `length`
    total = sum(weights)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if all(v is not None for v in window):
            out[i] = sum(w * v for w, v in zip(weights, window)) / total  # type: ignore[operator]
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Series, Series, Series]:
    """MACD (TradingView defaults): (MACD line, signal line, histogram).

    MACD = fast EMA - slow EMA; the signal line is an EMA of MACD; the
    histogram is their difference.
    """
    fast_line = ema(closes, fast)
    slow_line = ema(closes, slow)
    macd_line: Series = [None if f is None or s is None else f - s for f, s in zip(fast_line, slow_line)]
    signal_line = ema(macd_line, signal)
    hist: Series = [None if m is None or g is None else m - g for m, g in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def highest(values: Sequence[Optional[float]], length: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if all(v is not None for v in window):
            out[i] = max(window)  # type: ignore[type-var]
    return out


def lowest(values: Sequence[Optional[float]], length: int) -> Series:
    out: Series = [None] * len(values)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if all(v is not None for v in window):
            out[i] = min(window)  # type: ignore[type-var]
    return out


def stoch_raw(source: Sequence[Optional[float]], highs: Sequence[Optional[float]],
              lows: Sequence[Optional[float]], length: int) -> Series:
    """TradingView ta.stoch: where the source sits in the recent high-low range, 0 to 100.
    A range of zero gives no value (TradingView also leaves it empty)."""
    hh = highest(highs, length)
    ll = lowest(lows, length)
    out: Series = [None] * len(source)
    for i, (x, h, l) in enumerate(zip(source, hh, ll)):
        if x is None or h is None or l is None or h == l:
            continue
        out[i] = 100 * (x - l) / (h - l)
    return out


def stochastic(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               k_length: int = 14, k_smoothing: int = 1, d_smoothing: int = 3) -> tuple[Series, Series]:
    """Stochastic oscillator (TradingView defaults 14, 1, 3): (%K, %D).
    Above 80 is usually called overbought, below 20 oversold."""
    k = sma(stoch_raw(closes, highs, lows, k_length), k_smoothing)
    d = sma(k, d_smoothing)
    return k, d


def stoch_rsi(closes: Sequence[float], k_smoothing: int = 3, d_smoothing: int = 3,
              rsi_length: int = 14, stoch_length: int = 14) -> tuple[Series, Series]:
    """Stochastic RSI (TradingView defaults 3, 3, 14, 14): the stochastic of RSI. (%K, %D)."""
    r = rsi(closes, rsi_length)
    k = sma(stoch_raw(r, r, r, stoch_length), k_smoothing)
    d = sma(k, d_smoothing)
    return k, d


def supertrend(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
               atr_length: int = 10, factor: float = 3.0) -> tuple[Series, list[Optional[int]]]:
    """SuperTrend (TradingView ta.supertrend): (line, direction).

    Direction -1 = uptrend (line under the price), 1 = downtrend (line above).
    The line only moves in the trend's favour, which makes it a trailing stop.
    """
    n = len(closes)
    atr_line = atr(highs, lows, closes, atr_length)
    line: Series = [None] * n
    direction: list[Optional[int]] = [None] * n
    prev_upper = prev_lower = 0.0  # TradingView: nz(band[1]) is 0 before the first value
    prev_line: Optional[float] = None
    for i in range(n):
        a = atr_line[i]
        if a is None:
            continue
        mid = (highs[i] + lows[i]) / 2
        upper = mid + factor * a
        lower = mid - factor * a
        prev_close = closes[i - 1] if i > 0 else None
        if not (lower > prev_lower or (prev_close is not None and prev_close < prev_lower)):
            lower = prev_lower
        if not (upper < prev_upper or (prev_close is not None and prev_close > prev_upper)):
            upper = prev_upper
        if i == 0 or atr_line[i - 1] is None:
            d = 1
        elif prev_line == prev_upper:
            d = -1 if closes[i] > upper else 1
        else:
            d = 1 if closes[i] < lower else -1
        line[i] = lower if d == -1 else upper
        direction[i] = d
        prev_upper, prev_lower, prev_line = upper, lower, line[i]
    return line, direction
