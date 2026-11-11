"""Strategies: rules that say when to enter a trade and where its stop-loss
and take-profit go. Indicators only draw lines; a strategy turns those lines
into trades.

Like the indicator catalog, each strategy is one "card" (Strategy) with its
name, the market states it suits, its settings and its rule. The screen builds
its strategy list from the cards; adding a strategy = adding one card.

Common rules (agreed with the owner, the same for every strategy):
- A signal is judged only on a closed candle.
- The trade is entered at the open of the next candle.
- One position at a time per strategy; signals while a position is open are ignored.
- If one candle touches both stop-loss and take-profit, it counts as a loss
  (we cannot know which came first, so we assume the worse).
- Fees (phase 3): entry, stop-loss and time exits are market orders (taker
  fee); the take-profit is a waiting limit order (maker fee). Results are
  after fees.

Three extra rules, each with an on/off setting on every strategy (owner's choice):
- Market state: trade only when the market is in a state the strategy suits;
  trend strategies trade only with the trend (long in an uptrend, short in a downtrend).
- Break-even: once the price has gone part of the way to the take-profit
  (half by default), the stop-loss moves to the break-even price: the price
  where the trade, after both fees, ends with neither profit nor loss.
- Time limit: after N candles, a trade that is in profit is closed at the
  candle's close. A trade in loss is not forced out (that would lock in the loss).
- Fee vs risk: a trade is skipped when the round-trip fee is more than a
  part (a third by default) of the distance to the stop-loss; with such a
  tight stop the fee alone decides the result.

Each rule below is written for long trades; short trades are the mirror image.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import config
from . import indicators as ind
from .catalog import Candles, Param
from .presets import LONG_EMA

LONG, SHORT = "long", "short"


@dataclass(frozen=True)
class Signal:
    """A signal on a closed candle. The stop is a price, or a distance from
    the entry; the target is a price, or a reward:risk ratio."""
    index: int
    side: str
    stop_price: Optional[float] = None
    stop_distance: Optional[float] = None
    target_price: Optional[float] = None
    reward: Optional[float] = None


@dataclass(frozen=True)
class Strategy:
    type: str
    name: str
    states: tuple[str, ...]              # market states it suits (for suggestions later)
    uses: tuple[str, ...]                # indicators it reads, e.g. ("EMA", "ATR")
    params: tuple[Param, ...]
    signals: Callable[[Candles, dict], list[Signal]] = field(repr=False)
    lines: Callable[[dict], list[dict]] = field(repr=False, default=lambda p: [])

    @property
    def all_params(self) -> tuple[Param, ...]:
        return self.params + COMMON_PARAMS

    def public(self) -> dict:
        data = asdict(self)
        data.pop("signals")
        data.pop("lines")
        data["params"] = [asdict(p) for p in self.all_params]
        data["modeDefaults"] = {"trend": dict(LONG_EMA)} if any(p.name == "trend" for p in self.params) else {}
        return data


def _crossed_up(a, b, i) -> bool:
    return None not in (a[i - 1], b[i - 1], a[i], b[i]) and a[i - 1] <= b[i - 1] and a[i] > b[i]


def _crossed_down(a, b, i) -> bool:
    return None not in (a[i - 1], b[i - 1], a[i], b[i]) and a[i - 1] >= b[i - 1] and a[i] < b[i]


def _ready(*values) -> bool:
    return all(v is not None for v in values)


# The three extra rules, shared by every strategy (1 = on, 0 = off for the first;
# 0 turns the other two off).
COMMON_PARAMS = (
    Param("state_filter", 1, 0, 1),
    Param("breakeven", 0.5, 0, 0.95, 0.05),   # part of the way to the take-profit
    Param("max_candles", 0, 0, 1000),         # candles before a trade in profit is closed (0 = off, owner's choice)
    Param("fee_ratio", 0.33, 0, 1, 0.01),     # most of the stop distance the fees may take
)

# Settings shared by several strategies.
TREND = Param("trend", 200, 2, 500)
ATR_LENGTH = Param("atr_length", 14, 1, 500)


def _reward(default: float) -> Param:
    return Param("reward", default, 0.5, 10, 0.1)


def _atr_mult(default: float) -> Param:
    return Param("atr_mult", default, 0.1, 10, 0.1)


# 1. EMA crossover with a trend filter.
def _ema_cross(c: Candles, p: dict) -> list[Signal]:
    fast, slow = ind.ema(c.closes, p["fast"]), ind.ema(c.closes, p["slow"])
    trend = ind.ema(c.closes, p["trend"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["atr_length"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if _crossed_up(fast, slow, i) and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif _crossed_down(fast, slow, i) and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 2. MACD cross on the "cheap" side of zero, with the 200 EMA trend filter.
def _macd_ema(c: Candles, p: dict) -> list[Signal]:
    line, signal, _ = ind.macd(c.closes, p["fast"], p["slow"], p["signal"])
    trend = ind.ema(c.closes, p["trend"])
    low, high = ind.lowest(c.lows, p["swing"]), ind.highest(c.highs, p["swing"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], low[i], line[i]):
            continue
        if _crossed_up(line, signal, i) and line[i] < 0 and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=low[i], reward=p["reward"]))
        elif _crossed_down(line, signal, i) and line[i] > 0 and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=high[i], reward=p["reward"]))
    return out


# 3. RSI pullback inside a trend.
def _rsi_pullback(c: Candles, p: dict) -> list[Signal]:
    rsi = ind.rsi(c.closes, p["rsi_length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["atr_length"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], atr[i], rsi[i], rsi[i - 1]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > trend[i] and rsi[i - 1] < p["oversold"] <= rsi[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < trend[i] and rsi[i - 1] > p["overbought"] >= rsi[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 4. Back inside the Bollinger Bands (for ranging markets).
def _bb_reversion(c: Candles, p: dict) -> list[Signal]:
    upper, basis, lower = ind.bollinger(c.closes, p["length"], p["mult"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(lower[i - 1], lower[i]):
            continue
        if c.closes[i - 1] < lower[i - 1] and c.closes[i] > lower[i]:
            out.append(Signal(i, LONG, stop_price=min(c.lows[i - 1], c.lows[i]), target_price=basis[i]))
        elif c.closes[i - 1] > upper[i - 1] and c.closes[i] < upper[i]:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[i - 1], c.highs[i]), target_price=basis[i]))
    return out


# 5. SuperTrend turns, in the direction of the 200 EMA.
def _supertrend(c: Candles, p: dict) -> list[Signal]:
    line, direction = ind.supertrend(c.highs, c.lows, c.closes, p["atr_length"], p["factor"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], line[i], direction[i - 1]):
            continue
        if direction[i - 1] == 1 and direction[i] == -1 and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=line[i], reward=p["reward"]))
        elif direction[i - 1] == -1 and direction[i] == 1 and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=line[i], reward=p["reward"]))
    return out


# 6. Channel breakout ("Turtle" style): close beyond the last N candles' high/low.
def _donchian(c: Candles, p: dict) -> list[Signal]:
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["atr_length"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(high[i - 1], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > high[i - 1]:      # above the previous N candles (this one not included)
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < low[i - 1]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# ---------- owner's step 3: Smart Money / ICT / RTM, squeeze, VWAP ----------
# Stops get a small buffer beyond the zone (part of an ATR), so a touch of the exact edge
# does not count as a loss.

BUFFER = Param("buffer", 0.2, 0, 5, 0.05)        # x ATR beyond the zone / wick
MAX_WAIT = Param("max_wait", 30, 1, 500)          # candles a zone or gap waits for the price to come back


# 7. Liquidity sweep: the candle's wick runs past the high/low of the last N candles (the stops
#    sitting there are taken) and the candle closes back inside -> trade the way back.
def _liquidity_sweep(c: Candles, p: dict) -> list[Signal]:
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(high[i - 1], low[i - 1], atr[i]):
            continue
        buf = p["buffer"] * atr[i]
        if c.lows[i] < low[i - 1] < c.closes[i]:
            out.append(Signal(i, LONG, stop_price=c.lows[i] - buf, reward=p["reward"]))
        elif c.highs[i] > high[i - 1] > c.closes[i]:
            out.append(Signal(i, SHORT, stop_price=c.highs[i] + buf, reward=p["reward"]))
    return out


# 8. Fair value gap retest: three candles where the middle one moved so fast that the first
#    candle's high and the third candle's low do not overlap (a "gap"). In the trend's direction,
#    wait for the price to come back into the gap and close out of it again.
def _fvg_retest(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out, gaps = [], []          # gap: [side, bottom, top, born]
    for i in range(2, len(c.closes)):
        if not _ready(trend[i], atr[i]):
            continue
        buf = p["buffer"] * atr[i]
        keep = []
        fired = False
        for side, bottom, top, born in gaps:
            if i - born > p["max_wait"]:
                continue
            if side == LONG:
                if c.closes[i] < bottom:
                    continue                                     # gap filled through: gone
                if not fired and c.lows[i] <= top and c.closes[i] > top:
                    out.append(Signal(i, LONG, stop_price=bottom - buf, reward=p["reward"]))
                    fired = True
                    continue
            else:
                if c.closes[i] > top:
                    continue
                if not fired and c.highs[i] >= bottom and c.closes[i] < bottom:
                    out.append(Signal(i, SHORT, stop_price=top + buf, reward=p["reward"]))
                    fired = True
                    continue
            keep.append((side, bottom, top, born))
        gaps = keep[-20:]
        if c.lows[i] > c.highs[i - 2] and c.closes[i] > trend[i]:
            gaps.append((LONG, c.highs[i - 2], c.lows[i], i))
        elif c.highs[i] < c.lows[i - 2] and c.closes[i] < trend[i]:
            gaps.append((SHORT, c.highs[i], c.lows[i - 2], i))
    return out


# 9. Order block: the price breaks the high of the last N candles (break of structure) in the
#    trend's direction; the last opposite-coloured candle before that move is the "order block".
#    Trade when the price comes back to it and closes away from it again.
def _order_block(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    high, low = ind.highest(c.highs, p["swing"]), ind.lowest(c.lows, p["swing"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out, block = [], None       # block: [side, bottom, top, born]
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], high[i - 1], atr[i]):
            continue
        buf = p["buffer"] * atr[i]
        if block is not None:
            side, bottom, top, born = block
            if i - born > p["max_wait"] or (side == LONG and c.closes[i] < bottom) or (side == SHORT and c.closes[i] > top):
                block = None
            elif side == LONG and c.lows[i] <= top and c.closes[i] > top:
                out.append(Signal(i, LONG, stop_price=bottom - buf, reward=p["reward"]))
                block = None
            elif side == SHORT and c.highs[i] >= bottom and c.closes[i] < bottom:
                out.append(Signal(i, SHORT, stop_price=top + buf, reward=p["reward"]))
                block = None
        if block is None:
            start = max(0, i - p["swing"])
            if c.closes[i] > high[i - 1] and c.closes[i] > trend[i]:
                k = next((j for j in range(i - 1, start - 1, -1) if c.closes[j] < c.opens[j]), None)
                if k is not None:
                    block = (LONG, c.lows[k], c.highs[k], i)
            elif c.closes[i] < low[i - 1] and c.closes[i] < trend[i]:
                k = next((j for j in range(i - 1, start - 1, -1) if c.closes[j] > c.opens[j]), None)
                if k is not None:
                    block = (SHORT, c.lows[k], c.highs[k], i)
    return out


# 10. Fresh supply and demand (RTM): a "base" of 1-3 small candles, then a big candle leaving it
#     (at least leg x ATR). The first time the price comes back to the base, trade the same way
#     as the leg. A zone is used once ("fresh" only).
def _sd_zone(c: Candles, p: dict) -> list[Signal]:
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out, zones = [], []         # zone: (side, bottom, top, born)
    for i in range(4, len(c.closes)):
        if not _ready(atr[i - 1], atr[i]):
            continue
        buf = p["buffer"] * atr[i]
        keep = []
        for side, bottom, top, born in zones:
            if i - born > p["max_wait"]:
                continue
            touched = c.lows[i] <= top if side == LONG else c.highs[i] >= bottom
            if not touched:
                keep.append((side, bottom, top, born))
                continue
            # touched: trade if it closed back away from the zone; the zone is used up either way
            if side == LONG and c.closes[i] > top:
                out.append(Signal(i, LONG, stop_price=bottom - buf, reward=p["reward"]))
            elif side == SHORT and c.closes[i] < bottom:
                out.append(Signal(i, SHORT, stop_price=top + buf, reward=p["reward"]))
        zones = keep[-20:]
        rng = c.highs[i] - c.lows[i]
        body = abs(c.closes[i] - c.opens[i])
        if rng < p["leg"] * atr[i - 1] or body < 0.6 * rng:
            continue
        base = []
        for j in range(i - 1, max(i - 4, 0), -1):
            if c.highs[j] - c.lows[j] <= 0.6 * atr[i - 1]:
                base.append(j)
            else:
                break
        if not base:
            continue
        bottom = min(c.lows[j] for j in base)
        top = max(c.highs[j] for j in base)
        zones.append((LONG if c.closes[i] > c.opens[i] else SHORT, bottom, top, i))
    return out


# 11. Squeeze breakout: the Bollinger Bands sit inside the Keltner Channel for a while (a very
#     quiet market). When they come out again, trade the direction of the move.
def _squeeze(c: Candles, p: dict) -> list[Signal]:
    upper, basis, lower = ind.bollinger(c.closes, p["length"], 2.0)
    mid = ind.ema(c.closes, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["length"])
    out, quiet = [], 0
    for i in range(1, len(c.closes)):
        if not _ready(upper[i], mid[i], atr[i]):
            continue
        inside = upper[i] < mid[i] + p["kc_mult"] * atr[i] and lower[i] > mid[i] - p["kc_mult"] * atr[i]
        if inside:
            quiet += 1
            continue
        if quiet >= p["min_quiet"]:
            stop = atr[i] * p["atr_mult"]
            if c.closes[i] > basis[i] and c.closes[i] > c.closes[i - 1]:
                out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
            elif c.closes[i] < basis[i] and c.closes[i] < c.closes[i - 1]:
                out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
        quiet = 0
    return out


# 12. VWAP reversion: the price stretched far from the volume-weighted average of the last N
#     candles and closes back toward it -> trade back to the VWAP.
def _vwap_reversion(c: Candles, p: dict) -> list[Signal]:
    n = p["length"]
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    pv = vol = 0.0
    window = []
    vwap = [None] * len(c.closes)
    for i in range(len(c.closes)):
        typical = (c.highs[i] + c.lows[i] + c.closes[i]) / 3
        v = c.volumes[i] or 0.0
        window.append((typical * v, v))
        pv += typical * v
        vol += v
        if len(window) > n:
            a, b = window.pop(0)
            pv -= a
            vol -= b
        if len(window) == n and vol > 0:
            vwap[i] = pv / vol
    for i in range(1, len(c.closes)):
        if not _ready(vwap[i], vwap[i - 1], atr[i], atr[i - 1]):
            continue
        band = p["band"] * atr[i]
        buf = 0.2 * atr[i]
        if c.closes[i - 1] < vwap[i - 1] - p["band"] * atr[i - 1] and c.closes[i] > vwap[i] - band:
            out.append(Signal(i, LONG, stop_price=min(c.lows[i - 1], c.lows[i]) - buf, target_price=vwap[i]))
        elif c.closes[i - 1] > vwap[i - 1] + p["band"] * atr[i - 1] and c.closes[i] < vwap[i] + band:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[i - 1], c.highs[i]) + buf, target_price=vwap[i]))
    return out


# 13. EMA pullback: in a trend (EMA 50 above EMA 200, price above both), the price dips to the
#     EMA 50 and closes back above the fast EMA -> join the trend. Mirror for shorts.
def _ema_pullback(c: Candles, p: dict) -> list[Signal]:
    fast = ind.ema(c.closes, p["fast"])
    mid = ind.ema(c.closes, p["slow"])
    trend = ind.ema(c.closes, p["trend"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(fast[i], mid[i], trend[i], atr[i], mid[i - 1]):
            continue
        buf = p["buffer"] * atr[i]
        touched_low = min(c.lows[i - 1], c.lows[i]) <= mid[i]
        touched_high = max(c.highs[i - 1], c.highs[i]) >= mid[i]
        if mid[i] > trend[i] and mid[i] > mid[i - 1] and touched_low and c.closes[i] > fast[i] > mid[i]:
            out.append(Signal(i, LONG, stop_price=min(c.lows[i - 1], c.lows[i], mid[i]) - buf, reward=p["reward"]))
        elif mid[i] < trend[i] and mid[i] < mid[i - 1] and touched_high and c.closes[i] < fast[i] < mid[i]:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[i - 1], c.highs[i], mid[i]) + buf, reward=p["reward"]))
    return out


# 14. DMI / ADX: +DI crosses above -DI while ADX shows a real trend -> long (mirror for short).
def _dmi_adx(c: Candles, p: dict) -> list[Signal]:
    plus, minus, adx = ind.dmi(c.highs, c.lows, c.closes, p["length"], p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(adx[i], atr[i]) or adx[i] < p["min_adx"]:
            continue
        stop = p["atr_mult"] * atr[i]
        if _crossed_up(plus, minus, i):
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif _crossed_down(plus, minus, i):
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


def _midpoint(c: Candles, n: int) -> list:
    hi, lo = ind.highest(c.highs, n), ind.lowest(c.lows, n)
    return [None if h is None or l is None else (h + l) / 2 for h, l in zip(hi, lo)]


# 15. Ichimoku: Tenkan crosses Kijun with the price above the cloud (below for shorts).
#     The cloud at a candle is the one drawn 26 candles earlier, as on the chart.
def _ichimoku(c: Candles, p: dict) -> list[Signal]:
    tenkan, kijun = _midpoint(c, p["tenkan"]), _midpoint(c, p["kijun"])
    span_b = _midpoint(c, p["span_b"])
    span_a = [None if t is None or k is None else (t + k) / 2 for t, k in zip(tenkan, kijun)]
    shift = p["kijun"]
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    for i in range(max(1, shift), len(c.closes)):
        a, b = span_a[i - shift], span_b[i - shift]
        if not _ready(a, b, kijun[i], atr[i]):
            continue
        top, bottom = max(a, b), min(a, b)
        buf = 0.2 * atr[i]
        if _crossed_up(tenkan, kijun, i) and c.closes[i] > top:
            out.append(Signal(i, LONG, stop_price=min(kijun[i], c.lows[i]) - buf, reward=p["reward"]))
        elif _crossed_down(tenkan, kijun, i) and c.closes[i] < bottom:
            out.append(Signal(i, SHORT, stop_price=max(kijun[i], c.highs[i]) + buf, reward=p["reward"]))
    return out


# 16. Inside bar breakout: a candle inside the previous one (a pause), then a close beyond the
#     big candle in the trend's direction. Stop: the other side of the big candle.
def _inside_bar(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(2, len(c.closes)):
        if not _ready(trend[i]):
            continue
        m = i - 2   # the big ("mother") candle, i - 1 the inside one
        inside = c.highs[i - 1] < c.highs[m] and c.lows[i - 1] > c.lows[m]
        if not inside:
            continue
        if c.closes[i] > c.highs[m] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=c.lows[m], reward=p["reward"]))
        elif c.closes[i] < c.lows[m] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=c.highs[m], reward=p["reward"]))
    return out


# 17. Stochastic RSI pullback: in the trend's direction, %K crosses %D out of the oversold
#     (long) or overbought (short) zone.
def _stoch_rsi_trend(c: Candles, p: dict) -> list[Signal]:
    k, d = ind.stoch_rsi(c.closes, 3, 3, p["rsi_length"], p["rsi_length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = ind.atr(c.highs, c.lows, c.closes, 14)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(k[i - 1], d[i - 1], trend[i], atr[i]):
            continue
        stop = p["atr_mult"] * atr[i]
        if c.closes[i] > trend[i] and _crossed_up(k, d, i) and k[i - 1] < p["oversold"]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < trend[i] and _crossed_down(k, d, i) and k[i - 1] > p["overbought"]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 18. Volume breakout: a close outside the Keltner channel on clearly higher volume than usual,
#     in the trend's direction. Stop: the channel's middle line.
def _volume_breakout(c: Candles, p: dict) -> list[Signal]:
    mid = ind.ema(c.closes, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["length"])
    avg_volume = ind.sma(c.volumes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(mid[i], atr[i], avg_volume[i - 1], trend[i]) or not avg_volume[i - 1]:
            continue
        loud = (c.volumes[i] or 0) >= p["volume_mult"] * avg_volume[i - 1]
        upper, lower = mid[i] + p["kc_mult"] * atr[i], mid[i] - p["kc_mult"] * atr[i]
        if loud and c.closes[i] > upper and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=mid[i], reward=p["reward"]))
        elif loud and c.closes[i] < lower and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=mid[i], reward=p["reward"]))
    return out


# ---------- second strategy set (2026-11-11): the trend / breakout family and well-known classics ----------
# Tested on 28 months of 5m futures candles (about 95 coins, after fees): see docs/RESEARCH-2026-11-11.md.

def _atr_stop(c: Candles, p: dict) -> list:
    return ind.atr(c.highs, c.lows, c.closes, 14)


# 19. Turtle breakout: a close beyond the high / low of the last N candles (55: the slow Turtle system),
#     only on the trend EMA's side. Stop: a multiple of ATR.
def _turtle(c: Candles, p: dict) -> list[Signal]:
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(high[i - 1], low[i - 1], atr[i], trend[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > high[i - 1] and c.closes[i - 1] <= high[i - 1] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < low[i - 1] and c.closes[i - 1] >= low[i - 1] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 20. Keltner breakout: the close crosses out of the Keltner channel on the trend's side. Stop: the middle line.
def _keltner_breakout(c: Candles, p: dict) -> list[Signal]:
    mid = ind.ema(c.closes, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(mid[i - 1], atr[i - 1], trend[i]):
            continue
        up, dn = mid[i] + p["kc_mult"] * atr[i], mid[i] - p["kc_mult"] * atr[i]
        pup, pdn = mid[i - 1] + p["kc_mult"] * atr[i - 1], mid[i - 1] - p["kc_mult"] * atr[i - 1]
        if c.closes[i] > up and c.closes[i - 1] <= pup and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=mid[i], reward=p["reward"]))
        elif c.closes[i] < dn and c.closes[i - 1] >= pdn and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=mid[i], reward=p["reward"]))
    return out


# 21. Bollinger breakout: the close crosses out of the bands while they are widening, on the trend's side.
#     Stop: the middle line.
def _bb_breakout(c: Candles, p: dict) -> list[Signal]:
    upper, basis, lower = ind.bollinger(c.closes, p["length"], p["mult"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(upper[i - 1], trend[i]):
            continue
        widening = upper[i] - lower[i] > upper[i - 1] - lower[i - 1]
        if widening and c.closes[i] > upper[i] and c.closes[i - 1] <= upper[i - 1] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=basis[i], reward=p["reward"]))
        elif widening and c.closes[i] < lower[i] and c.closes[i - 1] >= lower[i - 1] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=basis[i], reward=p["reward"]))
    return out


# 22. EMA ribbon: three EMAs fall into order (fast > middle > slow) on the trend's side.
def _ema_ribbon(c: Candles, p: dict) -> list[Signal]:
    a, b, d = ind.ema(c.closes, p["fast"]), ind.ema(c.closes, p["mid"]), ind.ema(c.closes, p["slow"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(d[i - 1], trend[i], atr[i]):
            continue
        up, was_up = a[i] > b[i] > d[i], a[i - 1] > b[i - 1] > d[i - 1]
        down, was_down = a[i] < b[i] < d[i], a[i - 1] < b[i - 1] < d[i - 1]
        stop = atr[i] * p["atr_mult"]
        if up and not was_up and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif down and not was_down and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 23. Momentum thrust: the move of the last N candles becomes larger than `thrust` ATRs (time-series momentum).
def _momentum(c: Candles, p: dict) -> list[Signal]:
    n = p["length"]
    atr = _atr_stop(c, p)
    out = []
    for i in range(n + 1, len(c.closes)):
        if not _ready(atr[i], atr[i - 1]):
            continue
        now, before = c.closes[i] - c.closes[i - n], c.closes[i - 1] - c.closes[i - 1 - n]
        level, level_before = p["thrust"] * atr[i], p["thrust"] * atr[i - 1]
        stop = atr[i] * p["atr_mult"]
        if now > level and before <= level_before:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif now < -level and before >= -level_before:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 24. MACD zero cross: the MACD line crosses zero on the trend's side.
def _macd_zero(c: Candles, p: dict) -> list[Signal]:
    line, _, _ = ind.macd(c.closes, p["fast"], p["slow"], 9)
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(line[i - 1], line[i], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if line[i - 1] <= 0 < line[i] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif line[i - 1] >= 0 > line[i] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 25. Hull MA turn: the Hull moving average turns up (down) on the trend's side.
def _hma_turn(c: Candles, p: dict) -> list[Signal]:
    h = ind.hma(c.closes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(2, len(c.closes)):
        if not _ready(h[i - 2], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if h[i] > h[i - 1] <= h[i - 2] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif h[i] < h[i - 1] >= h[i - 2] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 26. Parabolic SAR flip on the trend's side. Stop: the SAR line.
def _psar_flip(c: Candles, p: dict) -> list[Signal]:
    line, direction = ind.psar(c.highs, c.lows, p["step"], p["step"], p["maximum"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(2, len(c.closes)):
        if not _ready(line[i], direction[i - 1], trend[i]):
            continue
        if direction[i - 1] == -1 and direction[i] == 1 and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=line[i], reward=p["reward"]))
        elif direction[i - 1] == 1 and direction[i] == -1 and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=line[i], reward=p["reward"]))
    return out


# 27. CCI trend: CCI crosses above +100 (below -100) on the trend's side (Lambert's original use).
def _cci_trend(c: Candles, p: dict) -> list[Signal]:
    cci = ind.cci(c.highs, c.lows, c.closes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(cci[i - 1], cci[i], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if cci[i - 1] <= p["level"] < cci[i] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif cci[i - 1] >= -p["level"] > cci[i] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 28. Aroon cross: Aroon Up crosses above Aroon Down and is strong (mirror for shorts).
def _aroon_cross(c: Candles, p: dict) -> list[Signal]:
    up, down = ind.aroon(c.highs, c.lows, p["length"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(up[i - 1], up[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if _crossed_up(up, down, i) and up[i] >= p["strong"]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif _crossed_down(up, down, i) and down[i] >= p["strong"]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 29. Vortex cross on the trend's side.
def _vortex_cross(c: Candles, p: dict) -> list[Signal]:
    plus, minus = ind.vortex(c.highs, c.lows, c.closes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(plus[i - 1], plus[i], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if _crossed_up(plus, minus, i) and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif _crossed_down(plus, minus, i) and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 30. ADX breakout: a close beyond the last N candles while ADX shows a trend that is getting stronger.
def _adx_breakout(c: Candles, p: dict) -> list[Signal]:
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    adx = ind.adx(c.highs, c.lows, c.closes, 14, 14)
    atr = _atr_stop(c, p)
    out = []
    for i in range(3, len(c.closes)):
        if not _ready(high[i - 1], adx[i], adx[i - 3], atr[i]) or adx[i] < p["min_adx"] or adx[i] <= adx[i - 3]:
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > high[i - 1]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < low[i - 1]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 31. OBV breakout: on-balance volume makes a new N-candle high (low) on the trend's side: the volume leads.
def _obv_breakout(c: Candles, p: dict) -> list[Signal]:
    obv = ind.obv(c.closes, c.volumes)
    high, low = ind.highest(obv, p["length"]), ind.lowest(obv, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(2, len(c.closes)):
        if not _ready(high[i - 2], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if obv[i] > high[i - 1] and obv[i - 1] <= high[i - 2] and c.closes[i] > trend[i] and c.closes[i] > c.opens[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif obv[i] < low[i - 1] and obv[i - 1] >= low[i - 2] and c.closes[i] < trend[i] and c.closes[i] < c.opens[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 32. KAMA cross: the close crosses Kaufman's adaptive average while the move is efficient (not choppy).
def _kama_cross(c: Candles, p: dict) -> list[Signal]:
    k = ind.kama(c.closes, p["length"])
    er = ind.efficiency(c.closes, p["length"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(k[i - 1], k[i], er[i], atr[i]) or er[i] < p["min_er"]:
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i - 1] <= k[i - 1] and c.closes[i] > k[i] and k[i] >= k[i - 1]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i - 1] >= k[i - 1] and c.closes[i] < k[i] and k[i] <= k[i - 1]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 33. Structure break: swing highs and lows (pivots). A close above the last swing high after a higher low
#     is a break of structure upward (mirror for shorts). Stop: beyond the last swing low.
def _structure_break(c: Candles, p: dict) -> list[Signal]:
    w = p["pivot"]
    atr = _atr_stop(c, p)
    out = []
    highs_seen: list[float] = []      # confirmed swing highs, oldest first
    lows_seen: list[float] = []
    used_high = used_low = None
    for i in range(2 * w, len(c.closes)):
        k = i - w                     # the candle that can now be confirmed as a pivot
        if c.highs[k] == max(c.highs[k - w: k + w + 1]):
            highs_seen.append(c.highs[k])
        if c.lows[k] == min(c.lows[k - w: k + w + 1]):
            lows_seen.append(c.lows[k])
        if atr[i] is None or len(highs_seen) < 2 or len(lows_seen) < 2:
            continue
        buf = p["buffer"] * atr[i]
        hi, lo = highs_seen[-1], lows_seen[-1]
        if c.closes[i] > hi and c.closes[i - 1] <= hi and lo > lows_seen[-2] and used_high != hi:
            used_high = hi
            out.append(Signal(i, LONG, stop_price=lo - buf, reward=p["reward"]))
        elif c.closes[i] < lo and c.closes[i - 1] >= lo and hi < highs_seen[-2] and used_low != lo:
            used_low = lo
            out.append(Signal(i, SHORT, stop_price=hi + buf, reward=p["reward"]))
    return out


# 34. NR7 breakout: the narrowest candle of the last 7, then a close beyond it on the trend's side.
def _nr7_breakout(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    n = p["length"]
    for i in range(n + 1, len(c.closes)):
        if not _ready(trend[i], atr[i]):
            continue
        m = i - 1
        rng = c.highs[m] - c.lows[m]
        if any(c.highs[j] - c.lows[j] < rng for j in range(m - n + 1, m)):
            continue
        buf = p["buffer"] * atr[i]
        if c.closes[i] > c.highs[m] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=min(c.lows[m], c.lows[i]) - buf, reward=p["reward"]))
        elif c.closes[i] < c.lows[m] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[m], c.highs[i]) + buf, reward=p["reward"]))
    return out


# 35. Heikin-Ashi turn: after at least `run` red Heikin-Ashi candles a green one with no lower wick, on the
#     trend's side (mirror for shorts).
def _heikin_ashi(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    ha_open = prev_close = None
    reds = greens = 0
    for i in range(len(c.closes)):
        ha_close = (c.opens[i] + c.highs[i] + c.lows[i] + c.closes[i]) / 4
        ha_open = (c.opens[i] + c.closes[i]) / 2 if ha_open is None else (ha_open + prev_close) / 2
        prev_close = ha_close
        green = ha_close > ha_open
        if _ready(trend[i], atr[i]):
            buf = p["buffer"] * atr[i]
            if green and reds >= p["run"] and min(c.lows[i], ha_open) >= ha_open and c.closes[i] > trend[i]:
                out.append(Signal(i, LONG, stop_price=min(c.lows[max(0, i - 2): i + 1]) - buf, reward=p["reward"]))
            elif not green and greens >= p["run"] and max(c.highs[i], ha_open) <= ha_open and c.closes[i] < trend[i]:
                out.append(Signal(i, SHORT, stop_price=max(c.highs[max(0, i - 2): i + 1]) + buf, reward=p["reward"]))
        reds, greens = (0, greens + 1) if green else (reds + 1, 0)
    return out


# 36. Engulfing: a candle whose body swallows the previous opposite candle's body, after a dip, on the
#     trend's side.
def _engulfing(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    rsi = ind.rsi(c.closes, 14)
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(trend[i], rsi[i - 1], atr[i]):
            continue
        buf = p["buffer"] * atr[i]
        o1, c1, o2, c2 = c.opens[i - 1], c.closes[i - 1], c.opens[i], c.closes[i]
        if c1 < o1 and c2 > o2 and c2 >= o1 and o2 <= c1 and rsi[i - 1] < p["dip"] and c2 > trend[i]:
            out.append(Signal(i, LONG, stop_price=min(c.lows[i - 1], c.lows[i]) - buf, reward=p["reward"]))
        elif c1 > o1 and c2 < o2 and c2 <= o1 and o2 >= c1 and rsi[i - 1] > 100 - p["dip"] and c2 < trend[i]:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[i - 1], c.highs[i]) + buf, reward=p["reward"]))
    return out


# 37. Pin bar: a long wick rejecting the low of the last N candles (the wick at least `wick` times the body,
#     the close in the upper third), on the trend's side.
def _pin_bar(c: Candles, p: dict) -> list[Signal]:
    low, high = ind.lowest(c.lows, p["length"]), ind.highest(c.highs, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(low[i], trend[i], atr[i]):
            continue
        rng = c.highs[i] - c.lows[i]
        if rng <= 0:
            continue
        body = abs(c.closes[i] - c.opens[i])
        lower = min(c.opens[i], c.closes[i]) - c.lows[i]
        upper = c.highs[i] - max(c.opens[i], c.closes[i])
        buf = p["buffer"] * atr[i]
        if c.lows[i] <= low[i] and lower >= p["wick"] * body and lower >= 0.6 * rng and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=c.lows[i] - buf, reward=p["reward"]))
        elif c.highs[i] >= high[i] and upper >= p["wick"] * body and upper >= 0.6 * rng and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=c.highs[i] + buf, reward=p["reward"]))
    return out


# 38. RSI(2) dip (Connors): in an uptrend a very short RSI falls to an extreme; buy the dip (mirror for shorts).
def _rsi2_dip(c: Candles, p: dict) -> list[Signal]:
    rsi = ind.rsi(c.closes, p["rsi_length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(rsi[i], rsi[i - 1], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > trend[i] and rsi[i] < p["oversold"] <= rsi[i - 1]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < trend[i] and rsi[i] > 100 - p["oversold"] >= rsi[i - 1]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 39. Williams %R pullback: on the trend's side, %R comes back up out of the oversold zone.
def _williams_pullback(c: Candles, p: dict) -> list[Signal]:
    wr = ind.williams_r(c.highs, c.lows, c.closes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(wr[i], wr[i - 1], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > trend[i] and wr[i - 1] < -p["zone"] <= wr[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < trend[i] and wr[i - 1] > p["zone"] - 100 >= wr[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 40. Z-score reversion: the close is more than `z` standard deviations from its average and turns back,
#     in a quiet market (ADX low). Target: the average.
def _zscore_reversion(c: Candles, p: dict) -> list[Signal]:
    mean, dev = ind.sma(c.closes, p["length"]), ind.stdev(c.closes, p["length"])
    adx = ind.adx(c.highs, c.lows, c.closes, 14, 14)
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(mean[i - 1], dev[i - 1], mean[i], adx[i], atr[i]) or not dev[i - 1] or adx[i] > p["max_adx"]:
            continue
        z_before = (c.closes[i - 1] - mean[i - 1]) / dev[i - 1]
        buf = 0.5 * atr[i]
        if z_before < -p["z"] and c.closes[i] > c.closes[i - 1]:
            out.append(Signal(i, LONG, stop_price=min(c.lows[i - 1], c.lows[i]) - buf, target_price=mean[i]))
        elif z_before > p["z"] and c.closes[i] < c.closes[i - 1]:
            out.append(Signal(i, SHORT, stop_price=max(c.highs[i - 1], c.highs[i]) + buf, target_price=mean[i]))
    return out


# 41. MFI turn: the Money Flow Index comes back out of its oversold zone on the trend's side.
def _mfi_turn(c: Candles, p: dict) -> list[Signal]:
    mfi = ind.mfi(c.highs, c.lows, c.closes, c.volumes, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(mfi[i], mfi[i - 1], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if c.closes[i] > trend[i] and mfi[i - 1] < p["zone"] <= mfi[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif c.closes[i] < trend[i] and mfi[i - 1] > 100 - p["zone"] >= mfi[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 42. Three soldiers: three strong candles in a row the same way, each closing near its end, with growing
#     volume, on the trend's side: the move is expected to go on. Stop: beyond the first of the three.
def _three_soldiers(c: Candles, p: dict) -> list[Signal]:
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(3, len(c.closes)):
        if not _ready(trend[i], atr[i - 3]):
            continue
        ups = downs = True
        for j in (i - 2, i - 1, i):
            rng = c.highs[j] - c.lows[j]
            body = c.closes[j] - c.opens[j]
            if rng <= 0 or abs(body) < 0.6 * rng or abs(body) < p["size"] * atr[i - 3]:
                ups = downs = False
                break
            ups = ups and body > 0
            downs = downs and body < 0
        loud = (c.volumes[i] or 0) > (c.volumes[i - 2] or 0)
        buf = p["buffer"] * atr[i]
        if ups and loud and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=c.lows[i - 2] - buf, reward=p["reward"]))
        elif downs and loud and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=c.highs[i - 2] + buf, reward=p["reward"]))
    return out


# 43. Volatility contraction: the short ATR shrinks well under the long ATR (a tight coil), then a close
#     beyond the coil's high / low on the trend's side.
def _contraction(c: Candles, p: dict) -> list[Signal]:
    short, long_ = ind.atr(c.highs, c.lows, c.closes, 5), ind.atr(c.highs, c.lows, c.closes, 50)
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    trend = ind.ema(c.closes, p["trend"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(short[i - 1], long_[i - 1], high[i - 1], low[i - 1], trend[i]) or not long_[i - 1]:
            continue
        if short[i - 1] > p["tight"] * long_[i - 1]:
            continue
        if c.closes[i] > high[i - 1] and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_price=low[i - 1], reward=p["reward"]))
        elif c.closes[i] < low[i - 1] and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_price=high[i - 1], reward=p["reward"]))
    return out


# 44. Box breakout: the price stays in a narrow box for N candles, then closes out of it on clearly higher
#     volume. Stop: the middle of the box.
def _box_breakout(c: Candles, p: dict) -> list[Signal]:
    n = p["length"]
    high, low = ind.highest(c.highs, n), ind.lowest(c.lows, n)
    atr = ind.atr(c.highs, c.lows, c.closes, 50)
    avg_volume = ind.sma(c.volumes, n)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(high[i - 1], low[i - 1], atr[i - 1], avg_volume[i - 1]) or not avg_volume[i - 1]:
            continue
        top, bottom = high[i - 1], low[i - 1]
        if top - bottom > p["box"] * atr[i - 1] or (c.volumes[i] or 0) < p["volume_mult"] * avg_volume[i - 1]:
            continue
        if c.closes[i] > top:
            out.append(Signal(i, LONG, stop_price=(top + bottom) / 2, reward=p["reward"]))
        elif c.closes[i] < bottom:
            out.append(Signal(i, SHORT, stop_price=(top + bottom) / 2, reward=p["reward"]))
    return out


# 45. TRIX cross: TRIX crosses its signal line on the right side of zero, on the trend's side.
def _trix_cross(c: Candles, p: dict) -> list[Signal]:
    line = ind.trix(c.closes, p["length"])
    signal = ind.ema(line, p["signal"])
    trend = ind.ema(c.closes, p["trend"])
    atr = _atr_stop(c, p)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(signal[i - 1], signal[i], trend[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        if _crossed_up(line, signal, i) and c.closes[i] > trend[i]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif _crossed_down(line, signal, i) and c.closes[i] < trend[i]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


# 46. Trend day: a very large candle (at least `size` ATRs) that closes near its end on higher volume,
#     breaking the last N candles: big moves tend to go on (momentum ignition).
def _wide_bar(c: Candles, p: dict) -> list[Signal]:
    high, low = ind.highest(c.highs, p["length"]), ind.lowest(c.lows, p["length"])
    atr = _atr_stop(c, p)
    avg_volume = ind.sma(c.volumes, 20)
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(high[i - 1], low[i - 1], atr[i - 1], avg_volume[i - 1]):
            continue
        rng = c.highs[i] - c.lows[i]
        if rng < p["size"] * atr[i - 1] or (c.volumes[i] or 0) < 1.5 * avg_volume[i - 1]:
            continue
        mid = (c.highs[i] + c.lows[i]) / 2
        if c.closes[i] > high[i - 1] and c.closes[i] >= c.highs[i] - 0.25 * rng:
            out.append(Signal(i, LONG, stop_price=mid, reward=p["reward"]))
        elif c.closes[i] < low[i - 1] and c.closes[i] <= c.lows[i] + 0.25 * rng:
            out.append(Signal(i, SHORT, stop_price=mid, reward=p["reward"]))
    return out


# 47. Trend Rider (2026-11-11, the bot's own engine: docs/RESEARCH-2026-11-11.md, part 2). The trend score is
#     the average of five channel states: for the last N, 2N, 4N, 8N and 16N candles, +1 after a close at the
#     highest close of that window, -1 after a close at the lowest, until the other happens. +1 = every window
#     says up. As a card (history table, other modes) it enters when the score rises to `enter` and uses a fixed
#     target; in the bot's rider mode there is no target: the trade ends when the score falls to zero.
TREND_STEPS = (1, 2, 4, 8, 16)


def trend_score(closes: list[float], base: int) -> list[Optional[float]]:
    n = len(closes)
    total = [0.0] * n
    for step in TREND_STEPS:
        high, low = ind.highest(closes, base * step), ind.lowest(closes, base * step)
        state = 0
        for i in range(n):
            if high[i] is not None:
                if closes[i] >= high[i]:
                    state = 1
                elif closes[i] <= low[i]:
                    state = -1
            total[i] += state / len(TREND_STEPS)
    first = base * TREND_STEPS[-1] - 1     # the longest window must be full
    return [None if i < first else total[i] for i in range(n)]


def _trend_rider(c: Candles, p: dict) -> list[Signal]:
    score = trend_score(c.closes, p["length"])
    atr = ind.atr(c.highs, c.lows, c.closes, p["atr_length"])
    out = []
    for i in range(1, len(c.closes)):
        if not _ready(score[i - 1], score[i], atr[i]):
            continue
        stop = atr[i] * p["atr_mult"]
        edge = p["enter"] - 1e-9
        if score[i] >= edge > score[i - 1]:
            out.append(Signal(i, LONG, stop_distance=stop, reward=p["reward"]))
        elif score[i] <= -edge < score[i - 1]:
            out.append(Signal(i, SHORT, stop_distance=stop, reward=p["reward"]))
    return out


def _ema_line(n, iid="trend") -> dict:
    return {"id": f"s-{iid}", "type": "ema", "params": {"length": n}}


_STRATEGIES = [
    Strategy("ema_cross", "EMA Cross", ("trend_up", "trend_down"), ("EMA", "ATR"),
             (Param("fast", 9, 1, 500), Param("slow", 21, 1, 500), TREND, ATR_LENGTH, _atr_mult(1.5), _reward(2)),
             _ema_cross,
             lambda p: [_ema_line(p["fast"], "fast"), _ema_line(p["slow"], "slow"), _ema_line(p["trend"])]),
    Strategy("macd_ema", "MACD + EMA", ("trend_up", "trend_down"), ("MACD", "EMA"),
             (Param("fast", 12, 1, 500), Param("slow", 26, 1, 500), Param("signal", 9, 1, 500), TREND,
              Param("swing", 10, 2, 100), _reward(1.5)),
             _macd_ema,
             lambda p: [_ema_line(p["trend"]),
                        {"id": "s-macd", "type": "macd",
                         "params": {"fast": p["fast"], "slow": p["slow"], "signal": p["signal"]}}]),
    Strategy("rsi_pullback", "RSI Pullback", ("trend_up", "trend_down"), ("RSI", "EMA", "ATR"),
             (Param("rsi_length", 14, 2, 500), Param("oversold", 40, 1, 99), Param("overbought", 60, 1, 99),
              TREND, ATR_LENGTH, _atr_mult(1.5), _reward(2)),
             _rsi_pullback,
             lambda p: [_ema_line(p["trend"]), {"id": "s-rsi", "type": "rsi", "params": {"length": p["rsi_length"]}}]),
    Strategy("bb_reversion", "Bollinger Reversion", ("range",), ("BB",),
             (Param("length", 20, 2, 500), Param("mult", 2, 0.1, 10, 0.1)),
             _bb_reversion,
             lambda p: [{"id": "s-bb", "type": "bb", "params": {"length": p["length"], "mult": p["mult"]}}]),
    Strategy("supertrend", "SuperTrend", ("trend_up", "trend_down"), ("SuperTrend", "EMA"),
             (Param("atr_length", 10, 1, 500), Param("factor", 3, 0.1, 20, 0.1), TREND, _reward(2)),
             _supertrend,
             lambda p: [_ema_line(p["trend"]),
                        {"id": "s-st", "type": "supertrend",
                         "params": {"atr_length": p["atr_length"], "factor": p["factor"]}}]),
    Strategy("donchian", "Channel Breakout", ("range", "volatile"), ("Donchian", "ATR"),
             (Param("length", 20, 2, 500), ATR_LENGTH, _atr_mult(2), _reward(2)),
             _donchian),
    Strategy("liquidity_sweep", "Liquidity Sweep", ("trend_up", "trend_down", "range", "volatile"), ("Price action", "ATR"),
             (Param("length", 20, 2, 500), BUFFER, _reward(2)),
             _liquidity_sweep),
    Strategy("fvg_retest", "FVG Retest", ("trend_up", "trend_down"), ("Price action", "EMA"),
             (TREND, MAX_WAIT, BUFFER, _reward(2)),
             _fvg_retest,
             lambda p: [_ema_line(p["trend"])]),
    Strategy("order_block", "Order Block", ("trend_up", "trend_down"), ("Price action", "EMA"),
             (Param("swing", 10, 2, 200), TREND, MAX_WAIT, BUFFER, _reward(2)),
             _order_block,
             lambda p: [_ema_line(p["trend"])]),
    Strategy("sd_zone", "Supply & Demand (RTM)", ("trend_up", "trend_down", "range", "volatile"), ("Price action", "ATR"),
             (Param("leg", 2, 0.5, 10, 0.1), Param("max_wait", 50, 1, 500), BUFFER, _reward(2)),
             _sd_zone),
    Strategy("squeeze", "Squeeze Breakout", ("range", "volatile"), ("BB", "Keltner", "ATR"),
             (Param("length", 20, 2, 500), Param("kc_mult", 1.5, 0.1, 10, 0.1), Param("min_quiet", 5, 1, 200),
              _atr_mult(1.5), _reward(2)),
             _squeeze,
             lambda p: [{"id": "s-bb", "type": "bb", "params": {"length": p["length"], "mult": 2}}]),
    Strategy("vwap_reversion", "VWAP Reversion", ("range",), ("VWAP", "ATR"),
             (Param("length", 96, 5, 2000), Param("band", 2, 0.5, 10, 0.1)),
             _vwap_reversion),
    Strategy("ema_pullback", "EMA Pullback", ("trend_up", "trend_down"), ("EMA", "ATR"),
             (Param("fast", 20, 1, 500), Param("slow", 50, 1, 500), TREND, BUFFER, _reward(2)),
             _ema_pullback,
             lambda p: [_ema_line(p["fast"], "fast"), _ema_line(p["slow"], "slow"), _ema_line(p["trend"])]),
    Strategy("dmi_adx", "DMI + ADX", ("trend_up", "trend_down", "volatile"), ("DMI", "ADX", "ATR"),
             (Param("length", 14, 2, 200), Param("min_adx", 20, 5, 80), _atr_mult(2), _reward(2.5)),
             _dmi_adx),
    Strategy("ichimoku", "Ichimoku Cloud", ("trend_up", "trend_down"), ("Ichimoku", "ATR"),
             (Param("tenkan", 9, 2, 200), Param("kijun", 26, 2, 300), Param("span_b", 52, 2, 500), _reward(2)),
             _ichimoku),
    Strategy("inside_bar", "Inside Bar Breakout", ("trend_up", "trend_down", "volatile"), ("Price action", "EMA"),
             (TREND, _reward(2)),
             _inside_bar,
             lambda p: [_ema_line(p["trend"])]),
    Strategy("stoch_rsi_trend", "Stoch RSI Pullback", ("trend_up", "trend_down"), ("Stoch RSI", "EMA", "ATR"),
             (Param("rsi_length", 14, 2, 200), Param("oversold", 20, 1, 99), Param("overbought", 80, 1, 99),
              TREND, _atr_mult(1.5), _reward(2)),
             _stoch_rsi_trend,
             lambda p: [_ema_line(p["trend"])]),
    Strategy("volume_breakout", "Volume Breakout", ("trend_up", "trend_down", "volatile"), ("Keltner", "Volume", "EMA"),
             (Param("length", 20, 2, 500), Param("kc_mult", 2, 0.1, 10, 0.1), Param("volume_mult", 2, 1, 10, 0.1),
              TREND, _reward(2)),
             _volume_breakout,
             lambda p: [_ema_line(p["length"], "mid"), _ema_line(p["trend"])]),
    # ---- second set (2026-11-11) ----
    Strategy("turtle", "Turtle Breakout", ("trend_up", "trend_down", "volatile"), ("Donchian", "EMA", "ATR"),
             (Param("length", 55, 2, 500), TREND, _atr_mult(2), _reward(3)),
             _turtle, lambda p: [_ema_line(p["trend"])]),
    Strategy("keltner_breakout", "Keltner Breakout", ("trend_up", "trend_down", "volatile"), ("Keltner", "EMA"),
             (Param("length", 20, 2, 500), Param("kc_mult", 2, 0.1, 10, 0.1), TREND, _reward(2)),
             _keltner_breakout, lambda p: [_ema_line(p["length"], "mid"), _ema_line(p["trend"])]),
    Strategy("bb_breakout", "Bollinger Breakout", ("trend_up", "trend_down", "volatile"), ("BB", "EMA"),
             (Param("length", 20, 2, 500), Param("mult", 2, 0.1, 10, 0.1), TREND, _reward(2)),
             _bb_breakout,
             lambda p: [_ema_line(p["trend"]), {"id": "s-bb", "type": "bb", "params": {"length": p["length"], "mult": p["mult"]}}]),
    Strategy("ema_ribbon", "EMA Ribbon", ("trend_up", "trend_down"), ("EMA", "ATR"),
             (Param("fast", 8, 1, 500), Param("mid", 21, 1, 500), Param("slow", 55, 1, 500), TREND, _atr_mult(2), _reward(2)),
             _ema_ribbon,
             lambda p: [_ema_line(p["fast"], "fast"), _ema_line(p["mid"], "mid"), _ema_line(p["slow"], "slow"), _ema_line(p["trend"])]),
    Strategy("momentum", "Momentum Thrust", ("trend_up", "trend_down", "volatile"), ("Momentum", "ATR"),
             (Param("length", 20, 2, 500), Param("thrust", 4, 0.5, 20, 0.5), _atr_mult(2), _reward(2)),
             _momentum),
    Strategy("macd_zero", "MACD Zero Cross", ("trend_up", "trend_down"), ("MACD", "EMA", "ATR"),
             (Param("fast", 12, 1, 500), Param("slow", 26, 1, 500), TREND, _atr_mult(2), _reward(2)),
             _macd_zero,
             lambda p: [_ema_line(p["trend"]), {"id": "s-macd", "type": "macd", "params": {"fast": p["fast"], "slow": p["slow"], "signal": 9}}]),
    Strategy("hma_turn", "Hull MA Turn", ("trend_up", "trend_down"), ("HMA", "EMA", "ATR"),
             (Param("length", 55, 2, 500), TREND, _atr_mult(2), _reward(2)),
             _hma_turn, lambda p: [_ema_line(p["trend"])]),
    Strategy("psar_flip", "Parabolic SAR Flip", ("trend_up", "trend_down"), ("PSAR", "EMA"),
             (Param("step", 0.02, 0.001, 0.2, 0.001), Param("maximum", 0.2, 0.01, 1, 0.01), TREND, _reward(2)),
             _psar_flip, lambda p: [_ema_line(p["trend"])]),
    Strategy("cci_trend", "CCI Trend", ("trend_up", "trend_down", "volatile"), ("CCI", "EMA", "ATR"),
             (Param("length", 20, 2, 500), Param("level", 100, 10, 400), TREND, _atr_mult(2), _reward(2)),
             _cci_trend, lambda p: [_ema_line(p["trend"])]),
    Strategy("aroon_cross", "Aroon Cross", ("trend_up", "trend_down", "range", "volatile"), ("Aroon", "ATR"),
             (Param("length", 25, 2, 500), Param("strong", 70, 0, 100), _atr_mult(2), _reward(2)),
             _aroon_cross),
    Strategy("vortex_cross", "Vortex Cross", ("trend_up", "trend_down"), ("Vortex", "EMA", "ATR"),
             (Param("length", 14, 2, 500), TREND, _atr_mult(2), _reward(2)),
             _vortex_cross, lambda p: [_ema_line(p["trend"])]),
    Strategy("adx_breakout", "ADX Breakout", ("trend_up", "trend_down", "volatile"), ("Donchian", "ADX", "ATR"),
             (Param("length", 20, 2, 500), Param("min_adx", 25, 5, 80), _atr_mult(2), _reward(2)),
             _adx_breakout),
    Strategy("obv_breakout", "OBV Breakout", ("trend_up", "trend_down", "volatile"), ("OBV", "EMA", "ATR"),
             (Param("length", 50, 2, 500), TREND, _atr_mult(2), _reward(2)),
             _obv_breakout, lambda p: [_ema_line(p["trend"])]),
    Strategy("kama_cross", "KAMA Cross", ("trend_up", "trend_down", "volatile"), ("KAMA", "ATR"),
             (Param("length", 10, 2, 500), Param("min_er", 0.3, 0, 1, 0.05), _atr_mult(2), _reward(2)),
             _kama_cross),
    Strategy("structure_break", "Structure Break (BOS)", ("trend_up", "trend_down", "range", "volatile"), ("Price action", "ATR"),
             (Param("pivot", 5, 1, 50), BUFFER, _reward(2)),
             _structure_break),
    Strategy("nr7_breakout", "NR7 Breakout", ("trend_up", "trend_down", "range"), ("Price action", "EMA"),
             (Param("length", 7, 2, 50), TREND, BUFFER, _reward(2)),
             _nr7_breakout, lambda p: [_ema_line(p["trend"])]),
    Strategy("heikin_ashi", "Heikin-Ashi Turn", ("trend_up", "trend_down"), ("Heikin-Ashi", "EMA"),
             (Param("run", 3, 1, 20), TREND, BUFFER, _reward(2)),
             _heikin_ashi, lambda p: [_ema_line(p["trend"])]),
    Strategy("engulfing", "Engulfing", ("trend_up", "trend_down"), ("Price action", "RSI", "EMA"),
             (Param("dip", 45, 1, 99), TREND, BUFFER, _reward(2)),
             _engulfing, lambda p: [_ema_line(p["trend"])]),
    Strategy("pin_bar", "Pin Bar", ("trend_up", "trend_down", "range"), ("Price action", "EMA"),
             (Param("length", 10, 2, 200), Param("wick", 2, 1, 10, 0.5), TREND, BUFFER, _reward(2)),
             _pin_bar, lambda p: [_ema_line(p["trend"])]),
    Strategy("rsi2_dip", "RSI(2) Dip", ("trend_up", "trend_down"), ("RSI", "EMA", "ATR"),
             (Param("rsi_length", 2, 2, 50), Param("oversold", 10, 1, 49), TREND, _atr_mult(2.5), _reward(1.5)),
             _rsi2_dip, lambda p: [_ema_line(p["trend"])]),
    Strategy("williams_pullback", "Williams %R Pullback", ("trend_up", "trend_down"), ("Williams %R", "EMA", "ATR"),
             (Param("length", 14, 2, 500), Param("zone", 80, 50, 99), TREND, _atr_mult(1.5), _reward(2)),
             _williams_pullback, lambda p: [_ema_line(p["trend"])]),
    Strategy("zscore_reversion", "Z-Score Reversion", ("range",), ("SMA", "StDev", "ADX"),
             (Param("length", 50, 5, 500), Param("z", 2.5, 0.5, 6, 0.1), Param("max_adx", 20, 5, 80)),
             _zscore_reversion),
    Strategy("mfi_turn", "MFI Turn", ("trend_up", "trend_down"), ("MFI", "EMA", "ATR"),
             (Param("length", 14, 2, 500), Param("zone", 20, 1, 49), TREND, _atr_mult(1.5), _reward(2)),
             _mfi_turn, lambda p: [_ema_line(p["trend"])]),
    Strategy("three_soldiers", "Three Soldiers", ("trend_up", "trend_down", "volatile"), ("Price action", "Volume", "EMA"),
             (Param("size", 0.5, 0.1, 5, 0.1), TREND, BUFFER, _reward(2)),
             _three_soldiers, lambda p: [_ema_line(p["trend"])]),
    Strategy("contraction", "Volatility Contraction", ("trend_up", "trend_down", "range"), ("ATR", "Donchian", "EMA"),
             (Param("length", 10, 2, 200), Param("tight", 0.7, 0.1, 1, 0.05), TREND, _reward(2)),
             _contraction, lambda p: [_ema_line(p["trend"])]),
    Strategy("box_breakout", "Box Breakout", ("range", "volatile"), ("Price action", "Volume", "ATR"),
             (Param("length", 20, 5, 500), Param("box", 4, 0.5, 20, 0.5), Param("volume_mult", 1.5, 1, 10, 0.1), _reward(2)),
             _box_breakout),
    Strategy("trix_cross", "TRIX Cross", ("trend_up", "trend_down"), ("TRIX", "EMA", "ATR"),
             (Param("length", 15, 2, 200), Param("signal", 9, 2, 100), TREND, _atr_mult(2), _reward(2)),
             _trix_cross, lambda p: [_ema_line(p["trend"])]),
    Strategy("wide_bar", "Wide-Range Bar", ("trend_up", "trend_down", "range", "volatile"), ("Price action", "Volume", "ATR"),
             (Param("length", 20, 2, 500), Param("size", 2.5, 1, 10, 0.1), _reward(2)),
             _wide_bar),
    Strategy("trend_rider", "Trend Rider", ("trend_up", "trend_down", "range", "volatile"), ("Donchian", "ATR"),
             (Param("length", 30, 2, 200), Param("enter", 0.6, 0.2, 1, 0.2), Param("atr_length", 84, 1, 500),
              _atr_mult(4), _reward(4)),
             _trend_rider),
]

STRATEGIES: dict[str, Strategy] = {s.type: s for s in _STRATEGIES}


def public_strategies() -> list[dict]:
    return [s.public() for s in _STRATEGIES]


def parse_params(kind: str, given, trading_mode: str = "daily") -> dict:
    """Fill in defaults and check ranges. The trend EMA defaults to the
    trading mode's long EMA (scalping 50, daily 200)."""
    strategy = STRATEGIES.get(kind)
    if strategy is None:
        raise ValueError(f"unknown strategy: {kind}")
    given = given or {}
    if not isinstance(given, dict):
        raise ValueError("params must be an object")
    unknown = set(given) - {p.name for p in strategy.all_params}
    if unknown:
        raise ValueError(f"{kind}: unknown setting {sorted(unknown)[0]}")
    out = {}
    for p in strategy.all_params:
        default = LONG_EMA.get(trading_mode, p.default) if p.name == "trend" else p.default
        value = given.get(p.name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{kind}: {p.name} must be a number")
        if p.step == 1 and value != int(value):
            raise ValueError(f"{kind}: {p.name} must be a whole number")
        if not p.min <= value <= p.max:
            raise ValueError(f"{kind}: {p.name} must be between {p.min:g} and {p.max:g}")
        out[p.name] = int(value) if p.step == 1 else float(value)
    return out


def _levels(sig: Signal, entry: float) -> Optional[tuple[float, float]]:
    """Stop-loss and take-profit for an entry price, or None if they make no sense
    (stop on the wrong side of the entry, or target not beyond it)."""
    direction = 1 if sig.side == LONG else -1
    stop = sig.stop_price if sig.stop_price is not None else entry - direction * (sig.stop_distance or 0)
    risk = (entry - stop) * direction
    if risk <= 0:
        return None
    target = sig.target_price if sig.target_price is not None else entry + direction * risk * (sig.reward or 0)
    if (target - entry) * direction <= 0:
        return None
    return stop, target


def allowed_by_state(sig: Signal, state: str, suited: tuple[str, ...]) -> bool:
    """Market-state rule: the state must suit the strategy, and in a trend
    only trades in the trend's direction are taken."""
    if state not in suited:
        return False
    if state == "trend_up":
        return sig.side == LONG
    if state == "trend_down":
        return sig.side == SHORT
    return True


@dataclass(frozen=True)
class Fees:
    """Fee rates in percent of the order's value, e.g. taker 0.1 = 0.1%."""
    maker: float = 0.0
    taker: float = 0.0


NO_FEES = Fees()


def breakeven_price(side: str, entry: float, fees: Fees, entry_fee: Optional[float] = None) -> float:
    """Exit price where the result after the entry fee and a taker exit fee is zero.
    entry_fee: the entry's fee rate in percent (a limit entry pays maker); default taker.

    long:  (S - E) - fin*E - fout*S = 0  ->  S = E (1 + fin) / (1 - fout)
    short: (E - S) - fin*E - fout*S = 0  ->  S = E (1 - fin) / (1 + fout)
    """
    fin = (fees.taker if entry_fee is None else entry_fee) / 100
    fout = fees.taker / 100
    if side == LONG:
        return entry * (1 + fin) / (1 - fout)
    return entry * (1 - fin) / (1 + fout)


def net_percent(side: str, entry: float, exit_: float, exit_fee: float, fees: Fees) -> float:
    """Result in percent of the entry value, after the entry fee (taker) and the exit fee."""
    direction = 1 if side == LONG else -1
    move = (exit_ - entry) * direction
    paid = entry * fees.taker / 100 + exit_ * exit_fee / 100
    return (move - paid) / entry * 100


def fee_ok(entry: float, stop: float, fees: Fees, ratio: float) -> bool:
    """Fee-vs-risk rule: the round-trip fee (taker in and out) may take at most
    `ratio` of the distance to the stop. 0 turns the rule off."""
    if not ratio:
        return True
    risk = abs(entry - stop) / entry * 100
    return 2 * fees.taker <= ratio * risk


def reward_risk(entry: float, stop: float, target: float, fees: Fees = NO_FEES) -> float:
    """What a trade can win for what it can lose, after the taker fee in and out."""
    fee = entry * fees.taker / 100 + target * fees.taker / 100
    reward = abs(target - entry) - fee
    risk = abs(entry - stop) + entry * fees.taker / 100 + stop * fees.taker / 100
    return reward / risk if risk > 0 else 0.0


def reward_ok(entry: float, stop: float, target: float, fees: Fees = NO_FEES,
              minimum: Optional[float] = None) -> bool:
    """The reward-to-risk rule (config.MIN_REWARD_RISK unless another minimum is given; 0 = off)."""
    minimum = config.MIN_REWARD_RISK if minimum is None else minimum
    return not minimum or reward_risk(entry, stop, target, fees) >= minimum - 1e-9


def simulate(
    candles: list[dict],
    signals: list[Signal],
    breakeven: float = 0,
    max_candles: int = 0,
    fees: Fees = NO_FEES,
    fee_ratio: float = 0,
    min_reward: Optional[float] = None,
) -> tuple[list[dict], Optional[str]]:
    """Walk the candles and turn signals into trades under the common rules.

    Returns the trades and the side of a signal on the last candle (the trade
    that would open at the next candle), if any.
    """
    by_index = {s.index: s for s in signals}
    trades: list[dict] = []
    pos: Optional[dict] = None
    n = len(candles)
    for i in range(n):
        c = candles[i]
        # Enter at this candle's open if the previous closed candle gave a signal.
        sig = by_index.get(i - 1)
        if pos is None and sig is not None:
            levels = _levels(sig, c["open"])
            if (levels is not None and fee_ok(c["open"], levels[0], fees, fee_ratio)
                    and reward_ok(c["open"], levels[0], levels[1], fees, min_reward)):
                pos = {"side": sig.side, "entryTime": c["time"], "entryPrice": c["open"],
                       "stopLoss": levels[0], "takeProfit": levels[1], "signalTime": candles[i - 1]["time"],
                       "breakevenTime": None, "_stop": levels[0], "_entryIndex": i}
        if pos is None:
            continue
        long_ = pos["side"] == LONG
        stop = pos["_stop"]
        hit_stop = c["low"] <= stop if long_ else c["high"] >= stop
        hit_target = c["high"] >= pos["takeProfit"] if long_ else c["low"] <= pos["takeProfit"]
        if hit_stop:
            # A gap past the stop fills at the open (worse than the stop).
            gapped = c["open"] < stop if long_ else c["open"] > stop
            reason = "breakeven" if pos["breakevenTime"] is not None else "stop"
            trades.append(_close(pos, c["time"], c["open"] if gapped else stop, reason, fees))
            pos = None
            continue
        if hit_target:
            trades.append(_close(pos, c["time"], pos["takeProfit"], "target", fees))
            pos = None
            continue
        # Time limit: close a trade that is in profit (after fees) at this candle's close.
        held = i - pos["_entryIndex"] + 1
        in_profit = net_percent(pos["side"], pos["entryPrice"], c["close"], fees.taker, fees) > 0
        if max_candles and held >= max_candles and in_profit:
            trades.append(_close(pos, c["time"], c["close"], "time", fees))
            pos = None
            continue
        # Break-even: from the next candle on, the stop sits at the break-even price.
        if breakeven and pos["breakevenTime"] is None:
            trigger = pos["entryPrice"] + (pos["takeProfit"] - pos["entryPrice"]) * breakeven
            level = breakeven_price(pos["side"], pos["entryPrice"], fees)
            # Only when it is still between the entry and the take-profit (fees can be larger than the move).
            if (level < pos["takeProfit"]) if long_ else (level > pos["takeProfit"]):
                if (c["high"] >= trigger) if long_ else (c["low"] <= trigger):
                    pos["_stop"] = level
                    pos["breakevenTime"] = c["time"]
    if pos is not None:
        trades.append({**_public(pos), "exitTime": None, "exitPrice": None, "exitReason": None,
                       "result": "open", "pnlPercent": None, "grossPercent": None, "feePercent": None, "r": None})
    last = by_index.get(n - 1)
    pending = last.side if last is not None and pos is None else None
    return trades, pending


def _public(pos: dict) -> dict:
    return {k: v for k, v in pos.items() if not k.startswith("_")}


def _close(pos: dict, time: int, price: float, reason: str, fees: Fees = NO_FEES) -> dict:
    direction = 1 if pos["side"] == LONG else -1
    entry = pos["entryPrice"]
    exit_fee = fees.maker if reason == "target" else fees.taker  # take-profit waits as a limit order
    gross = (price - entry) * direction / entry * 100
    net = net_percent(pos["side"], entry, price, exit_fee, fees)
    if abs(net) < 1e-9:
        net = 0.0
    risk = abs(entry - pos["stopLoss"])
    result = "win" if net > 0 else "loss" if net < 0 else "breakeven"
    return {**_public(pos), "exitTime": time, "exitPrice": price, "exitReason": reason,
            "result": result,
            "grossPercent": gross,
            "feePercent": gross - net,
            "pnlPercent": net,
            "r": net / 100 * entry / risk}


def stats(trades: list[dict]) -> dict:
    """Summary without fees: count, win rate, profit factor, total %."""
    closed = [t for t in trades if t["result"] != "open"]
    wins = [t["pnlPercent"] for t in closed if t["result"] == "win"]
    losses = [t["pnlPercent"] for t in closed if t["result"] == "loss"]
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(closed) - len(wins) - len(losses),
        "open": len(trades) - len(closed),
        "winRate": len(wins) / len(closed) * 100 if closed else None,
        # None when there is no loss yet (profit factor would be infinite).
        "profitFactor": gross_win / gross_loss if gross_loss > 0 else None,
        "netPercent": sum(wins) + sum(losses),
        "feePercent": sum(t.get("feePercent") or 0 for t in closed),
        "feesIncluded": any(t.get("feePercent") for t in closed),
    }


