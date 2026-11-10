"""Study 2026-11-10 (owner's idea): while the limit order waits, if the price goes further our way (down for a long),
enter there and move the stop and the target down by the same amount (same risk, same reward).
Bot's 18 strategies, top-40 + volatile-30 coins. The bot today: limit at entry - 0.1 x risk, 1 candle to fill.
Variants: d = extra depth (share of the risk) beyond the bot's limit; wait 1 or 3 candles; not reached = no trade.
The fill candle only checks the (moved) stop. Reported: trades, avg R per trade, and total R per 100 signals
(missed signals count as 0), two time halves.
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
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "30m": 4000, "1h": 4000}
BASE = 0.1
DEPTHS = (0.0, 0.25, 0.5, 0.75, 1.0)
WAITS = (1, 3)


def dip(c, s, d: float, wait: int):
    side = s["sig"].side
    long_ = side == LONG
    k = 1 if long_ else -1
    dist = abs(s["entry"] - s["stop"])
    shift = (BASE + d) * dist
    lvl, stop, target = s["entry"] - k * shift, s["stop"] - k * shift, s["target"] - k * shift
    i = s["i"]
    for j in range(i, min(len(c) - 1, i + wait)):
        x = c[j]
        if (x["low"] <= lvl) if long_ else (x["high"] >= lvl):
            fill = min(lvl, x["open"]) if long_ else max(lvl, x["open"])
            risk = abs(fill - stop)
            if (x["low"] <= stop) if long_ else (x["high"] >= stop):
                return R(side, fill, stop, risk, FEES.maker, FEES.taker)
            return walk(c, j + 1, side, fill, stop, target, [], FEES.maker)
    return None


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    acc = defaultdict(lambda: [[0, 0, 0.0, 0], [0, 0, 0.0, 0]])   # name -> half -> [signals, trades, sumR, wins]
    try:
        top = [m.symbol for m in await service.top_markets(limit=40)]
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
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
                    for s in signals_of(c, tf):
                        half = 0 if s["time"] < mid else 1
                        for wait in WAITS:
                            for d in DEPTHS:
                                if wait == 3 and d == 0.0:
                                    continue
                                name = f"{set_name} {tf} " + ("bot today (0.1, 1 candle)" if d == 0 and wait == 1
                                                               else f"+{d:g} risk deeper, wait {wait}")
                                a = acc[name][half]
                                a[0] += 1
                                r = dip(c, s, d, wait)
                                if r is None:
                                    continue
                                a[1] += 1
                                a[2] += r
                                a[3] += r > 0
    finally:
        await service.close()
    lines = ["# Owner's idea: deeper entry with stop and target moved by the same amount",
             "name | signals | trades (filled %) | avgR per trade | R per 100 signals: all (half 1 / half 2) | won %"]
    for name in sorted(acc):
        h = acc[name]
        sig = h[0][0] + h[1][0]
        tr = h[0][1] + h[1][1]
        sr = h[0][2] + h[1][2]
        if not sig:
            continue
        per = lambda x: f"{x[2] / x[0] * 100:+.1f}" if x[0] else "-"
        lines.append(f"{name} | {sig} | {tr} ({tr / sig * 100:.0f}%) | {sr / tr if tr else 0:+.3f} | "
                     f"{sr / sig * 100:+.1f} ({per(h[0])} / {per(h[1])}) | {(h[0][3] + h[1][3]) / tr * 100 if tr else 0:.0f}")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
