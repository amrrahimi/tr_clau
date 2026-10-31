"""Experiments on the candle history (owner's questions), run in the live check.

compare_exits: the same signals of every strategy, closed in different ways:
- be0 / be50 / be80: break-even off, at 50% or at 80% of the way to the target;
- cap: close as soon as the trade is CAP_R risk-units in profit after fees
  (the owner's "close every position at +$0.1" with $1 risk per trade).
Results are in R (multiples of the risk) after fees, so all coins add up fairly.
"""

from __future__ import annotations

from dataclasses import replace

from .regime import series
from .strategies import (STRATEGIES, Candles, Fees, _levels, allowed_by_state, simulate)

VARIANTS = ("be0", "be50", "be80", "cap")
CAP_R = 0.1


def compare_exits(candles: list[dict], settings: dict[str, dict], mode: str, fees: Fees) -> dict[str, dict]:
    """{variant: {"count", "sumR", "wins"}} over every strategy on one chart."""
    out = {v: {"count": 0, "sumR": 0.0, "wins": 0} for v in VARIANTS}
    if len(candles) < 300:
        return out
    states, _, _ = series(candles, mode)
    data = Candles(opens=[c["open"] for c in candles], highs=[c["high"] for c in candles],
                   lows=[c["low"] for c in candles], closes=[c["close"] for c in candles],
                   volumes=[c.get("volume", 0.0) for c in candles])
    for kind, strategy in STRATEGIES.items():
        params = settings[kind]
        signals = strategy.signals(data, params)
        if params.get("state_filter"):
            signals = [s for s in signals if allowed_by_state(s, states[s.index], strategy.states)]
        ratio = params.get("fee_ratio", 0)
        runs = {
            "be0": (signals, 0),
            "be50": (signals, 0.5),
            "be80": (signals, 0.8),
            "cap": (_capped(signals, candles, fees), 0),
        }
        for name, (sigs, breakeven) in runs.items():
            trades, _ = simulate(candles, sigs, breakeven, int(params.get("max_candles", 0)), fees, ratio)
            for t in trades:
                if t["result"] == "open" or t["r"] is None:
                    continue
                out[name]["count"] += 1
                out[name]["sumR"] += t["r"]
                out[name]["wins"] += t["r"] > 0
    return out


def _capped(signals, candles, fees: Fees):
    """The same signals with the target moved to CAP_R profit after the round-trip taker fee."""
    capped = []
    for s in signals:
        entry = candles[s.index]["close"]   # the next candle opens at about this price
        levels = _levels(s, entry)
        if levels is None:
            continue
        risk = abs(entry - levels[0])
        reward = CAP_R + entry * 2 * fees.taker / 100 / risk
        capped.append(replace(s, target_price=None, reward=reward))
    return capped


def add(total: dict, part: dict) -> None:
    for v, r in part.items():
        t = total.setdefault(v, {"count": 0, "sumR": 0.0, "wins": 0})
        for k in ("count", "sumR", "wins"):
            t[k] += r[k]


def strategy_results(candles: list[dict], settings: dict[str, dict], mode: str, fees: Fees) -> dict[str, dict]:
    """{strategy: {"count", "sumR", "wins"}}: every strategy on one chart, as the bot runs it."""
    from .strategies import run
    out = {k: {"count": 0, "sumR": 0.0, "wins": 0} for k in STRATEGIES}
    if len(candles) < 300:
        return out
    states, _, _ = series(candles, mode)
    for kind in STRATEGIES:
        for t in run(candles, kind, settings[kind], states, fees)["trades"]:
            if t["result"] == "open" or t["r"] is None:
                continue
            out[kind]["count"] += 1
            out[kind]["sumR"] += t["r"]
            out[kind]["wins"] += t["r"] > 0
    return out
