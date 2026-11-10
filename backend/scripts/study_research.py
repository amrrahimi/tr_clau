"""Study 2026-11-10 (owner: "research more, fitted to our charts and data"). Read-only.

Two coin sets: the 40 top-volume coins, and the 30 most volatile coins (the bot's "volatile" mode; today's list).
Part 1, what our data looks like (per timeframe):
  candle size against the fee, return autocorrelation, how often the next candle reverses, what follows big candles
  (continuation in %, next 1 and 3 candles), and BTC -> altcoin lead-lag (does the coin follow BTC's last candle?).
Part 2, ideas from the research, on our data (net of fees, two time halves):
  L  lead-lag: after a big BTC candle, trade the coin in BTC's direction for 1 candle (market in / out).
  A+ volatility breakout (long, 1h) with filters from the research: BTC trend, the coin's 5-day average, adaptive k
     (20-day noise ratio), and a tighter stop (half way).
  G+ buy the 5 biggest losers of the day (4h data) with a stop and a BTC filter.
"""

from __future__ import annotations

import asyncio
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import FEES, R, Tally  # noqa: E402
from study_new import COST, pct, trade  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG, SHORT  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "1h": 4000, "4h": 2500}
BTC = "BTC/USDT:USDT"


def ret(k) -> float:
    return (k["close"] - k["open"]) / k["open"] * 100


