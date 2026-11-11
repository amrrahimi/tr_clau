"""Study 2026-11-11 (owner): setups from four schools, coded from their published definitions, on our coins.
  ICT (Michael Huddleston): BOS (close beyond the last swing in the trend's direction) and CHoCH (the first close
      beyond the last swing against the trend).
  RTM (iFmyante): QM (quasimodo: higher high, then a close below the higher low -> sell limit at the left shoulder),
      FTR/FL (the base before a move that broke a swing high; buy limit at its first return),
      CAPS (the same, only when price comes back slowly in compression).
  YTC (Lance Beggs): BOF (breakout failure at a swing level), TST (test of the level without a break, reversal
      candle), BPB (breakout pullback: break, pull back to the level, hold). The owner's "BOP" read as BPB.
  Ichimoku (Goichi Hosoda): Tenkan/Kijun golden cross alone, + above the cloud, + Chikou above the price 26 back.
Swings: fractals of 3 candles each side (known 3 candles later). Stop as each school places it, target 2R,
bot's fee rule (stop >= 20 x round-trip fee), market entries taker / limit entries maker. Two time halves.
The bot's 18 strategies on the same candles for comparison. Coins: volatile 30 + top 40; 5m / 15m / 30m / 1h.
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
from app.indicators import atr as atr_s  # noqa: E402
from app.paper import FEE_RATIO_BY_TF  # noqa: E402
from app.strategies import LONG, SHORT, fee_ok  # noqa: E402

TF = {"5m": 5000, "15m": 5000, "30m": 4000, "1h": 4000}
K = 3            # swing: higher / lower than 3 candles on each side
RR = 2.0
WAIT = 40        # candles a limit order waits


def swings(c):
    """[(known_at, index, 'H'|'L', price)] in time order, alternating (the more extreme one kept)."""
    out = []
    n = len(c)
    for i in range(K, n - K):
        h, l = c[i]["high"], c[i]["low"]
        is_h = all(h > c[j]["high"] for j in range(i - K, i)) and all(h >= c[j]["high"] for j in range(i + 1, i + K + 1))
        is_l = all(l < c[j]["low"] for j in range(i - K, i)) and all(l <= c[j]["low"] for j in range(i + 1, i + K + 1))
        for typ, px, ok in (("H", h, is_h), ("L", l, is_l)):
            if not ok:
                continue
            if out and out[-1][2] == typ:
                if (typ == "H" and px > out[-1][3]) or (typ == "L" and px < out[-1][3]):
                    out[-1] = (i + K, i, typ, px)
                continue
            out.append((i + K, i, typ, px))
    return out


class Run:
    def __init__(self, c, tf, mid, add):
        self.c, self.tf, self.mid, self.add = c, tf, mid, add
        self.a = atr_s([x["high"] for x in c], [x["low"] for x in c], [x["close"] for x in c], 14)

    def market(self, name, j, side, stop):
        """Signal on the close of candle j: enter at the next open."""
        c = self.c
        if j + 2 >= len(c):
            return
        entry = c[j + 1]["open"]
        if (side == LONG and stop >= entry) or (side == SHORT and stop <= entry):
            return
        if not fee_ok(entry, stop, FEES, FEE_RATIO_BY_TF[self.tf]):
            return
        k = 1 if side == LONG else -1
        target = entry + k * RR * abs(entry - stop)
        r = walk(c, j + 1, side, entry, stop, target, [], FEES.taker)
        self.add(name, 0 if c[j]["time"] < self.mid else 1, r)

    def limit(self, name, j, side, level, stop, invalid=None):
        """Limit at `level` from candle j+1 for WAIT candles; cancelled if `invalid` is crossed first."""
        c = self.c
        if (side == LONG and stop >= level) or (side == SHORT and stop <= level):
            return
        if not fee_ok(level, stop, FEES, FEE_RATIO_BY_TF[self.tf]):
            return
        k = 1 if side == LONG else -1
        for m in range(j + 1, min(len(c) - 1, j + 1 + WAIT)):
            x = c[m]
            if (x["low"] <= level) if side == LONG else (x["high"] >= level):
                fill = min(level, x["open"]) if side == LONG else max(level, x["open"])
                risk = abs(fill - stop)
                if (x["low"] <= stop) if side == LONG else (x["high"] >= stop):
                    r = R(side, fill, stop, risk, FEES.maker, FEES.taker)
                else:
                    r = walk(c, m + 1, side, fill, stop, fill + k * RR * risk, [], FEES.maker)
                self.add(name, 0 if c[j]["time"] < self.mid else 1, r)
                return
            if invalid is not None and ((x["high"] >= invalid) if side == LONG else (x["low"] <= invalid)):
                return      # it ran away first (long: up to `invalid`) -> no trade

    # ---------------------------------------------------------------- ICT
    def ict(self, sw):
        c = self.c
        bias = None
        last_h = last_l = None
        si = 0
        broken_h = broken_l = None
        for j in range(1, len(c) - 2):
            while si < len(sw) and sw[si][0] <= j:
                if sw[si][2] == "H":
                    last_h = sw[si]
                else:
                    last_l = sw[si]
                si += 1
            cl, prev = c[j]["close"], c[j - 1]["close"]
            if last_h and last_h is not broken_h and cl > last_h[3] >= prev:
                broken_h = last_h
                kind = "BOS" if bias in (None, "up") else "CHoCH"
                bias = "up"
                if kind == "BOS" and last_l:
                    stop = last_l[3]
                else:
                    stop = min(x["low"] for x in c[last_h[1]:j + 1])
                self.market(f"ICT {kind}", j, LONG, stop)
            if last_l and last_l is not broken_l and cl < last_l[3] <= prev:
                broken_l = last_l
                kind = "BOS" if bias in (None, "down") else "CHoCH"
                bias = "down"
                if kind == "BOS" and last_h:
                    stop = last_h[3]
                else:
                    stop = max(x["high"] for x in c[last_l[1]:j + 1])
                self.market(f"ICT {kind}", j, SHORT, stop)

    # ---------------------------------------------------------------- RTM
    def qm(self, sw):
        c = self.c
        done = set()
        for t in range(2, len(sw)):
            a, b, d = sw[t - 2], sw[t - 1], sw[t]
            if a[2] == "H" and b[2] == "L" and d[2] == "H" and d[3] > a[3]:
                side, shoulder, neck, head = SHORT, a[3], b[3], d[3]
            elif a[2] == "L" and b[2] == "H" and d[2] == "L" and d[3] < a[3]:
                side, shoulder, neck, head = LONG, a[3], b[3], d[3]
            else:
                continue
            end = sw[t + 1][0] if t + 1 < len(sw) else len(c) - 2
            for j in range(d[0], min(end + 20, len(c) - 2)):
                broke = c[j]["close"] < neck if side == SHORT else c[j]["close"] > neck
                if broke and d[1] not in done:
                    done.add(d[1])
                    pad = 0.1 * abs(head - shoulder)
                    stop = head + pad if side == SHORT else head - pad
                    self.limit("RTM QM", j, side, shoulder, stop, invalid=None)
                    break
                if (side == SHORT and c[j]["high"] > head) or (side == LONG and c[j]["low"] < head):
                    break

    def ftr(self, sw):
        """Base before a strong move that closed beyond the last swing; first return to it (FTR/FL), and the
        same only when the return comes in compression (CAPS)."""
        c, a = self.c, self.a
        last_h = last_l = None
        si = 0
        used = set()
        for j in range(20, len(c) - 2):
            while si < len(sw) and sw[si][0] <= j:
                if sw[si][2] == "H":
                    last_h = sw[si]
                else:
                    last_l = sw[si]
                si += 1
            if a[j] is None:
                continue
            x = c[j]
            body = abs(x["close"] - x["open"])
            for side, lvl in ((LONG, last_h), (SHORT, last_l)):
                if not lvl or lvl[1] in used or body < 1.2 * a[j]:
                    continue
                up = side == LONG
                if not ((x["close"] > lvl[3] >= c[j - 1]["close"]) if up else (x["close"] < lvl[3] <= c[j - 1]["close"])):
                    continue
                s = j
                while s - 1 > j - 5 and ((c[s - 1]["close"] > c[s - 1]["open"]) if up else (c[s - 1]["close"] < c[s - 1]["open"])) \
                        and abs(c[s - 1]["close"] - c[s - 1]["open"]) > 0.5 * a[j]:
                    s -= 1
                base = c[s - 1]
                if base["high"] - base["low"] > 1.2 * a[j]:
                    continue
                used.add(lvl[1])
                proximal = base["high"] if up else base["low"]
                distal = base["low"] if up else base["high"]
                pad = 0.1 * a[j]
                stop = distal - pad if up else distal + pad
                self.limit("RTM FTR/FL", j, side, proximal, stop)
                # CAPS: first return only if the 5 candles before the touch are a compression
                for m in range(j + 1, min(len(c) - 1, j + 1 + WAIT)):
                    touch = c[m]["low"] <= proximal if up else c[m]["high"] >= proximal
                    if touch:
                        prev5 = c[max(j + 1, m - 5):m]
                        if len(prev5) >= 4 and a[m] is not None:
                            small = sum(y["high"] - y["low"] for y in prev5) / len(prev5) <= 0.9 * a[m]
                            stair = sum(1 for p, q in zip(prev5, prev5[1:])
                                        if ((q["high"] < p["high"]) if up else (q["low"] > p["low"]))) >= 2
                            if small and stair:
                                self.limit("RTM CAPS (FTR + compression)", m - 1, side, proximal, stop)
                        break

    # ---------------------------------------------------------------- YTC
    def ytc(self, sw):
        c, a = self.c, self.a
        last_h = last_l = None
        si = 0
        used = defaultdict(set)
        broke_at = {}
        for j in range(20, len(c) - 2):
            while si < len(sw) and sw[si][0] <= j:
                if sw[si][2] == "H":
                    last_h = sw[si]
                else:
                    last_l = sw[si]
                si += 1
            if a[j] is None:
                continue
            x, p = c[j], c[j - 1]
            for lvl, res in ((last_h, True), (last_l, False)):
                if not lvl or j - lvl[1] > 60:
                    continue
                L = lvl[3]
                key = lvl[1]
                if res:
                    # BOF: through the resistance and back below it (same candle or the next)
                    if key not in used["BOF"] and x["close"] < L and (x["high"] > L or p["close"] > L):
                        used["BOF"].add(key)
                        self.market("YTC BOF", j, SHORT, max(x["high"], p["high"]) + 0.1 * a[j])
                    # TST: comes up to it without breaking, bearish candle closing in its lower half
                    elif key not in used["TST"] and L - 0.3 * a[j] <= x["high"] <= L and x["close"] < x["open"] \
                            and x["close"] < (x["high"] + x["low"]) / 2:
                        used["TST"].add(key)
                        self.market("YTC TST", j, SHORT, L + 0.3 * a[j])
                    # BPB: closes above it, later dips back to it and holds
                    if x["close"] > L >= p["close"]:
                        broke_at[("H", key)] = j
                    b = broke_at.get(("H", key))
                    if b is not None and key not in used["BPB"] and b < j <= b + 10 and x["low"] <= L + 0.2 * a[j] \
                            and x["close"] > L and x["close"] > x["open"]:
                        used["BPB"].add(key)
                        self.market("YTC BPB", j, LONG, min(x["low"], L) - 0.2 * a[j])
                else:
                    if key not in used["BOF-"] and x["close"] > L and (x["low"] < L or p["close"] < L):
                        used["BOF-"].add(key)
                        self.market("YTC BOF", j, LONG, min(x["low"], p["low"]) - 0.1 * a[j])
                    elif key not in used["TST-"] and L <= x["low"] <= L + 0.3 * a[j] and x["close"] > x["open"] \
                            and x["close"] > (x["high"] + x["low"]) / 2:
                        used["TST-"].add(key)
                        self.market("YTC TST", j, LONG, L - 0.3 * a[j])
                    if x["close"] < L <= p["close"]:
                        broke_at[("L", key)] = j
                    b = broke_at.get(("L", key))
                    if b is not None and key not in used["BPB-"] and b < j <= b + 10 and x["high"] >= L - 0.2 * a[j] \
                            and x["close"] < L and x["close"] < x["open"]:
                        used["BPB-"].add(key)
                        self.market("YTC BPB", j, SHORT, max(x["high"], L) + 0.2 * a[j])

    # ---------------------------------------------------------------- Ichimoku
    def ichimoku(self):
        c, a = self.c, self.a
        n = len(c)
        hi = [x["high"] for x in c]
        lo = [x["low"] for x in c]

        def mid(i, p):
            return (max(hi[i - p + 1:i + 1]) + min(lo[i - p + 1:i + 1])) / 2 if i >= p - 1 else None
        ten = [mid(i, 9) for i in range(n)]
        kij = [mid(i, 26) for i in range(n)]
        sb = [mid(i, 52) for i in range(n)]
        for j in range(80, n - 2):
            if None in (ten[j], kij[j], ten[j - 1], kij[j - 1], a[j]):
                continue
            up = ten[j] > kij[j] and ten[j - 1] <= kij[j - 1]
            down = ten[j] < kij[j] and ten[j - 1] >= kij[j - 1]
            if not (up or down):
                continue
            side = LONG if up else SHORT
            k = 1 if up else -1
            span_a = (ten[j - 26] + kij[j - 26]) / 2
            span_b = sb[j - 26]
            top, bottom = max(span_a, span_b), min(span_a, span_b)
            cl = c[j]["close"]
            cloud = cl > top if up else cl < bottom
            chikou = cl > c[j - 26]["high"] if up else cl < c[j - 26]["low"]
            stop = kij[j] - k * 0.2 * a[j]
            if abs(cl - stop) < 0.5 * a[j]:
                stop = cl - k * 1.5 * a[j]
            self.market("Ichimoku TK golden cross only", j, side, stop)
            if cloud:
                self.market("Ichimoku TK cross + above cloud", j, side, stop)
                if chikou:
                    self.market("Ichimoku TK cross + cloud + Chikou", j, side, stop)


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    acc = defaultdict(lambda: [[0, 0.0, 0], [0, 0.0, 0]])
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

                    def add(name, half, r, key=key):
                        x = acc[(key, name)][half]
                        x[0] += 1
                        x[1] += r
                        x[2] += r > 0

                    run = Run(c, tf, mid, add)
                    sw = swings(c)
                    run.ict(sw)
                    run.qm(sw)
                    run.ftr(sw)
                    run.ytc(sw)
                    run.ichimoku()
                    for s in signals_of(c, tf):
                        r = walk(c, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"], [], FEES.taker)
                        add("~ bot's 18 strategies (comparison)", 0 if s["time"] < mid else 1, r)
    finally:
        await service.close()
    lines = ["# Four schools on our coins: avg R per trade (half 1 / half 2), trades, won %, total R"]
    last = None
    for key, name in sorted(acc):
        if key != last:
            lines.append(f"\n## {key}")
            last = key
        h = acc[(key, name)]
        n = h[0][0] + h[1][0]
        f = lambda x: f"{x[1] / x[0]:+.3f}" if x[0] else "-"
        lines.append(f"{name}: {(h[0][1] + h[1][1]) / n:+.3f} ({f(h[0])} / {f(h[1])}) n={n} won {(h[0][2] + h[1][2]) / n * 100:.0f}% "
                     f"total {h[0][1] + h[1][1]:+.0f}R")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
