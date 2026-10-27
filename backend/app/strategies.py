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
- Results are without fees for now (fees come in phase 3).

Three extra rules, each with an on/off setting on every strategy (owner's choice):
- Market state: trade only when the market is in a state the strategy suits;
  trend strategies trade only with the trend (long in an uptrend, short in a downtrend).
- Break-even: once the price has gone part of the way to the take-profit
  (half by default), the stop-loss moves to the entry price.
- Time limit: after N candles, a trade that is in profit is closed at the
  candle's close. A trade in loss is not forced out (that would lock in the loss).

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
    Param("max_candles", 48, 0, 1000),        # candles before a trade in profit is closed
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


def simulate(
    candles: list[dict],
    signals: list[Signal],
    breakeven: float = 0,
    max_candles: int = 0,
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
            if levels is not None:
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
            trades.append(_close(pos, c["time"], c["open"] if gapped else stop, reason))
            pos = None
            continue
        if hit_target:
            trades.append(_close(pos, c["time"], pos["takeProfit"], "target"))
            pos = None
            continue
        # Time limit: close a trade that is in profit at this candle's close.
        held = i - pos["_entryIndex"] + 1
        in_profit = c["close"] > pos["entryPrice"] if long_ else c["close"] < pos["entryPrice"]
        if max_candles and held >= max_candles and in_profit:
            trades.append(_close(pos, c["time"], c["close"], "time"))
            pos = None
            continue
        # Break-even: from the next candle on, the stop sits at the entry price.
        if breakeven and pos["breakevenTime"] is None:
            trigger = pos["entryPrice"] + (pos["takeProfit"] - pos["entryPrice"]) * breakeven
            if (c["high"] >= trigger) if long_ else (c["low"] <= trigger):
                pos["_stop"] = pos["entryPrice"]
                pos["breakevenTime"] = c["time"]
    if pos is not None:
        trades.append({**_public(pos), "exitTime": None, "exitPrice": None, "exitReason": None,
                       "result": "open", "pnlPercent": None, "r": None})
    last = by_index.get(n - 1)
    pending = last.side if last is not None and pos is None else None
    return trades, pending


def _public(pos: dict) -> dict:
    return {k: v for k, v in pos.items() if not k.startswith("_")}


def _close(pos: dict, time: int, price: float, reason: str) -> dict:
    direction = 1 if pos["side"] == LONG else -1
    move = (price - pos["entryPrice"]) * direction
    risk = abs(pos["entryPrice"] - pos["stopLoss"])
    result = "win" if move > 0 else "loss" if move < 0 else "breakeven"
    return {**_public(pos), "exitTime": time, "exitPrice": price, "exitReason": reason,
            "result": result,
            "pnlPercent": move / pos["entryPrice"] * 100,
            "r": move / risk}


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
        "feesIncluded": False,
    }


def run(candles: list[dict], kind: str, params: dict, states: Optional[list[str]] = None) -> dict:
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
    trades, pending = simulate(candles, signals, params.get("breakeven", 0), int(params.get("max_candles", 0)))
    return {
        "strategy": kind,
        "name": strategy.name,
        "params": params,
        "trades": trades,
        "stats": stats(trades),
        "nextSignal": pending,
        "lines": strategy.lines(params),
    }
