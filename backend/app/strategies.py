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


def breakeven_price(side: str, entry: float, fees: Fees) -> float:
    """Exit price where the result after the entry fee and a taker exit fee is zero.

    long:  (S - E) - fin*E - fout*S = 0  ->  S = E (1 + fin) / (1 - fout)
    short: (E - S) - fin*E - fout*S = 0  ->  S = E (1 - fin) / (1 + fout)
    """
    fin = fout = fees.taker / 100
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


def simulate(
    candles: list[dict],
    signals: list[Signal],
    breakeven: float = 0,
    max_candles: int = 0,
    fees: Fees = NO_FEES,
    fee_ratio: float = 0,
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
            if levels is not None and fee_ok(c["open"], levels[0], fees, fee_ratio):
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
        if levels is not None and fee_ok(entry, levels[0], fees, fee_ratio):
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
