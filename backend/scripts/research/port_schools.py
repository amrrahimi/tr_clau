"""Owner 2026-11-13: account test before adding the schools' setups to the proven set, and a cap on same-side trades.
Trades with the research harness (bot rules: next-open entry, fee rule, break-even at 50% on 1h / 4h, worst case
inside a candle): the proven set as built (PROVEN_BY_TF, PROVEN_TUNING, market-state rule) and the candidates
from study_schools28.py: Ichimoku TK cross + cloud + Chikou (4h), ICT CHoCH (4h), RTM QM (1h; its limit entry is
taken here as a market entry at the open after the limit would have filled - an approximation).
Account: 0.5% risk (6% budget / 12 places), one trade per coin, 6 h pause after a stop, 5 random orders of
same-time signals; whole period and second half."""
import os, sys, random, numpy as np, multiprocessing as mp
from dataclasses import dataclass
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from lib import load, as_candles, coins, run, summarize
from app import paper, regime
from app.strategies import STRATEGIES, allowed_by_state, parse_params
import study_schools as S

STEP = {"1h": 3600, "4h": 14400}


@dataclass
class Sig:
    index: int
    side: str
    stop_price: Optional[float] = None
    stop_distance: Optional[float] = None
    target_price: Optional[float] = None
    reward: Optional[float] = None


class Collect(S.Run):
    """The schools' setups as signals (no simulation here)."""
    def __init__(self, c, tf):
        super().__init__(c, tf, 0, None)
        self.out = {}

    def market(self, name, j, side, stop):
        self.out.setdefault(name, []).append(Sig(j, side, stop_price=stop, reward=2.0))

    def limit(self, name, j, side, level, stop, invalid=None):
        c = self.c
        for m in range(j + 1, min(len(c) - 1, j + 1 + S.WAIT)):
            if (c[m]["low"] <= level) if side == "long" else (c[m]["high"] >= level):
                self.market(name, m, side, stop)
                return


def one(sym):
    out = []
    for tf in ("1h", "4h"):
        a = load(sym, tf)
        if len(a) < 400:
            continue
        cand = as_candles(a)
        rows = [{"high": x[2], "low": x[3], "close": x[4]} for x in a]
        states, _, _ = regime.series(rows, "daily")
        for k in paper.PROVEN_BY_TF[tf]:
            st = STRATEGIES[k]
            sigs = st.signals(cand, parse_params(k, paper.PROVEN_TUNING.get(tf, {}).get(k, {}), "daily"))
            sigs = [x for x in sigs if allowed_by_state(x, states[x.index], st.states)]
            for r in run(a, sigs, be=0.5):
                out.append(("proven", k, tf, sym, a[int(r[0]), 0], a[int(r[1]), 0] + STEP[tf], r[2], r[3]))
        c = [{"time": int(x[0]), "open": x[1], "high": x[2], "low": x[3], "close": x[4], "volume": x[5]} for x in a]
        col = Collect(c, tf)
        sw = S.swings(c)
        if tf == "4h":
            col.ict(sw)
            col.ichimoku()
            want = {"ICT CHoCH": "choch", "Ichimoku TK cross + cloud + Chikou": "ichimoku_full"}
        else:
            col.qm(sw)
            want = {"RTM QM": "qm"}
        for name, key in want.items():
            for r in run(a, col.out.get(name, []), be=0.5):
                out.append(("new", key, tf, sym, a[int(r[0]), 0], a[int(r[1]), 0] + STEP[tf], r[2], r[3]))
    return out