def run(candles: list[dict], kind: str, params: dict, states: Optional[list[str]] = None,
        fees: Fees = NO_FEES) -> dict:
    """Run one strategy over closed candles. `states` is the market state of
    every candle (needed when the market-state rule is on)."""
    strategy = STRATEGIES[kind]
    data = Candles(
        opens=[c["open"] for c in candles],
        highs=[c["high"] for c in candles],
        lows=[c["low"] for c in candles],
        closes=[c["close"] for c in candles],
        volumes=[c.get("volume", 0.0) for c in candles],
    )
    signals = strategy.signals(data, params)
    if params.get("state_filter") and states is not None:
        signals = [sig for sig in signals if allowed_by_state(sig, states[sig.index], strategy.states)]
    fee_ratio = params.get("fee_ratio", 0)
    trades, pending = simulate(candles, signals, params.get("breakeven", 0), int(params.get("max_candles", 0)),
                               fees, fee_ratio)
    # A signal on the last closed candle: the trade the bot would open at the next candle.
    signal = None
    if pending is not None:
        sig = signals[-1]
        entry = candles[-1]["close"]  # the next candle opens at (about) this price
        levels = _levels(sig, entry)
        if (levels is not None and fee_ok(entry, levels[0], fees, fee_ratio)
                and reward_ok(entry, levels[0], levels[1], fees)):
            step = candles[-1]["time"] - candles[-2]["time"] if len(candles) > 1 else 0
            signal = {"side": sig.side, "time": candles[-1]["time"], "entry": entry,
                      "stopLoss": levels[0], "takeProfit": levels[1],
                      # The signal is certain once its candle has closed; the trade opens then.
                      "confirmedAt": candles[-1]["time"] + step}
    return {
        "strategy": kind,
        "name": strategy.name,
        "params": params,
        "trades": trades,
        "stats": stats(trades),
        "nextSignal": pending,
        "signal": signal,
        "lines": strategy.lines(params),
    }


