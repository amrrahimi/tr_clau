"""Study 2026-11-10 (owner: "the bot puts the target too far"). Read-only, 40 coins, R after fees, halves.

For every signal of the 18 strategies (bot fee / reward rules):
  * how far toward its own target price went before the stop (MFE, share of the way and in R)
  * the same entries and stops with other exits:
      own target / target at 1.0, 1.5, 2.0, 3.0 R / own target + lock 80/40, 60/30, 50/25, 40/20 /
      own target + break-even at 30%, 50% / 1.5 R target + lock 50/25
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import COINS, FEES, TIMEFRAMES, Tally, signals_of, walk  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG  # noqa: E402


def mfe(c, start, side, entry, stop, target, limit=400):
    """Largest move toward the target (share of the way) before the stop or the target."""
    long_ = side == LONG
    way = abs(target - entry)
    best = 0.0
    for i in range(start, min(len(c), start + limit)):
        k = c[i]
        if (k["low"] <= stop) if long_ else (k["high"] >= stop):
            return best, "stop"
        fav = (k["high"] - entry) if long_ else (entry - k["low"])
        best = max(best, fav / way)
        if best >= 1:
            return 1.0, "target"
    return best, "open"


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    t = Tally()
    dist = defaultdict(lambda: [0] * 6)   # tf -> counts of losers by MFE bucket
    reward = defaultdict(list)
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
                for s in signals_of(c, tf):
                    i, side, e, sl, tp = s["i"], s["sig"].side, s["entry"], s["stop"], s["target"]
                    half = 0 if s["time"] < mid else 1
                    risk = abs(e - sl)
                    d = 1 if side == LONG else -1
                    reward[tf].append(abs(tp - e) / risk)
                    share, how = mfe(c, i, side, e, sl, tp)
                    if how == "stop":
                        b = 0 if share < 0.1 else 1 if share < 0.25 else 2 if share < 0.4 else 3 if share < 0.6 else 4 if share < 0.8 else 5
                        dist[tf][b] += 1
                    args = (c, i, side, e, sl)
                    t.add(f"{tf} own target", half, walk(*args, tp, [], FEES.taker))
                    for k in (1.0, 1.5, 2.0, 3.0):
                        t.add(f"{tf} target {k}R", half, walk(*args, e + d * k * risk, [], FEES.taker))
                    for a, b2 in ((0.8, 0.4), (0.6, 0.3), (0.5, 0.25), (0.4, 0.2)):
                        t.add(f"{tf} own + lock {int(a*100)}/{int(b2*100)}", half, walk(*args, tp, [(a, b2)], FEES.taker))
                    for a in (0.3, 0.5):
                        t.add(f"{tf} own + BE at {int(a*100)}%", half, walk(*args, tp, [(a, "be")], FEES.taker))
                    t.add(f"{tf} 1.5R + lock 50/25", half, walk(*args, e + d * 1.5 * risk, [(0.5, 0.25)], FEES.taker))
                    t.add(f"{tf} 2R + lock 50/25", half, walk(*args, e + d * 2 * risk, [(0.5, 0.25)], FEES.taker))
    finally:
        await service.close()
    lines = t.report("Exits on the same entries and stops (40 coins)")
    lines.append("\n## Losers: how far toward the target before the stop (share of trades)")
    lines.append("tf | <10% | 10-25% | 25-40% | 40-60% | 60-80% | 80-100%")
    for tf, b in dist.items():
        n = sum(b) or 1
        lines.append(f"{tf} | " + " | ".join(f"{x / n * 100:.0f}%" for x in b) + f"  (n={sum(b)})")
    lines.append("\n## The strategies' own reward:risk (median / 75th / 90th percentile)")
    for tf, r in reward.items():
        r = sorted(r)
        q = lambda p: r[min(len(r) - 1, int(len(r) * p))]
        lines.append(f"{tf}: {q(0.5):.2f} / {q(0.75):.2f} / {q(0.9):.2f} (n={len(r)})")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
