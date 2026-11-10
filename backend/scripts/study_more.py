"""Study 2026-11-10 (owner: "research more, more comprehensively"). Read-only. Themes from the research:
 1. fees vs stop distance for the bot's own 18 strategies (stop-distance buckets),
 2. data snooping: keep only strategy x timeframe pairs that were positive before, test on later data (walk-forward),
 3. top-40 vs volatile-30 coins for the bot's strategies,
 4. pairs trading (1h, most correlated pairs picked in the first half, traded in the second),
 5. day of the week (4h, ~14 months),
 6. funding-rate extremes as a contrarian signal (Toobit funding history, 1h prices).
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

from study import FEES, Tally, signals_of, walk  # noqa: E402
from study_new import COST, pct  # noqa: E402
from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG, SHORT  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "1h": 4000, "4h": 2500}


def bucket(risk_pct: float) -> str:
    for edge, name in ((3, "2.4-3%"), (4, "3-4%"), (6, "4-6%"), (10, "6-10%")):
        if risk_pct < edge:
            return name
    return ">10%"


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    fee = Tally()
    sets = Tally()
    rows = defaultdict(lambda: [[0, 0.0] for _ in range(3)])   # (set, tf, kind) -> thirds [n, sumR]
    p = Tally()
    hourly: dict[str, dict] = {}
    four: dict[str, list] = {}
    funding: dict[str, list] = {}
    try:
        top = [m.symbol for m in await service.top_markets(limit=40)]
        vol = [m.symbol for m in await service.volatile_markets(config.VOLATILE_COINS, config.VOLATILE_MIN_VOLUME)]
        ex = service.exchange
        for set_name, coins in (("top40", top), ("volatile30", vol)):
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
                    t0, t1 = c[0]["time"], c[-1]["time"]
                    mid = (t0 + t1) // 2
                    for s in signals_of(c, tf):
                        r = walk(c, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"], [], FEES.taker)
                        half = 0 if s["time"] < mid else 1
                        third = min(2, int((s["time"] - t0) / max(1, t1 - t0) * 3))
                        x = rows[(set_name, tf, s["kind"])][third]
                        x[0] += 1
                        x[1] += r
                        sets.add(f"{set_name} {tf} all bot strategies", half, r)
                        if set_name == "top40":
                            fee.add(f"{tf} stop {bucket(abs(s['entry'] - s['stop']) / s['entry'] * 100)}", half, r)
                    if set_name == "top40" and tf == "1h":
                        hourly[symbol] = {k["time"]: k for k in c}
                    if set_name == "top40" and tf == "4h":
                        four[symbol] = c
                if set_name == "top40":
                    try:
                        since = (min(hourly[symbol]) if symbol in hourly else 0) * 1000
                        rates = await ex.fetch_funding_rate_history(symbol, since=since, limit=1000)
                        funding[symbol] = sorted((int(x["timestamp"] / 1000), x["fundingRate"]) for x in rates
                                                 if x.get("fundingRate") is not None)
                    except Exception as error:
                        print("  funding skip", error, flush=True)
    finally:
        await service.close()

    lines = ["# More research — bot strategies, selection, pairs, weekdays, funding (Toobit fees)"]
    lines += fee.report("1. Bot's 18 strategies (top 40) by stop distance")
    lines += sets.report("3. Bot's 18 strategies: top-40 vs volatile-30")

    # 2. walk-forward selection: pick (set, tf, kind) positive in third k (n >= 20), result in third k+1
    sel = defaultdict(lambda: [0, 0.0])
    for (set_name, tf, kind), th in rows.items():
        for k in (0, 1):
            n, s = th[k]
            nn, ss = th[k + 1]
            if not nn:
                continue
            key = (set_name, tf)
            sel[(key, "all")][0] += nn
            sel[(key, "all")][1] += ss
            if n >= 20 and s / n > 0:
                sel[(key, "picked")][0] += nn
                sel[(key, "picked")][1] += ss
            elif n >= 20:
                sel[(key, "dropped")][0] += nn
                sel[(key, "dropped")][1] += ss
    lines.append("\n## 2. Walk-forward: strategies that were positive in one third, traded in the next (avgR there)")
    lines.append("set tf | all | picked (positive before) | dropped")
    for key in sorted({k for k, _ in sel}):
        def f(w):
            n, s = sel[(key, w)]
            return f"{s / n:+.3f} (n={n})" if n else "-"
        lines.append(f"{key[0]} {key[1]} | {f('all')} | {f('picked')} | {f('dropped')}")
    best = sorted(((th[2][1] / th[2][0], k, th) for k, th in rows.items() if th[0][0] >= 20 and th[1][0] >= 20 and th[2][0] >= 20
                   and all(x[1] > 0 for x in th)), reverse=True)
    lines.append("\nstrategy x timeframe positive in all three thirds (avgR per third):")
    for _, k, th in best[:25]:
        lines.append(f"{k[0]} {k[1]} {k[2]}: " + " / ".join(f"{x[1] / x[0]:+.3f} (n={x[0]})" for x in th))

    # 4. pairs trading on 1h
    syms = [s for s in hourly if len(hourly[s]) > 3000]
    if len(syms) > 5:
        common = sorted(set.intersection(*(set(hourly[s]) for s in syms)))
        if len(common) > 2000:
            half_t = common[len(common) // 2]
            lp = {s: [math.log(hourly[s][t]["close"]) for t in common] for s in syms}
            h = len([t for t in common if t < half_t])

            def corr(a, b):
                ra = [a[i + 1] - a[i] for i in range(h - 1)]
                rb = [b[i + 1] - b[i] for i in range(h - 1)]
                ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
                cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
                va = sum((x - ma) ** 2 for x in ra)
                vb = sum((y - mb) ** 2 for y in rb)
                return cov / math.sqrt(va * vb) if va and vb else 0
            pairs = sorted(((corr(lp[a], lp[b]), a, b) for i, a in enumerate(syms) for b in syms[i + 1:]), reverse=True)[:10]
            lines.append("\n## 4. Pairs (1h): 10 most correlated in half 1 -> " +
                         ", ".join(f"{a.split('/')[0]}-{b.split('/')[0]} {r:.2f}" for r, a, b in pairs))
            W = 100
            for r, a, b in pairs:
                spread = [x - y for x, y in zip(lp[a], lp[b])]
                i = W
                while i < len(common) - 1:
                    win = spread[i - W:i]
                    m = sum(win) / W
                    sd = math.sqrt(sum((x - m) ** 2 for x in win) / W)
                    if sd <= 0:
                        i += 1
                        continue
                    z = (spread[i] - m) / sd
                    if abs(z) < 2:
                        i += 1
                        continue
                    d = -1 if z > 0 else 1        # z > 0: a rich -> short a, long b
                    j = i + 1
                    while j < min(len(common) - 1, i + 72):
                        zj = (spread[j] - m) / sd
                        if abs(zj) < 0.5 or abs(zj) > 4:
                            break
                        j += 1
                    gross = d * ((spread[j] - spread[i]) * 100) / 2      # half the money in each leg, %
                    net = gross - 2 * COST / 2 * 1                         # two legs in and out: 0.24% on the half sizes -> 0.12% on the whole
                    half = 0 if common[i] < half_t else 1
                    p.add("4. pairs z>2, exit z<0.5 / >4 / 72h (whole-position %)", half, net)
                    i = j + 1

    # 5. day of the week (4h, UTC days)
    by_day = defaultdict(lambda: [[], []])
    for s, c in four.items():
        mid = c[len(c) // 2]["time"]
        days = defaultdict(list)
        for k in c:
            days[k["time"] // 86400].append(k)
        for dnum, ks in days.items():
            if len(ks) < 6:
                continue
            r = (ks[-1]["close"] - ks[0]["open"]) / ks[0]["open"] * 100
            by_day[(dnum + 3) % 7][0 if ks[0]["time"] < mid else 1].append(r)   # 0 = Monday
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines.append("\n## 5. Day of the week (top 40, 4h data, UTC day open->close %, before fees): half 1 / half 2")
    for dw in range(7):
        a, b = by_day[dw]
        if a and b:
            lines.append(f"{names[dw]}: {sum(a) / len(a):+.3f} / {sum(b) / len(b):+.3f}  (n={len(a)}/{len(b)})")

    # 6. funding extremes (contrarian, hold 24h from the next hour's open)
    for s, rates in funding.items():
        hc = hourly.get(s)
        if not hc or len(rates) < 40:
            continue
        times = sorted(hc)
        mid = times[len(times) // 2]
        last_entry = 0
        for n in range(30, len(rates)):
            tm, fr = rates[n]
            past = [x for _, x in rates[n - 30:n]]
            m = sum(past) / 30
            sd = math.sqrt(sum((x - m) ** 2 for x in past) / 30)
            if sd <= 0:
                continue
            z = (fr - m) / sd
            start = (tm // 3600 + 1) * 3600
            if abs(z) < 2 or start < last_entry + 86400 or start not in hc or start + 86400 not in hc:
                continue
            last_entry = start
            side = SHORT if z > 0 else LONG
            r = pct(side, hc[start]["open"], hc[start + 86400]["open"])
            half = 0 if start < mid else 1
            p.add(f"6. funding z>2 contrarian, 24h ({'high funding -> short' if z > 0 else 'low funding -> long'})", half, r)
            if fr > 0.0005 or fr < -0.0005:
                p.add("6. funding beyond +/-0.05% contrarian, 24h", half, r)
    lines += [x.replace("avgR", "avg%") for x in p.report("4 and 6 (net %)")]
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
