"""Study 2026-11-10 (owner's follow-up): only the cases where the price went AGAINST the signal after it.
 1. Signals where the price fell (long; rose for a short) d x risk within W candles: today's trade (bot's limit at
    0.1 x risk, 1 candle) against the owner's idea (enter at that lower price, stop and target moved down as much).
 2. Signals the bot missed today (limit not filled in 1 candle) where the price later fell d x risk within W candles:
    an extra trade with the owner's idea. Is it worth adding?
Bot's 18 strategies, volatile-30 + top-40 coins, 5m / 15m / 30m, two time halves.
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import signals_of  # noqa: E402
from study_dip import BASE, dip  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "30m": 4000}
DEPTHS = (0.25, 0.5, 1.0)
WAITS = (3, 6)


def reached(c, s, d, wait) -> bool:
    long_ = s["sig"].side == LONG
    lvl = s["entry"] - (1 if long_ else -1) * (BASE + d) * abs(s["entry"] - s["stop"])
    for j in range(s["i"], min(len(c) - 1, s["i"] + wait)):
        if (c[j]["low"] <= lvl) if long_ else (c[j]["high"] >= lvl):
            return True
    return False


class Acc:
    def __init__(self):
        self.n = [0, 0]
        self.r = [0.0, 0.0]
        self.w = [0, 0]

    def add(self, half, r):
        self.n[half] += 1
        self.r[half] += r
        self.w[half] += r > 0

    def text(self):
        n = sum(self.n)
        if not n:
            return "-"
        h = [f"{self.r[k] / self.n[k]:+.3f}" if self.n[k] else "-" for k in (0, 1)]
        return f"n={n} avgR {sum(self.r) / n:+.3f} ({h[0]} / {h[1]}) won {sum(self.w) / n * 100:.0f}%"


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    A = defaultdict(Acc)
    signals = defaultdict(lambda: [0, 0])
    today_total = defaultdict(lambda: [0.0, 0.0])
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
                        signals[key][half] += 1
                        today = dip(c, s, 0.0, 1)
                        if today is not None:
                            today_total[key][half] += today
                        for d in DEPTHS:
                            for w in WAITS:
                                name = f"{key} | price went against {d:g} x risk within {w} candles"
                                if not reached(c, s, d, w):
                                    continue
                                idea = dip(c, s, d, w)
                                if today is not None:
                                    A[(name, "1 today (entered as usual)")].add(half, today)
                                    if idea is not None:
                                        A[(name, "1 owner's idea (entered lower, levels moved)")].add(half, idea)
                                elif idea is not None:
                                    A[(name, "2 EXTRA trade (bot had missed it)")].add(half, idea)
    finally:
        await service.close()
    lines = ["# Price went against the signal: today's trade vs the owner's idea; extra trades from missed signals"]
    for key in sorted(signals):
        sig = sum(signals[key])
        lines.append(f"\n## {key}: {sig} signals, today's total {sum(today_total[key]) / sig * 100:+.1f} R per 100 signals")
        for name in sorted({n for n, _ in A if n.startswith(key + " |")}):
            lines.append(name.split(" | ")[1])
            for part in ("1 today (entered as usual)", "1 owner's idea (entered lower, levels moved)",
                         "2 EXTRA trade (bot had missed it)"):
                if (name, part) in A:
                    acc = A[(name, part)]
                    extra = ""
                    if part.startswith("2"):
                        extra = f" -> adds {sum(acc.r) / sig * 100:+.1f} R per 100 signals"
                    lines.append(f"   {part}: {acc.text()}{extra}")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
