"""Study 2026-11-11 (owner): half the size at the bot's usual limit, the other half lower (d x risk deeper) if the price
gets there within W candles. Compared with today's full-size trade. 1R = the risk of today's full-size trade.
  A: both halves share the same stop and target (classic scale-in: the lower half risks less, earns more).
  B: the lower half gets its own stop and target, moved down as much as its entry (owner's earlier idea).
Bot's 18 strategies, volatile-30 + top-40, 5m / 15m / 30m / 1h, two time halves; R per 100 signals.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import FEES, R, signals_of, walk  # noqa: E402
from study_dip import BASE, dip  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "30m": 4000, "1h": 4000}
DEPTHS = (0.25, 0.5, 0.75)
WAITS = (1, 3)


def lower_half(c, s, d, wait, own_levels: bool):
    """R of the lower half as a share of today's full risk (None = never filled)."""
    side = s["sig"].side
    long_ = side == LONG
    k = 1 if long_ else -1
    dist = abs(s["entry"] - s["stop"])
    stop1, target1 = s["stop"] - k * BASE * dist, s["target"] - k * BASE * dist
    lvl = s["entry"] - k * (BASE + d) * dist
    stop, target = (stop1 - k * d * dist, target1 - k * d * dist) if own_levels else (stop1, target1)
    for j in range(s["i"], min(len(c) - 1, s["i"] + wait)):
        x = c[j]
        if (x["low"] <= lvl) if long_ else (x["high"] >= lvl):
            fill = min(lvl, x["open"]) if long_ else max(lvl, x["open"])
            risk = abs(fill - stop)
            if risk <= 0:
                return None
            if (x["low"] <= stop) if long_ else (x["high"] >= stop):
                r = R(side, fill, stop, risk, FEES.maker, FEES.taker)
            else:
                r = walk(c, j + 1, side, fill, stop, target, [], FEES.maker)
            return r * risk / dist
    return None


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    acc = defaultdict(lambda: [[0, 0.0], [0, 0.0]])    # name -> half -> [signals, sumR]
    order = []
    try:
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
        top = [m.symbol for m in await service.top_markets(limit=40)]
        for set_name, coins in (("volatile30", vol), ("top40", top)):
            for num, symbol in enumerate(coins):
                print(f"[{set_name} {num + 1}/{len(coins)}] {symbol}", flush=True)
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
                    key = f"{set_name} {tf}"
                    for s in signals_of(c, tf):
                        half = 0 if s["time"] < mid else 1
                        today = dip(c, s, 0.0, 1)
                        t = today or 0.0

                        def add(name, r):
                            if name not in acc:
                                order.append(name)
                            a = acc[name][half]
                            a[0] += 1
                            a[1] += r
                        add(f"{key} | today: full size at the usual limit", t)
                        for d in DEPTHS:
                            for w in WAITS:
                                for own, label in ((False, "A same stop/target"), (True, "B lower half moved")):
                                    low = lower_half(c, s, d, w, own)
                                    add(f"{key} | half + half {d:g} x risk lower, wait {w}, {label}",
                                        0.5 * t + 0.5 * (low or 0.0))
    finally:
        await service.close()
    lines = ["# Half at the usual limit + half lower (R per 100 signals, 1R = today's full-size risk): all (half 1 / half 2)"]
    last = None
    for name in order:
        key, rest = name.split(" | ")
        if key != last:
            lines.append(f"\n## {key}")
            last = key
        h = acc[name]
        sig = h[0][0] + h[1][0]
        per = [f"{h[k][1] / h[k][0] * 100:+.1f}" if h[k][0] else "-" for k in (0, 1)]
        lines.append(f"{rest}: {(h[0][1] + h[1][1]) / sig * 100:+.1f} ({per[0]} / {per[1]})")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
