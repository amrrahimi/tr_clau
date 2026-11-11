"""Study 2026-11-11 (owner: "test idea 2 with a stop"): trade against extreme funding rates.
Funding above +X -> short, below -X -> long, from the next hour's open; hold H hours; a stop S% from the entry
(checked on 1h candles; a gap fills at the open), or no stop. One trade per coin at a time.
Coins: top 40 + volatile 30 (Toobit funding history, 1h prices ~166 days). Net of fees (0.12% round trip).
Reported: net % per trade, won %, worst trade, and R = net % / stop % (what 1 trade means with a fixed risk).
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study_new import COST  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402

LEVELS = (0.0005, 0.001)            # 0.05% and 0.1% per funding period
HOLDS = (8, 24, 48)                 # hours
STOPS = (None, 3.0, 5.0, 8.0, 12.0)  # % from the entry


def run(candles: list[dict], start: int, short: bool, hold: int, stop):
    entry = candles[start]["open"]
    end = min(len(candles) - 1, start + hold)
    if stop is not None:
        lvl = entry * (1 + stop / 100) if short else entry * (1 - stop / 100)
        for k in candles[start:end]:
            if (k["high"] >= lvl) if short else (k["low"] <= lvl):
                px = max(lvl, k["open"]) if short else min(lvl, k["open"])
                return ((entry - px) if short else (px - entry)) / entry * 100 - COST, end
    px = candles[end]["open"]
    return ((entry - px) if short else (px - entry)) / entry * 100 - COST, end


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    acc = defaultdict(lambda: [[], []])
    try:
        top = [m.symbol for m in await service.top_markets(limit=40)]
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
        coins = list(dict.fromkeys(top + vol))
        for num, symbol in enumerate(coins):
            print(f"[{num + 1}/{len(coins)}] {symbol}", flush=True)
            try:
                c = await fetch_history(lambda lim, before: service.fetch_candles(symbol, "1h", limit=lim, before=before), 4000)
                c = c[:-1]
                rates = await service.exchange.fetch_funding_rate_history(symbol, since=c[0]["time"] * 1000, limit=1000)
            except Exception as error:
                print("  skip", error, flush=True)
                continue
            if len(c) < 500:
                continue
            idx = {k["time"]: n for n, k in enumerate(c)}
            mid = c[len(c) // 2]["time"]
            rates = sorted((int(x["timestamp"] / 1000), x["fundingRate"]) for x in rates if x.get("fundingRate") is not None)
            group = "volatile" if symbol in vol and symbol not in top else "top"
            for level in LEVELS:
                for hold in HOLDS:
                    for stop in STOPS:
                        busy_until = -1
                        for tm, fr in rates:
                            if abs(fr) < level:
                                continue
                            start = idx.get((tm // 3600 + 1) * 3600)
                            if start is None or start <= busy_until or start + hold >= len(c):
                                continue
                            short = fr > 0
                            r, end = run(c, start, short, hold, stop)
                            busy_until = end
                            half = 0 if c[start]["time"] < mid else 1
                            name = (f"funding beyond {level * 100:g}% | hold {hold}h | "
                                    f"{'no stop' if stop is None else f'stop {stop:g}%'}")
                            for tag in ("all", "short (high funding)" if short else "long (low funding)", group):
                                acc[(name, tag)][half].append((r, stop))
    finally:
        await service.close()

    lines = ["# Against extreme funding, with stops (net % per trade; R = net % / stop %)",
             "setting | group | trades | net % per trade (half 1 / half 2) | won % | worst % | R per trade"]
    for (name, tag) in sorted(acc, key=lambda k: (k[0], k[1])):
        h = acc[(name, tag)]
        allr = h[0] + h[1]
        if len(allr) < 10:
            continue
        m = lambda xs: f"{sum(x for x, _ in xs) / len(xs):+.2f}" if xs else "-"
        stop = allr[0][1]
        rr = f"{sum(x for x, _ in allr) / len(allr) / stop:+.3f}" if stop else "-"
        lines.append(f"{name} | {tag} | {len(allr)} | {m(allr)} ({m(h[0])} / {m(h[1])}) | "
                     f"{sum(1 for x, _ in allr if x > 0) / len(allr) * 100:.0f} | {min(x for x, _ in allr):+.1f} | {rr}")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
