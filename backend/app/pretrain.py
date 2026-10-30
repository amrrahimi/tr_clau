"""Pre-training (owner's step 1): rebuild past signals from the candle history
so the brain has thousands of examples from the first day instead of waiting.

For every chart (coin x timeframe) the strategies are run over the history the
bot keeps anyway. Every past trade becomes a remembered signal with the
conditions at its moment, exactly like a live one:
- market state, ADX and ATR ratio of the signal candle;
- stop distance, reward ratio, fee share, hour and weekday;
- the strategy's record built ONLY from trades that had finished before that
  moment (no peeking into the future), and whether it counted as "reliable".
They are marked as history, so the brain can tell them from live signals and
its final test is done on live ones once there are enough.
"""

from __future__ import annotations

from typing import Optional

from .memory import features
from .regime import series
from .scanner import reliable
from .strategies import STRATEGIES, Fees, run, stats

WARMUP = 1000           # skip signals with less history than this before them (record too short)
REFRESH_SECONDS = 24 * 3600


def history_signals(symbol: str, base: str, timeframe: str, candles: list[dict], settings: dict[str, dict],
                    mode: str, fees: Fees) -> list[dict]:
    """Finished past trades of every strategy on one chart, as memory rows."""
    if len(candles) <= WARMUP + 2:
        return []
    states, adx, ratio = series(candles, mode)
    step = candles[1]["time"] - candles[0]["time"]
    index = {c["time"]: i for i, c in enumerate(candles)}
    out = []
    for kind in STRATEGIES:
        trades = run(candles, kind, settings[kind], states, fees)["trades"]
        finished = [t for t in trades if t["result"] != "open"]
        by_exit = sorted(finished, key=lambda t: t["exitTime"])
        for t in finished:
            j = index.get(t["signalTime"])
            if j is None or j < WARMUP:
                continue
            # The record as it was at the signal: only trades that had already ended.
            before = [x for x in by_exit if x["exitTime"] <= t["signalTime"]]
            record = stats(before)
            entry = {"symbol": symbol, "base": base, "strategy": kind, "marketState": states[j], "stats": record,
                     "signal": {"side": t["side"], "time": t["signalTime"], "entry": t["entryPrice"],
                                "stopLoss": t["stopLoss"], "takeProfit": t["takeProfit"],
                                "confirmedAt": t["signalTime"] + step}}
            ok = reliable(entry)
            feats = features(entry, {"adx": adx[j], "atrRatio": ratio[j]}, fees)
            feats["reliable"] = ok
            out.append({"entry": entry, "features": feats, "reliable": ok, "result": t["result"],
                        "exitTime": t["exitTime"], "exitReason": t["exitReason"], "pnlPercent": t["pnlPercent"],
                        "r": t["r"]})
    return out


def due(last_run: Optional[float], now: float) -> bool:
    return last_run is None or now - last_run >= REFRESH_SECONDS