# ---------- automatic choice (the owner's two rules) ----------

RULES = ("cautious", "max_profit")
MIN_TRADES = 10  # cautious rule: fewer trades than this is mostly luck


def choose(rows: list[dict], market_state: str, rule: str) -> Optional[dict]:
    """Pick the strategy the bot uses, from the table's rows (strategy + stats).

    cautious:   suits the current market state, at least MIN_TRADES trades and
                profit factor above 1; the best profit factor wins.
    max_profit: the highest total result, with no other condition.
    Either way nothing is picked when no strategy made a profit.
    """
    if rule not in RULES:
        raise ValueError(f"rule must be one of {list(RULES)}")
    best = None
    best_key = None
    for row in rows:
        s = row["stats"]
        if s["trades"] == 0 or s["netPercent"] <= 0:
            continue
        if rule == "cautious":
            pf = s["profitFactor"] if s["profitFactor"] is not None else float("inf")  # no loss at all
            if market_state not in STRATEGIES[row["strategy"]].states or s["trades"] < MIN_TRADES or pf <= 1:
                continue
            key = (pf, s["trades"])
        else:
            key = (s["netPercent"], s["trades"])
        if best_key is None or key > best_key:
            best, best_key = row, key
    if best is None:
        return None
    return {"strategy": best["strategy"], "profitFactor": best["stats"]["profitFactor"],
            "trades": best["stats"]["trades"], "netPercent": best["stats"]["netPercent"]}
