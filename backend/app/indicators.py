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


def _rolling_extreme(values: Sequence[Optional[float]], length: int, better) -> Series:
    """Highest / lowest of the last `length` values in one pass (a queue of candidates), None where the
    window holds a None or is not full yet. Same numbers as taking max / min of every window, much faster."""
    out: Series = [None] * len(values)
    queue: list[int] = []     # indexes whose values could still be the window's extreme, best first
    head = 0
    last_none = -1
    for i, v in enumerate(values):
        if v is None:
            last_none = i
            queue, head = [], 0
            continue
        while len(queue) > head and not better(values[queue[-1]], v):
            queue.pop()
        queue.append(i)
        if queue[head] <= i - length:
            head += 1
        if head > 64:
            queue, head = queue[head:], 0
        if i >= length - 1 and last_none <= i - length:
            out[i] = values[queue[head]]
    return out


def highest(values: Sequence[Optional[float]], length: int) -> Series:
    return _rolling_extreme(values, length, lambda a, b: a > b)


def lowest(values: Sequence[Optional[float]], length: int) -> Series:
    return _rolling_extreme(values, length, lambda a, b: a < b)


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


# ---------- indicators added for the second strategy set (2026-11-11) ----------

def roc(values: Sequence[float], length: int) -> Series:
    """Rate of change in percent over `length` candles (TradingView ta.roc)."""
    out: Series = [None] * len(values)
    for i in range(length, len(values)):
        if values[i - length]:
            out[i] = (values[i] - values[i - length]) / values[i - length] * 100
    return out


