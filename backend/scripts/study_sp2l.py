"""Study 2026-11-10 (owner's videos: the "SP2L" setup). Read-only, 40 coins, R after fees, two time halves.

SP2L (long; short is the mirror):
  1. a strong first leg: 2-8 bullish candles in a row that
       * hold a price gap (the low of a candle above the high of the candle two before it, FVG-like),
       * close near their top (close in the top 25% of the candle's range; "loose": top 40%),
       * are big (average range >= 1.5x the average range of the 20 candles before the leg; "loose": 1.2x);
  2. no entry on the leg itself: wait for the first pullback;
  3. trigger: a buy limit at the previous candle's low, filled by the first candle that trades below it
     (within 3 candles after the leg; a gap down fills at the open);
  4. stop: under the leg's low;  5. target: 1R (the video), 1.5R, 2R; also 2R + lock 50/25.
Limit entry = maker fee; the fill candle only checks the stop (a candle that fills and reaches the target
is not counted as a win). The bot's minimum stop-vs-fee rule is applied. Variant "+EMA200": only with the
200 EMA trend. The bot's own strategies on the same coins (own target) are shown for comparison.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import COINS, FEES, R, TIMEFRAMES, Tally, signals_of, walk  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.indicators import ema as ema_series  # noqa: E402
from app.paper import FEE_RATIO_BY_TF  # noqa: E402
from app.strategies import LONG, SHORT, fee_ok  # noqa: E402

RULES = {"strict": (0.75, 1.5), "loose": (0.6, 1.2)}   # (close position in the range, size vs the 20 before)
LEG_MIN, LEG_MAX, AVG_OF, WAIT = 2, 8, 20, 3


def _rng(k: dict) -> float:
    return k["high"] - k["low"]


def legs(c: list[dict], close_at: float, size: float):
    """Strong legs: (side, first, last). A leg is a maximal run of same-colour candles (cut at LEG_MAX)."""
    out = []
    i = AVG_OF + 1
    n = len(c)
    while i < n - 1:
        up = c[i]["close"] > c[i]["open"]
        down = c[i]["close"] < c[i]["open"]
        if not (up or down):
            i += 1
            continue
        j = i
        while j + 1 < n and j + 1 - i < LEG_MAX and ((c[j + 1]["close"] > c[j + 1]["open"]) if up
                                                      else (c[j + 1]["close"] < c[j + 1]["open"])):
            j += 1
        if j - i + 1 >= LEG_MIN and _strong(c, i, j, up, close_at, size):
            out.append((LONG if up else SHORT, i, j))
        i = j + 1
    return out


def _strong(c, a, b, up, close_at, size) -> bool:
    for k in c[a:b + 1]:
        r = _rng(k)
        if r <= 0:
            return False
        pos = (k["close"] - k["low"]) / r if up else (k["high"] - k["close"]) / r
        if pos < close_at:
            return False
    before = sum(_rng(k) for k in c[a - AVG_OF:a]) / AVG_OF
    if before <= 0 or sum(_rng(k) for k in c[a:b + 1]) / (b - a + 1) < size * before:
        return False
    for m in range(a, b + 1):   # gap: candle m+1 and m-1 do not overlap (m-1 may be the candle before the leg)
        if m + 1 > b:
            break
        if (c[m + 1]["low"] > c[m - 1]["high"]) if up else (c[m + 1]["high"] < c[m - 1]["low"]):
            return True
    return False


def trades(c: list[dict], close_at: float, size: float, tf: str):
    """SP2L entries: dicts with side, k (fill candle), entry, stop, time."""
    out = []
    for side, a, b in legs(c, close_at, size):
        long_ = side == LONG
        stop = min(k["low"] for k in c[a:b + 1]) if long_ else max(k["high"] for k in c[a:b + 1])
        for k in range(b + 1, min(len(c) - 2, b + 1 + WAIT)):
            prev, x = c[k - 1], c[k]
            level = prev["low"] if long_ else prev["high"]
            if (level <= stop) if long_ else (level >= stop):
                break
            if (x["low"] < level) if long_ else (x["high"] > level):
                gapped = (x["open"] < level) if long_ else (x["open"] > level)
                entry = x["open"] if gapped else level
                if ((entry > stop) if long_ else (entry < stop)) and fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF[tf]):
                    out.append({"side": side, "k": k, "entry": entry, "stop": stop, "time": c[b]["time"]})
                break
    return out


def run(c, t: dict, side: str, k: int, entry: float, stop: float, reward: float, steps) -> float:
    long_ = side == LONG
    risk = abs(entry - stop)
    x = c[k]
    if (x["low"] <= stop) if long_ else (x["high"] >= stop):   # the fill candle reached the stop too
        return R(side, entry, stop, risk, FEES.maker, FEES.taker)
    target = entry + reward * risk if long_ else entry - reward * risk
    return walk(c, k + 1, side, entry, stop, target, steps, FEES.maker)


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    t = Tally()
    base = Tally()
    tfs = {"1m": 5000, **TIMEFRAMES}
    try:
        coins = [m.symbol for m in await service.top_markets(limit=COINS)]
        for n, symbol in enumerate(coins):
            print(f"[{n + 1}/{len(coins)}] {symbol}", flush=True)
            for tf, total in tfs.items():
                try:
                    c = await fetch_history(lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                except Exception as error:
                    print("  skip", tf, error, flush=True)
                    continue
                c = c[:-1]
                if len(c) < 600:
                    continue
                mid = c[len(c) // 2]["time"]
                e200 = ema_series([x["close"] for x in c], 200)
                for rule, (close_at, size) in RULES.items():
                    for s in trades(c, close_at, size, tf):
                        half = 0 if s["time"] < mid else 1
                        args = (c, t, s["side"], s["k"], s["entry"], s["stop"])
                        e = e200[s["k"] - 1]
                        trend = e is not None and ((c[s["k"] - 1]["close"] > e) if s["side"] == LONG
                                                   else (c[s["k"] - 1]["close"] < e))
                        for name, ok in ((rule, True), (f"{rule}+EMA200", trend)):
                            if not ok:
                                continue
                            for rw in (1.0, 1.5, 2.0):
                                t.add(f"{tf} {name} {rw:g}R", half, run(*args, rw, []))
                            t.add(f"{tf} {name} 2R+lock50/25", half, run(*args, 2.0, [(0.5, 0.25)]))
                for s in signals_of(c, tf):
                    half = 0 if s["time"] < mid else 1
                    base.add(f"{tf} bot strategies (own target)", half,
                             walk(c, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"], [], FEES.taker))
    finally:
        await service.close()
    lines = [f"# SP2L study — {COINS} coins, Toobit fees maker 0.02% taker 0.06%, limit entry"]
    lines += t.report("SP2L (strict = top 25% close, 1.5x size; loose = top 40%, 1.2x)")
    lines += base.report("For comparison: the bot's 18 strategies on the same candles")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
