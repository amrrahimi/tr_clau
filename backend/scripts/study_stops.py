"""Study 2026-11-10 (owner): would a stop behind support / resistance raise the win rate? Read-only.

Swing levels: pivot highs / lows (3 candles each side) of the 100 closed candles before the signal.
For a long, "support" = nearest swing low below the entry (short: nearest swing high above).
  own                 the strategy's stop, target 2R (reference)
  own: level protects the nearest level lies between the entry and the stop (stop already behind it)
  own: stop in front  the stop sits before the level (price can take the stop and then turn at the level)
  own: no level       no swing level on that side
  SR stop             stop = level -/+ 0.25 ATR, target 2R of the new risk (only where a level exists and
                      the new stop is 0.3-4 ATR away); "own (same signals)" is the reference on those signals
  SR stop + SR target as SR stop, target = nearest level on the other side if that gives >= 1R
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import COINS, FEES, TIMEFRAMES, Tally, signals_of, walk  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.indicators import atr as atr_series  # noqa: E402
from app.strategies import LONG, fee_ok  # noqa: E402

PIVOT, LOOK = 3, 100


def pivots(c):
    highs, lows = [], []
    for j in range(PIVOT, len(c) - PIVOT):
        h, low = c[j]["high"], c[j]["low"]
        if all(h >= c[j + d]["high"] for d in range(-PIVOT, PIVOT + 1) if d):
            highs.append((j, h))
        if all(low <= c[j + d]["low"] for d in range(-PIVOT, PIVOT + 1) if d):
            lows.append((j, low))
    return highs, lows


def nearest(levels, upto, price, below: bool):
    """Nearest pivot level below / above the price among pivots confirmed before candle `upto`."""
    best = None
    for j, x in levels:
        if j + PIVOT >= upto or j < upto - LOOK:
            continue
        if below and x < price and (best is None or x > best):
            best = x
        if not below and x > price and (best is None or x < best):
            best = x
    return best


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    t = Tally()
    try:
        coins = [m.symbol for m in await service.top_markets(limit=COINS)]
        for n, symbol in enumerate(coins):
            print(f"[{n + 1}/{len(coins)}] {symbol}", flush=True)
            for tf, total in TIMEFRAMES.items():
                try:
                    c = await fetch_history(lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                except Exception as error:
                    print("  skip", tf, error, flush=True)
                    continue
                c = c[:-1]
                if len(c) < 600:
                    continue
                mid = c[len(c) // 2]["time"]
                highs, lows = pivots(c)
                a = atr_series([k["high"] for k in c], [k["low"] for k in c], [k["close"] for k in c], 14)
                for s in signals_of(c, tf):
                    i, side, e, sl = s["i"], s["sig"].side, s["entry"], s["stop"]
                    at = a[s["sig"].index]
                    if at is None or at <= 0:
                        continue
                    long_ = side == LONG
                    d = 1 if long_ else -1
                    half = 0 if s["time"] < mid else 1
                    risk = abs(e - sl)
                    own = walk(c, i, side, e, sl, e + d * 2 * risk, [], FEES.taker)
                    t.add(f"{tf} own", half, own)
                    level = nearest(lows if long_ else highs, s["sig"].index + 1, e, long_)
                    if level is None:
                        t.add(f"{tf} own: no level", half, own)
                        continue
                    protected = (sl < level) if long_ else (sl > level)
                    t.add(f"{tf} own: level protects" if protected else f"{tf} own: stop in front", half, own)
                    new = level - d * 0.25 * at
                    r2 = abs(e - new)
                    if not 0.3 * at <= r2 <= 4 * at or not fee_ok(e, new, FEES, 0.05):
                        continue
                    t.add(f"{tf} own (same signals)", half, own)
                    t.add(f"{tf} SR stop", half, walk(c, i, side, e, new, e + d * 2 * r2, [], FEES.taker))
                    opp = nearest(highs if long_ else lows, s["sig"].index + 1, e, not long_)
                    if opp is not None and abs(opp - e) >= r2:
                        t.add(f"{tf} SR stop + SR target", half, walk(c, i, side, e, new, opp, [], FEES.taker))
                        t.add(f"{tf} own (same as SR target)", half, own)
    finally:
        await service.close()
    text = "\n".join(t.report("Stops and support / resistance (40 coins)"))
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