def simulate(rows, max_open=12, risk=0.005, pause_h=6, side_cap=0, seed=0, start=None):
    rnd = random.Random(seed)
    rows = sorted(rows, key=lambda r: (r[4], rnd.random()))
    eq = peak = 1.0; dd = 0.0; open_ = []; paused = {}; n = w = 0; rs = []; months = {}
    for _, k, tf, sym, t0, t1, d, R in rows:
        if start and t0 < start:
            continue
        for p in sorted([p for p in open_ if p[0] <= t0]):
            eq += p[2] * p[3]; open_.remove(p); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
            months[int(p[0] // (30 * 86400))] = eq
            if p[2] <= -0.9:
                paused[p[1]] = p[0] + pause_h * 3600
        if len(open_) >= max_open or any(p[1] == sym for p in open_) or paused.get(sym, 0) > t0:
            continue
        if side_cap and sum(1 for p in open_ if p[4] == d) >= side_cap:
            continue
        open_.append((t1, sym, R, eq * risk, d)); n += 1; w += R > 0; rs.append(R)
    for p in open_:
        eq += p[2] * p[3]
    peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    vals = [1.0] + [months[m] for m in sorted(months)]
    mr = np.diff(vals) / np.array(vals[:-1]) * 100 if len(vals) > 1 else np.array([0.0])
    return eq, n, w, dd, np.array(rs), mr


def report(name, rows, **kw):
    res = [simulate(rows, seed=s, **kw) for s in range(5)]
    eq = [r[0] for r in res]; _, n, w, _, rs, mr = res[0]
    print(f"{name:58s} final x{np.mean(eq):5.2f} ({min(eq):.2f}-{max(eq):.2f}) trades={n:5d} win={w / max(n, 1) * 100:4.1f}% "
          f"avgR={rs.mean() if len(rs) else 0:+.3f} maxDD={np.mean([r[3] for r in res]) * 100:4.1f}% "
          f"months+ {np.mean(mr > 0) * 100:3.0f}% worst month {mr.min():+.1f}%", flush=True)


if __name__ == "__main__":
    with mp.Pool(4) as p:
        rows = [x for r in p.map(one, coins("all"), chunksize=1) for x in r]
    t = np.array([x[4] for x in rows]); mid = (t.min() + t.max()) / 2
    R = np.array([x[7] for x in rows])
    print("== trades per strategy (bot rules, all coins) ==")
    for key in sorted({(x[0], x[1], x[2]) for x in rows}):
        m = np.array([(x[0], x[1], x[2]) == key for x in rows])
        print(summarize(R[m], t[m], f"{key[0]} {key[2]} {key[1]}", split=mid))
    base = [x for x in rows if x[0] == "proven"]
    plus4 = base + [x for x in rows if x[0] == "new" and x[2] == "4h"]
    plus_all = base + [x for x in rows if x[0] == "new"]
    WEAK4 = {"momentum", "structure_break", "keltner_breakout", "volume_breakout", "turtle"}
    lean = [x for x in base if not (x[2] == "4h" and x[1] in WEAK4)]
    lean_ichi = lean + [x for x in rows if x[0] == "new" and x[1] == "ichimoku_full"]
    base_ichi = base + [x for x in rows if x[0] == "new" and x[1] == "ichimoku_full"]
    print("\n== swap: the five weakest 4h strategies out, Ichimoku full in (in-sample choice) ==")
    for start, label in ((None, "whole"), (mid, "2nd half")):
        report(f"[{label}] proven set as built", base, start=start)
        report(f"[{label}] + Ichimoku full only", base_ichi, start=start)
        report(f"[{label}] without the 5 weakest on 4h", lean, start=start)
        report(f"[{label}] without the 5 weakest on 4h + Ichimoku full", lean_ichi, start=start)
    sys.exit(0)
    print("\n== account: 0.5% risk, 12 places, one per coin, 6 h pause ==")
    for start, label in ((None, "whole"), (mid, "2nd half")):
        report(f"[{label}] proven set as built", base, start=start)
        report(f"[{label}] + Ichimoku full + CHoCH on 4h", plus4, start=start)
        report(f"[{label}] + Ichimoku full + CHoCH on 4h + QM on 1h", plus_all, start=start)
        for cap in (4, 6, 8):
            report(f"[{label}] proven set, at most {cap} trades on one side", base, start=start, side_cap=cap)
            report(f"[{label}] + new 4h + QM, at most {cap} on one side", plus_all, start=start, side_cap=cap)
        report(f"[{label}] proven set, 10 places (the owner's max)", base, start=start, max_open=10)
        report(f"[{label}] + new 4h + QM, 10 places", plus_all, start=start, max_open=10)