def hma(values: Sequence[Optional[float]], length: int) -> Series:
    """Hull moving average (TradingView ta.hma): WMA(2 x WMA(n/2) - WMA(n), sqrt(n)). Smooth and fast."""
    half, full = wma(values, max(1, length // 2)), wma(values, length)
    diff: Series = [None if a is None or b is None else 2 * a - b for a, b in zip(half, full)]
    return wma(diff, max(1, int(math.sqrt(length))))


def kama(values: Sequence[float], length: int = 10, fast: int = 2, slow: int = 30) -> Series:
    """Kaufman's adaptive moving average: fast in a straight move, slow in a choppy one."""
    out: Series = [None] * len(values)
    if len(values) <= length:
        return out
    f, s = 2 / (fast + 1), 2 / (slow + 1)
    path = sum(abs(values[j] - values[j - 1]) for j in range(1, length + 1))
    previous = values[length]
    out[length] = previous
    for i in range(length + 1, len(values)):
        path += abs(values[i] - values[i - 1]) - abs(values[i - length] - values[i - length - 1])
        er = abs(values[i] - values[i - length]) / path if path > 0 else 0.0
        previous = previous + (er * (f - s) + s) ** 2 * (values[i] - previous)
        out[i] = previous
    return out


def efficiency(values: Sequence[float], length: int) -> Series:
    """Kaufman's efficiency ratio, 0 to 1: the straight move divided by the whole path."""
    out: Series = [None] * len(values)
    if len(values) <= length:
        return out
    path = sum(abs(values[j] - values[j - 1]) for j in range(1, length + 1))
    out[length] = abs(values[length] - values[0]) / path if path > 0 else 0.0
    for i in range(length + 1, len(values)):
        path += abs(values[i] - values[i - 1]) - abs(values[i - length] - values[i - length - 1])
        out[i] = abs(values[i] - values[i - length]) / path if path > 1e-300 else 0.0
    return out


def cci(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = 20) -> Series:
    """Commodity Channel Index (TradingView ta.cci on hlc3)."""
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    mean = sma(typical, length)
    out: Series = [None] * len(closes)
    for i in range(length - 1, len(closes)):
        m = mean[i]
        dev = sum(abs(v - m) for v in typical[i - length + 1: i + 1]) / length
        out[i] = (typical[i] - m) / (0.015 * dev) if dev > 0 else 0.0
    return out


def psar(highs: Sequence[float], lows: Sequence[float], start: float = 0.02, step: float = 0.02,
         maximum: float = 0.2) -> tuple[Series, list[Optional[int]]]:
    """Parabolic SAR: (line, direction). Direction 1 = the line is under the price (up), -1 = above."""
    n = len(highs)
    line: Series = [None] * n
    direction: list[Optional[int]] = [None] * n
    if n < 2:
        return line, direction
    up = highs[1] >= highs[0]
    sar = lows[0] if up else highs[0]
    extreme = highs[1] if up else lows[1]
    af = start
    line[1], direction[1] = sar, 1 if up else -1
    for i in range(2, n):
        sar = sar + af * (extreme - sar)
        if up:
            sar = min(sar, lows[i - 1], lows[i - 2])
            if lows[i] < sar:
                up, sar, extreme, af = False, extreme, lows[i], start
            elif highs[i] > extreme:
                extreme, af = highs[i], min(af + step, maximum)
        else:
            sar = max(sar, highs[i - 1], highs[i - 2])
            if highs[i] > sar:
                up, sar, extreme, af = True, extreme, highs[i], start
            elif lows[i] < extreme:
                extreme, af = lows[i], min(af + step, maximum)
        line[i], direction[i] = sar, 1 if up else -1
    return line, direction


def aroon(highs: Sequence[float], lows: Sequence[float], length: int = 14) -> tuple[Series, Series]:
    """Aroon (up, down), 0 to 100: how recently the highest high / lowest low of the window came."""
    n = len(highs)
    up: Series = [None] * n
    down: Series = [None] * n
    for i in range(length, n):
        hi = lo = i - length
        for j in range(i - length, i + 1):
            if highs[j] >= highs[hi]:
                hi = j
            if lows[j] <= lows[lo]:
                lo = j
        up[i] = 100 * (length - (i - hi)) / length
        down[i] = 100 * (length - (i - lo)) / length
    return up, down


def vortex(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
           length: int = 14) -> tuple[Series, Series]:
    """Vortex indicator: (VI+, VI-)."""
    n = len(highs)
    plus: Series = [None] * n
    minus: Series = [None] * n
    vp = [0.0] + [abs(highs[i] - lows[i - 1]) for i in range(1, n)]
    vm = [0.0] + [abs(lows[i] - highs[i - 1]) for i in range(1, n)]
    tr = true_range(highs, lows, closes)
    for i in range(length, n):
        total = sum(tr[i - length + 1: i + 1])  # type: ignore[arg-type]
        if total > 0:
            plus[i] = sum(vp[i - length + 1: i + 1]) / total
            minus[i] = sum(vm[i - length + 1: i + 1]) / total
    return plus, minus


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float]:
    """On-balance volume: volume added on up candles, taken away on down candles."""
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        v = volumes[i] or 0.0
        out[i] = out[i - 1] + (v if closes[i] > closes[i - 1] else -v if closes[i] < closes[i - 1] else 0.0)
    return out


def mfi(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], volumes: Sequence[float],
        length: int = 14) -> Series:
    """Money Flow Index, 0 to 100: an RSI that also weighs the volume."""
    n = len(closes)
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    pos = [0.0] * n
    neg = [0.0] * n
    for i in range(1, n):
        flow = typical[i] * (volumes[i] or 0.0)
        if typical[i] > typical[i - 1]:
            pos[i] = flow
        elif typical[i] < typical[i - 1]:
            neg[i] = flow
    out: Series = [None] * n
    for i in range(length, n):
        p, m = sum(pos[i - length + 1: i + 1]), sum(neg[i - length + 1: i + 1])
        out[i] = 100.0 if m == 0 else 100 - 100 / (1 + p / m)
    return out


def williams_r(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], length: int = 14) -> Series:
    """Williams %R, -100 to 0: where the close sits in the recent range (-100 = at the low)."""
    hh, ll = highest(highs, length), lowest(lows, length)
    return [None if h is None or l is None or h == l else -100 * (h - c) / (h - l) for h, l, c in zip(hh, ll, closes)]


def trix(closes: Sequence[float], length: int = 15) -> Series:
    """TRIX: percent change of a triple-smoothed EMA."""
    e3 = ema(ema(ema(closes, length), length), length)
    out: Series = [None] * len(closes)
    for i in range(1, len(closes)):
        if e3[i] is not None and e3[i - 1]:
            out[i] = (e3[i] - e3[i - 1]) / e3[i - 1] * 100
    return out