class Diag:
    """Per (set, tf): sums for the data portrait."""

    def __init__(self):
        self.d = defaultdict(lambda: defaultdict(list))

    def add(self, key, name, value):
        self.d[key][name].append(value)

    def lines(self) -> list[str]:
        out = ["## 1. Our data (median candle range %, cost share, lag-1 autocorrelation, next candle reverses %)",
               "set tf | range% | fee/range | autocorr | reverses% | after 2-3x candle: next1 / next3 % | after >3x: next1 / next3 % (n)"]
        for key, v in sorted(self.d.items()):
            def m(name):
                x = v.get(name) or []
                return sum(x) / len(x) if x else float("nan")
            rng = sorted(v["range"])
            med = rng[len(rng) // 2] if rng else float("nan")
            out.append(f"{key} | {med:.2f} | {COST / med * 100 if med else 0:.0f}% | {m('ac'):+.3f} | {m('rev') * 100:.1f} | "
                       f"{m('b2n1'):+.3f} / {m('b2n3'):+.3f} | {m('b3n1'):+.3f} / {m('b3n3'):+.3f} ({len(v.get('b3n1', []))})")
        return out


def portrait(c, key, d: Diag):
    r = [ret(k) for k in c]
    n = len(r)
    if n < 200:
        return
    mean = sum(r) / n
    var = sum((x - mean) ** 2 for x in r)
    if var > 0:
        d.add(key, "ac", sum((r[i] - mean) * (r[i + 1] - mean) for i in range(n - 1)) / var)
    for i in range(50, n - 4):
        k = c[i]
        d.add(key, "range", (k["high"] - k["low"]) / k["open"] * 100)
        if r[i] and r[i + 1]:
            d.add(key, "rev", 1.0 if (r[i] > 0) != (r[i + 1] > 0) else 0.0)
        avg = sum(abs(x) for x in r[i - 50:i]) / 50
        if avg <= 0:
            continue
        size = abs(r[i]) / avg
        sign = 1 if r[i] > 0 else -1
        n1 = r[i + 1] * sign
        n3 = (c[i + 3]["close"] - c[i + 1]["open"]) / c[i + 1]["open"] * 100 * sign
        if 2 <= size < 3:
            d.add(key, "b2n1", n1)
            d.add(key, "b2n3", n3)
        elif size >= 3:
            d.add(key, "b3n1", n1)
            d.add(key, "b3n3", n3)


def lead_lag(c, btc: dict, tf, mid, half_name, t: Tally, d: Diag, key):
    """Coin's next candle after BTC's candle, in BTC's direction (continuation in %, after fees for the trade lines)."""
    times = sorted(btc)
    if len(times) < 100:
        return
    babs = [abs(ret(btc[x])) for x in times]
    pos = {x: n for n, x in enumerate(times)}
    for i in range(1, len(c) - 1):
        n = pos.get(c[i]["time"])
        if n is None or n < 50:
            continue
        avg = sum(babs[n - 50:n]) / 50
        b = ret(btc[c[i]["time"]])
        if avg <= 0 or b == 0:
            continue
        size = abs(b) / avg
        sign = 1 if b > 0 else -1
        nxt = ret(c[i + 1]) * sign
        own = ret(c[i]) * sign
        lag = own < abs(b)            # the coin moved less than BTC in the same candle
        if size >= 2:
            d.add(key, "ll_all", nxt)
        if size >= 3:
            half = 0 if c[i]["time"] < mid else 1
            side = LONG if sign > 0 else SHORT
            t.add(f"L {half_name} {tf} BTC candle >3x: coin next candle", half, pct(side, c[i + 1]["open"], c[i + 1]["close"]))
            if lag:
                t.add(f"L {half_name} {tf} BTC >3x and coin lagged", half, pct(side, c[i + 1]["open"], c[i + 1]["close"]))


def daily(c):
    days = defaultdict(list)
    for n, k in enumerate(c):
        days[k["time"] // 86400].append(n)
    return days


def btc_trend(btc_1h: list[dict]) -> dict:
    """day -> True if BTC's previous day closed above the average of the 10 days before it."""
    days = daily(btc_1h)
    keys = sorted(days)
    closes = {d: btc_1h[days[d][-1]]["close"] for d in keys}
    out = {}
    for n, d in enumerate(keys):
        if n >= 11:
            prev = keys[n - 1]
            avg = sum(closes[x] for x in keys[n - 11:n - 1]) / 10
            out[d] = closes[prev] > avg
    return out


def vb_plus(c, mid, t: Tally, up: dict, name: str):
    days = daily(c)
    keys = sorted(days)
    full = 86400 // (c[1]["time"] - c[0]["time"])
    stats = {}
    for d in keys:
        idx = days[d]
        hi = max(c[i]["high"] for i in idx)
        lo = min(c[i]["low"] for i in idx)
        o, cl = c[idx[0]]["open"], c[idx[-1]]["close"]
        stats[d] = (hi - lo, 1 - abs(cl - o) / (hi - lo) if hi > lo else 1.0, cl, len(idx))
    for n, d in enumerate(keys):
        if n < 21 or stats[d][3] < full or stats[keys[n - 1]][3] < full:
            continue
        prev = keys[n - 1]
        rng = stats[prev][0]
        cur = days[d]
        o = c[cur[0]]["open"]
        ma5 = sum(stats[x][2] for x in keys[n - 5:n]) / 5
        noise = sum(stats[x][1] for x in keys[n - 20:n]) / 20
        half = 0 if c[cur[0]]["time"] < mid else 1
        for kname, k in (("k=0.5", 0.5), ("k=0.7", 0.7), ("k=noise", noise)):
            lvl = o + k * rng
            for i in cur:
                x = c[i]
                if x["high"] < lvl:
                    continue
                entry = max(lvl, x["open"])
                last = cur[-1]
                for sname, stop in (("stop=open", o), ("stop=half", entry - 0.5 * (entry - o))):
                    risk = entry - stop
                    if risk <= 0 or risk / entry * 100 < 0.5:
                        continue
                    hit = R(LONG, entry, stop, risk, FEES.taker, FEES.taker)
                    if x["low"] <= stop:           # worst case: the entry candle touched the stop
                        r = hit
                    elif i < last:
                        r = trade(c, i + 1, LONG, entry, stop, None, limit=last - i)
                    else:
                        r = R(LONG, entry, x["close"], risk, FEES.taker, FEES.taker)
                    base = f"A+ {name} {kname} {sname}"
                    t.add(f"{base} (worst case)", half, r)
                    if up.get(d):
                        t.add(f"{base} +BTC up", half, r)
                    if c[cur[0]]["open"] > ma5:
                        t.add(f"{base} +coin above 5-day avg", half, r)
                    if up.get(d) and c[cur[0]]["open"] > ma5:
                        t.add(f"{base} +both", half, r)
                break


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    d = Diag()
    t = Tally()
    p = Tally()
    four: dict[str, dict] = {}
    try:
        top = [m.symbol for m in await service.top_markets(limit=40)]
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
        print("volatile:", ", ".join(s.split("/")[0] for s in vol), flush=True)
        btc = {}
        for tf, total in TF.items():
            b = await fetch_history(lambda lim, before: service.fetch_candles(BTC, tf, limit=lim, before=before), total)
            btc[tf] = b[:-1]
        up = btc_trend(btc["1h"])
        btc_by = {tf: {k["time"]: k for k in b} for tf, b in btc.items()}
        cache: dict = {}
        for set_name, coins in (("top40", top), ("volatile30", vol)):
            for num, symbol in enumerate(coins):
                print(f"[{set_name} {num + 1}/{len(coins)}] {symbol}", flush=True)
                for tf, total in TF.items():
                    if (symbol, tf) not in cache:
                        try:
                            cc = await fetch_history(lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                        except Exception as error:
                            print("  skip", tf, error, flush=True)
                            cc = []
                        cache[(symbol, tf)] = cc[:-1]
                    c = cache[(symbol, tf)]
                    if len(c) < 600:
                        continue
                    mid = c[len(c) // 2]["time"]
                    key = f"{set_name} {tf}"
                    portrait(c, key, d)
                    if symbol != BTC and tf in ("5m", "15m", "1h"):
                        lead_lag(c, btc_by[tf], tf, mid, set_name, p, d, key)
                    if tf in ("15m", "1h"):
                        vb_plus(c, mid, t, up, f"{set_name} {tf}")
                    if tf == "4h" and set_name == "top40":
                        four[symbol] = {k["time"]: k for k in c}
                # free memory of the small timeframes after use
                for tf in ("5m", "15m"):
                    cache.pop((symbol, tf), None)
    finally:
        await service.close()

    # G+ losers of the day with a stop (4h)
    btc4 = btc_by.get("4h", {}) if four else {}
    times = sorted({tm for x in four.values() for tm in x if (tm // 3600) % 24 == 0})
    tmid = times[len(times) // 2] if times else 0
    for tm in times:
        rows = []
        for s, x in four.items():
            now, past = x.get(tm), x.get(tm - 6 * 14400)
            path = [x.get(tm + j * 14400) for j in range(6)]
            if now and past and all(path):
                rows.append(((now["open"] - past["open"]) / past["open"], now["open"], path))
        if len(rows) < 20:
            continue
        rows.sort(key=lambda r: r[0])
        b_now, b_past = btc4.get(tm), btc4.get(tm - 6 * 14400)
        btc_fell = b_now and b_past and b_now["open"] < b_past["open"]
        half = 0 if tm < tmid else 1
        for ret1, entry, path in rows[:5]:
            for sl in (None, 5.0, 10.0):
                exit_ = path[-1]["close"]
                if sl:
                    stop = entry * (1 - sl / 100)
                    for k in path:
                        if k["low"] <= stop:
                            exit_ = min(stop, k["open"])
                            break
                name = f"G+ long 5 biggest 1d losers, {'no stop' if sl is None else f'stop {sl:g}%'}"
                p.add(name, half, pct(LONG, entry, exit_))
                p.add(f"{name}, BTC fell too" if btc_fell else f"{name}, BTC rose", half, pct(LONG, entry, exit_))

    lines = ["# Research study — our coins and charts (Toobit fees, round trip 0.12% taker)"]
    lines += d.lines()
    lines.append("\nlead-lag: coin's next candle in BTC's direction after a BTC candle >= 2x its average (%, before fees)")
    for key, v in sorted(d.d.items()):
        x = v.get("ll_all")
        if x:
            lines.append(f"{key}: {sum(x) / len(x):+.4f}% (n={len(x)})")
    lines += t.report("2. A+ volatility breakout, long, 15m / 1h, worst case (R)")
    lines += [x.replace("avgR", "avg%") for x in p.report("2. L lead-lag and G+ losers (net %)")]
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
