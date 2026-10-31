"""Signals for the owner's high-risk "barrage" account (1-minute charts only).

The six main strategies are built for few, careful trades. The barrage account
wants many: these short patterns happen again and again on every coin, so over
100 coins there are several signals every minute. They are only used by that
account (closed at a tiny profit), never by the main bot.

- scalp_ema:  short trend up (EMA 9 above EMA 21, both rising), the candle dips to
              EMA 9 and closes back above it -> long (mirror for short).
- scalp_rsi2: RSI over 2 candles below 10 while above EMA 50 -> long; above 90 while
              below EMA 50 -> short (a quick snap-back inside the trend).
- scalp_bb:   the candle pokes through a Bollinger band (20, 2) and closes back
              inside -> trade back toward the middle band.
Stop: 1 ATR(14) from the entry. Target: 1 x the risk (the profit cap usually closes earlier).

Also: the main strategies with the barrage account's looser rules (`loose_signals`):
signals of the last LOOSE_CANDLES closed candles, even when the strategy is still in an
earlier trade, and without the fee rule.
"""

from __future__ import annotations

from . import indicators as ind
from .regime import series
from .strategies import LONG, SHORT, STRATEGIES, Candles, Signal, allowed_by_state

SCALP_KINDS = ("scalp_ema", "scalp_rsi2", "scalp_bb")
LOOSE_CANDLES = 2
STOP_ATR = 1.0
REWARD = 1.0


def _data(candles: list[dict]) -> Candles:
    return Candles(opens=[c["open"] for c in candles], highs=[c["high"] for c in candles],
                   lows=[c["low"] for c in candles], closes=[c["close"] for c in candles],
                   volumes=[c.get("volume", 0.0) for c in candles])


def scalp_signals(candles: list[dict]) -> list[tuple[str, Signal]]:
    """(kind, signal) on the last closed candle only (the input must hold closed candles)."""
    n = len(candles)
    if n < 60:
        return []
    d = _data(candles)
    i = n - 1
    atr = ind.atr(d.highs, d.lows, d.closes, 14)[i]
    if not atr:
        return []
    out: list[tuple[str, Signal]] = []

    def add(kind: str, side: str) -> None:
        out.append((kind, Signal(i, side, stop_distance=STOP_ATR * atr, reward=REWARD)))

    e9, e21, e50 = ind.ema(d.closes, 9), ind.ema(d.closes, 21), ind.ema(d.closes, 50)
    c, lo, hi = d.closes[i], d.lows[i], d.highs[i]
    if None not in (e9[i], e9[i - 1], e21[i], e21[i - 1]):
        if e9[i] > e21[i] and e9[i] > e9[i - 1] and e21[i] > e21[i - 1] and lo <= e9[i] < c:
            add("scalp_ema", LONG)
        elif e9[i] < e21[i] and e9[i] < e9[i - 1] and e21[i] < e21[i - 1] and hi >= e9[i] > c:
            add("scalp_ema", SHORT)

    r2 = ind.rsi(d.closes, 2)[i]
    if r2 is not None and e50[i] is not None:
        if r2 < 10 and c > e50[i]:
            add("scalp_rsi2", LONG)
        elif r2 > 90 and c < e50[i]:
            add("scalp_rsi2", SHORT)

    upper, _middle, lower = ind.bollinger(d.closes, 20, 2.0)
    if upper[i] is not None and lower[i] is not None:
        if lo < lower[i] < c:
            add("scalp_bb", LONG)
        elif hi > upper[i] > c:
            add("scalp_bb", SHORT)
    return out


def loose_signals(candles: list[dict], settings: dict[str, dict], mode: str) -> list[tuple[str, Signal]]:
    """The main strategies' signals of the last LOOSE_CANDLES closed candles, with the market-state
    rule but without "one trade at a time" and without the fee rule."""
    n = len(candles)
    if n < 60:
        return []
    states, _, _ = series(candles, mode)
    d = _data(candles)
    out = []
    for kind, strategy in STRATEGIES.items():
        params = settings[kind]
        for s in strategy.signals(d, params):
            if s.index < n - LOOSE_CANDLES:
                continue
            if params.get("state_filter") and not allowed_by_state(s, states[s.index], strategy.states):
                continue
            out.append((kind, s))
    return out
