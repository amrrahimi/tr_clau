"""Study 2026-11-10 (owner: "find new methods and strategies and test them"). Read-only, 40 coins, after Toobit fees,
two time halves. None of these is among the bot's 18 strategies.

 A. Larry Williams volatility breakout (1h candles, UTC day): break of day open +/- k x yesterday's range,
    stop at the day open, exit at the day's end.
 B. Hour of the day: the best / worst hours of the first half traded in the second half (out of sample).
 C. 12-hour session momentum / reversal at 08:00 and 20:00 UTC (4h candles).
 D. Connors RSI(2) pullback in the 200-SMA trend, exit above / below the 5-SMA (stop 2.5 ATR).
 E. Fade an exhaustion candle (range > 3 ATR, closes at its extreme), stop beyond it.
 F. Lance-like Fibonacci trend: range of the last N candles, flip up above 0.786 / down below 0.236, stop at 0.5.
 G. Cross-sectional momentum / reversal across the 40 coins (4h): daily, long the top 5, short the bottom 5.
 H. New York opening range (first 30 min, 15m candles): breakout, stop at the other side, exit at 16:00 NY.
R = multiples of the risk; % = net % per trade (both sides 0.06% taker).
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import COINS, FEES, R, Tally  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.indicators import atr as atr_s, highest, lowest, rsi as rsi_s, sma as sma_s  # noqa: E402
from app.paper import FEE_RATIO_BY_TF  # noqa: E402
from app.strategies import LONG, SHORT, fee_ok  # noqa: E402

TF = {"15m": 5000, "1h": 4000, "4h": 2500}
COST = 2 * FEES.taker   # % round trip
NY = ZoneInfo("America/New_York")


def trade(c, start, side, entry, stop, target=None, limit=400, steps=(), exit_at=None, fee_in=FEES.taker) -> float:
    """From candle `start` on: stop first, then target (maker), then lock steps, then exit_at(i) -> close of i."""
    long_ = side == LONG
    risk = abs(entry - stop)
    s = stop
    done = set()
    end = min(len(c), start + limit)
    for i in range(start, end):
        k = c[i]
        if (k["low"] <= s) if long_ else (k["high"] >= s):
            gapped = (k["open"] < s) if long_ else (k["open"] > s)
            return R(side, entry, k["open"] if gapped else s, risk, fee_in, FEES.taker)
        if target is not None and ((k["high"] >= target) if long_ else (k["low"] <= target)):
            return R(side, entry, target, risk, fee_in, FEES.maker)
        for n, (at, to) in enumerate(steps):
            best = (k["high"] - entry) if long_ else (entry - k["low"])
            if n not in done and best >= at * risk:
                done.add(n)
                new = entry + (to * risk if long_ else -to * risk)
                if (new > s) if long_ else (new < s):
                    s = new
        if exit_at is not None and exit_at(i):
            return R(side, entry, k["close"], risk, fee_in, FEES.taker)
    return R(side, entry, c[end - 1]["close"], risk, fee_in, FEES.taker)


def pct(side, a, b) -> float:
    return ((b - a) / a * 100) * (1 if side == LONG else -1) - COST


def day(t: int) -> int:
    return t // 86400


# ---------------- A. volatility breakout (1h) ----------------
def vol_breakout(c, mid, t: Tally):
    days = defaultdict(list)
    for n, k in enumerate(c):
        days[day(k["time"])].append(n)
    keys = sorted(days)
    for d0, d1 in zip(keys, keys[1:]):
        prev, cur = days[d0], days[d1]
        if len(prev) < 24 or len(cur) < 24:
            continue
        rng = max(c[i]["high"] for i in prev) - min(c[i]["low"] for i in prev)
        o = c[cur[0]]["open"]
        trend_up = c[prev[-1]]["close"] > c[prev[0]]["open"]
        half = 0 if c[cur[0]]["time"] < mid else 1
        for k in (0.5, 0.7):
            up, dn = o + k * rng, o - k * rng
            for n in cur:
                x = c[n]
                side = LONG if x["high"] >= up else SHORT if x["low"] <= dn else None
                if side is None:
                    continue
                if x["high"] >= up and x["low"] <= dn:
                    break   # both in one candle: unknown order, skip the day
                lvl = up if side == LONG else dn
                entry = (max(lvl, x["open"]) if side == LONG else min(lvl, x["open"]))
                if not fee_ok(entry, o, FEES, FEE_RATIO_BY_TF["1h"]):
                    break
                last = cur[-1]
                if (x["close"] <= o) if side == LONG else (x["close"] >= o):
                    r = R(side, entry, o, abs(entry - o), FEES.taker, FEES.taker)
                else:
                    r = trade(c, n + 1, side, entry, o, None, limit=last - n) if n < last else \
                        R(side, entry, x["close"], abs(entry - o), FEES.taker, FEES.taker)
                t.add(f"A k={k} both sides", half, r)
                if side == LONG:
                    t.add(f"A k={k} long only", half, r)
                if (side == LONG) == trend_up:
                    t.add(f"A k={k} with yesterday's direction", half, r)
                break


# ---------------- D. RSI(2) ----------------
def rsi2(c, tf, mid, t: Tally):
    cl = [x["close"] for x in c]
    r2 = rsi_s(cl, 2)
    s200, s5 = sma_s(cl, 200), sma_s(cl, 5)
    a = atr_s([x["high"] for x in c], [x["low"] for x in c], cl, 14)
    i = 201
    while i < len(c) - 2:
        if None in (r2[i], s200[i], s5[i], a[i]):
            i += 1
            continue
        side = LONG if (r2[i] < 10 and cl[i] > s200[i]) else SHORT if (r2[i] > 90 and cl[i] < s200[i]) else None
        if side is None:
            i += 1
            continue
        entry = c[i + 1]["open"]
        stop = entry - 2.5 * a[i] if side == LONG else entry + 2.5 * a[i]
        if not fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF[tf]):
            i += 1
            continue
        out = lambda j: s5[j] is not None and ((cl[j] > s5[j]) if side == LONG else (cl[j] < s5[j]))
        half = 0 if c[i]["time"] < mid else 1
        t.add(f"D {tf} RSI2 exit at SMA5", half, trade(c, i + 1, side, entry, stop, None, 20, exit_at=out))
        t.add(f"D {tf} RSI2 target 1R", half, trade(c, i + 1, side, entry, stop, entry + (a[i] * 2.5 if side == LONG else -a[i] * 2.5), 40))
        i += 3


# ---------------- E. exhaustion fade ----------------
def fade(c, tf, mid, t: Tally):
    a = atr_s([x["high"] for x in c], [x["low"] for x in c], [x["close"] for x in c], 14)
    for i in range(20, len(c) - 2):
        x = c[i]
        rng = x["high"] - x["low"]
        if a[i - 1] is None or rng < 3 * a[i - 1] or rng <= 0:
            continue
        pos = (x["close"] - x["low"]) / rng
        side = SHORT if pos > 0.8 else LONG if pos < 0.2 else None
        if side is None:
            continue
        entry = c[i + 1]["open"]
        stop = x["high"] + 0.1 * rng if side == SHORT else x["low"] - 0.1 * rng
        if (entry >= stop) if side == SHORT else (entry <= stop):
            continue
        risk = abs(entry - stop)
        if not fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF[tf]):
            continue
        d = 1 if side == LONG else -1
        half = 0 if x["time"] < mid else 1
        for k in (0.5, 1.0, 2.0):
            t.add(f"E {tf} fade 3ATR candle {k:g}R", half, trade(c, i + 1, side, entry, stop, entry + d * k * risk, 50))


# ---------------- F. Lance-like ----------------
def lance(c, tf, mid, t: Tally):
    cl = [x["close"] for x in c]
    for n in (50, 100):
        hs, ls = highest([x["high"] for x in c], n), lowest([x["low"] for x in c], n)
        state = None
        for i in range(n, len(c) - 2):
            hh, ll = hs[i], ls[i]
            if hh is None or ll is None:
                continue
            rng = hh - ll
            if rng <= 0:
                continue
            new = LONG if cl[i] > ll + 0.786 * rng else SHORT if cl[i] < ll + 0.236 * rng else state
            if new == state or state is None:
                state = new
                continue
            state = new
            entry = c[i + 1]["open"]
            stop = ll + 0.5 * rng
            if (entry <= stop) if new == LONG else (entry >= stop):
                continue
            if not fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF[tf]):
                continue
            risk = abs(entry - stop)
            d = 1 if new == LONG else -1
            half = 0 if c[i]["time"] < mid else 1
            side = new

            def flip(j, side=side, hs=hs, ls=ls):
                h, low = hs[j], ls[j]
                return (cl[j] < low + 0.236 * (h - low)) if side == LONG else (cl[j] > low + 0.786 * (h - low))
            t.add(f"F {tf} N={n} 2R", half, trade(c, i + 1, side, entry, stop, entry + d * 2 * risk, 300))
            t.add(f"F {tf} N={n} 4R + BE at 1R", half, trade(c, i + 1, side, entry, stop, entry + d * 4 * risk, 300,
                                                         steps=[(1.0, 0.0)]))
            t.add(f"F {tf} N={n} exit on flip", half, trade(c, i + 1, side, entry, stop, None, 600, exit_at=flip))


# ---------------- H. New York opening range (15m) ----------------
def orb(c, mid, t: Tally):
    days = defaultdict(list)
    for n, k in enumerate(c):
        local = datetime.fromtimestamp(k["time"], timezone.utc).astimezone(NY)
        mins = local.hour * 60 + local.minute
        if 570 <= mins < 960:   # 9:30-16:00
            days[local.date()].append(n)
    for d, idx in days.items():
        if len(idx) < 20:
            continue
        hi = max(c[i]["high"] for i in idx[:2])
        lo = min(c[i]["low"] for i in idx[:2])
        last = idx[-1]
        for n in idx[2:-1]:
            side = LONG if c[n]["close"] > hi else SHORT if c[n]["close"] < lo else None
            if side is None:
                continue
            entry = c[n + 1]["open"]
            stop = lo if side == LONG else hi
            if (entry <= stop) if side == LONG else (entry >= stop):
                break
            if not fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF["15m"]):
                break
            risk = abs(entry - stop)
            dd = 1 if side == LONG else -1
            half = 0 if c[n]["time"] < mid else 1
            lim = last - n
            t.add("H NY 30-min range: hold to 16:00", half, trade(c, n + 1, side, entry, stop, None, lim))
            t.add("H NY 30-min range: 1R", half, trade(c, n + 1, side, entry, stop, entry + dd * risk, lim))
            t.add("H NY 30-min range: 2R", half, trade(c, n + 1, side, entry, stop, entry + dd * 2 * risk, lim))
            break


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    t = Tally()                 # R
    p = Tally()                 # %
    hours = []                  # (time, hour, net % long)
    four = {}                   # symbol -> {time: candle}
    try:
        coins = [m.symbol for m in await service.top_markets(limit=COINS)]
        for num, symbol in enumerate(coins):
            print(f"[{num + 1}/{len(coins)}] {symbol}", flush=True)
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
                rsi2(c, tf, mid, t)
                fade(c, tf, mid, t)
                lance(c, tf, mid, t)
                if tf == "15m":
                    orb(c, mid, t)
                if tf == "1h":
                    vol_breakout(c, mid, t)
                    hours += [(k["time"], (k["time"] // 3600) % 24, (k["close"] - k["open"]) / k["open"] * 100) for k in c]
                if tf == "4h":
                    four[symbol] = {k["time"]: k for k in c}
                    # C. 12h sessions at 08:00 / 20:00 UTC
                    by = {k["time"]: k for k in c}
                    for k in c:
                        h = (k["time"] // 3600) % 24
                        if h not in (8, 20):
                            continue
                        a, b = by.get(k["time"] - 12 * 3600), by.get(k["time"] + 12 * 3600)
                        if a is None or b is None:
                            continue
                        past = k["open"] - a["open"]
                        if past == 0:
                            continue
                        half = 0 if k["time"] < mid else 1
                        mom = LONG if past > 0 else SHORT
                        rev = SHORT if past > 0 else LONG
                        p.add(f"C 12h momentum from {h:02d}:00", half, pct(mom, k["open"], b["open"]))
                        p.add(f"C 12h reversal from {h:02d}:00", half, pct(rev, k["open"], b["open"]))
    finally:
        await service.close()

    # B. hour of the day (1h): pick in half 1, trade in half 2
    if hours:
        ts = sorted(x[0] for x in hours)
        mid = ts[len(ts) // 2]
        first = defaultdict(list)
        for tm, h, r in hours:
            if tm < mid:
                first[h].append(r)
        mean = {h: sum(v) / len(v) for h, v in first.items()}
        best = sorted(mean, key=mean.get)[-2:]
        worst = sorted(mean, key=mean.get)[:2]
        lines_b = [f"B in half 1 best hours (UTC) {best} ({', '.join(f'{mean[h]:+.3f}%' for h in best)}), "
                   f"worst {worst} ({', '.join(f'{mean[h]:+.3f}%' for h in worst)}) before fees"]
        for tm, h, r in hours:
            half = 0 if tm < mid else 1
            if h in best:
                p.add("B best 2 hours long (picked in half 1)", half, r - COST)
            if h in worst:
                p.add("B worst 2 hours short (picked in half 1)", half, -r - COST)
            if h in (21, 22):
                p.add("B 21-22 UTC long (published BTC idea)", half, r - COST)
    else:
        lines_b = []

    # G. cross-sectional (4h): each day 00:00 UTC, rank by the past return, hold 1 day
    if four:
        times = sorted({tm for d in four.values() for tm in d if (tm // 3600) % 24 == 0})
        tmid = times[len(times) // 2] if times else 0
        for tm in times:
            for look, name in ((6, "1d"), (18, "3d"), (42, "7d")):
                rows = []
                for s, d in four.items():
                    now, past, nxt = d.get(tm), d.get(tm - look * 14400), d.get(tm + 6 * 14400)
                    if now and past and nxt:
                        rows.append(((now["open"] - past["open"]) / past["open"], now["open"], nxt["open"]))
                if len(rows) < 20:
                    continue
                rows.sort()
                half = 0 if tm < tmid else 1
                for ret, a, b in rows[-5:]:
                    p.add(f"G momentum {name}: long top 5", half, pct(LONG, a, b))
                    p.add(f"G reversal {name}: short top 5", half, pct(SHORT, a, b))
                for ret, a, b in rows[:5]:
                    p.add(f"G momentum {name}: short bottom 5", half, pct(SHORT, a, b))
                    p.add(f"G reversal {name}: long bottom 5", half, pct(LONG, a, b))

    lines = [f"# New strategies — {COINS} coins, Toobit fees (taker 0.06%, maker 0.02%)"]
    lines += t.report("In R (risk multiples): A, D, E, F, H")
    lines += [x.replace("avgR", "avg%") for x in p.report("In net % per trade (no stop): B, C, G")]
    lines += lines_b
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
