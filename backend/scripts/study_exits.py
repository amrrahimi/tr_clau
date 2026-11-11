"""Study 2026-11-11 (owner approved): (1) exit rules modelled on the owner's own habits in the paper trades
(targets pulled closer, profits taken early at +0.25..+1.5R, break-even), and early exits for trades that go
nowhere; (2) a per-coin pause after a stop (no re-entry into the same coin for X hours).
Bot's 18 strategies, volatile-30 + top-40 coins, 5m and 15m, entry at the next open (taker), two time halves.
Base = today's panel: lock at 80% of the way -> stop to 60% of the way.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import FEES, signals_of  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG  # noqa: E402

TF = {"5m": 5000, "15m": 5000}
SEC = {"5m": 300, "15m": 900}


def sim(c, i, side, entry, stop, target, lock=(0.8, 0.6), be_at=None, partial=None, time_exit=None, rr=None,
        limit=400):
    """-> (R, exit time, how). rr: target at rr x risk instead of the strategy's. partial: (at R, share) then BE.
    be_at: stop to entry at +be_at R. time_exit: (candles, R): close if the best so far stayed below R."""
    k = 1 if side == LONG else -1
    risk = abs(entry - stop)
    if rr is not None:
        target = entry + k * rr * risk
    way = abs(target - entry)
    s = stop
    size = 1.0
    got = 0.0
    best = 0.0
    fin = FEES.taker

    def r_of(px, fee_out):
        return (k * (px - entry) - (entry * fin + px * fee_out) / 100) / risk

    end = min(len(c), i + limit)
    for j in range(i, end):
        x = c[j]
        lo, hi = (x["low"], x["high"]) if k > 0 else (x["high"], x["low"])
        if (x["low"] <= s) if k > 0 else (x["high"] >= s):
            gap = (x["open"] < s) if k > 0 else (x["open"] > s)
            px = x["open"] if gap else s
            return got + size * r_of(px, FEES.taker), x["time"], "stop"
        if (x["high"] >= target) if k > 0 else (x["low"] <= target):
            return got + size * r_of(target, FEES.maker), x["time"], "target"
        fav = (x["high"] - entry) if k > 0 else (entry - x["low"])
        best = max(best, fav / risk)
        if partial and size == 1.0 and best >= partial[0]:
            px = entry + k * partial[0] * risk
            got += partial[1] * r_of(px, FEES.maker)
            size -= partial[1]
            s = entry if k * (entry - s) > 0 else s
        if be_at is not None and best >= be_at and k * (entry - s) > 0:
            s = entry
        if lock and best * risk >= lock[0] * way:
            new = entry + k * lock[1] * way
            if k * (new - s) > 0:
                s = new
        if time_exit and j - i + 1 >= time_exit[0] and best < time_exit[1]:
            return got + size * r_of(x["close"], FEES.taker), x["time"], "time"
    x = c[end - 1]
    return got + size * r_of(x["close"], FEES.taker), x["time"], "end"


RULES = {
    "base: lock 80/60 (today)": {},
    "no lock": {"lock": None},
    "lock 50/25": {"lock": (0.5, 0.25)},
    "target 1R": {"rr": 1.0},
    "target 1.5R": {"rr": 1.5},
    "half at +1R, rest break-even": {"partial": (1.0, 0.5)},
    "half at +0.5R, rest break-even": {"partial": (0.5, 0.5)},
    "break-even at +1R": {"be_at": 1.0},
    "break-even at +0.5R": {"be_at": 0.5},
    "close if not +0.5R after 6 candles": {"time_exit": (6, 0.5)},
    "close if not +0.5R after 12 candles": {"time_exit": (12, 0.5)},
    "close if not +0.5R after 24 candles": {"time_exit": (24, 0.5)},
    "close if not +0.3R after 12 candles": {"time_exit": (12, 0.3)},
}
PAUSES = (0, 2, 6, 12, 24)   # hours without re-entry in the same coin after a stop


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    acc = defaultdict(lambda: [[0, 0.0, 0], [0, 0.0, 0]])     # name -> half -> [n, sumR, wins]
    order = []

    def add(name, half, r):
        if name not in acc:
            order.append(name)
        a = acc[name][half]
        a[0] += 1
        a[1] += r
        a[2] += r > 0.02

    try:
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
        top = [m.symbol for m in await service.top_markets(limit=40)]
        for set_name, coins in (("volatile30", vol), ("top40", top)):
            for num, symbol in enumerate(coins):
                print(f"[{set_name} {num + 1}/{len(coins)}] {symbol}", flush=True)
                trades = []     # this coin, both timeframes: (signal time, tf, base result)
                mids = {}
                for tf, total in TF.items():
                    try:
                        c = await fetch_history(lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                    except Exception as error:
                        print("  skip", tf, error, flush=True)
                        continue
                    c = c[:-1]
                    if len(c) < 600:
                        continue
                    mid = c[len(c) // 2]["time"]
                    mids[tf] = mid
                    for s in signals_of(c, tf):
                        half = 0 if s["time"] < mid else 1
                        args = (c, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"])
                        for name, kw in RULES.items():
                            r, _, _ = sim(*args, **kw)
                            add(f"1 {set_name} {tf} | {name}", half, r)
                        r, t_out, how = sim(*args)
                        trades.append((c[s["i"]]["time"], tf, half, r, t_out, how))
                # 2. one position per coin at a time, and a pause after a stop
                trades.sort()
                for pause in PAUSES:
                    busy = 0
                    for t_in, tf, half, r, t_out, how in trades:
                        if t_in < busy:
                            continue
                        add(f"2 {set_name} 5m+15m | one trade per coin, pause {pause}h after a stop", half, r)
                        busy = t_out + (pause * 3600 if how == "stop" else 0)
    finally:
        await service.close()

    lines = ["# Exit rules from the owner's habits, and a per-coin pause after a stop",
             "name | trades | avgR (half 1 / half 2) | total R (half 1 / half 2) | won %"]
    last = None
    for name in order:
        head, rest = name.split(" | ")
        if head != last:
            lines.append(f"\n## {head[2:]}")
            last = head
        h = acc[name]
        n = h[0][0] + h[1][0]
        if not n:
            continue
        avg = lambda x: f"{x[1] / x[0]:+.3f}" if x[0] else "-"
        lines.append(f"{rest} | {n} | {(h[0][1] + h[1][1]) / n:+.3f} ({avg(h[0])} / {avg(h[1])}) | "
                     f"{h[0][1] + h[1][1]:+.0f} ({h[0][1]:+.0f} / {h[1][1]:+.0f}) | {(h[0][2] + h[1][2]) / n * 100:.0f}")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
