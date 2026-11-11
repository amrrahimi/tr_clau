"""The proven set as built now (per-timeframe tuning, priority order, 12 places x 0.5%) against before."""
import sys, random, numpy as np, multiprocessing as mp
from lib import *
from app import regime, paper
from app.strategies import STRATEGIES, allowed_by_state, parse_params
STEP = {"1h": 3600, "4h": 14400}
def one(args):
    sym, tuned = args; out = []
    for tf in ("1h", "4h"):
        a = load(sym, tf)
        if len(a) < 600: continue
        c = as_candles(a); rows = [{"high": x[2], "low": x[3], "close": x[4]} for x in a]
        states, _, _ = regime.series(rows, "daily")
        for rank, k in enumerate(paper.PROVEN_BY_TF[tf]):
            s = STRATEGIES[k]; over = paper.PROVEN_TUNING[tf].get(k, {}) if tuned else {}
            sg = [x for x in s.signals(c, parse_params(k, over, "daily")) if allowed_by_state(x, states[x.index], s.states)]
            for row in run(a, sg, be=0.5): out.append((a[int(row[0]), 0], a[int(row[1]), 0] + STEP[tf], sym, row[3], rank))
    return out
def portfolio(rows, start=None, max_open=6, risk=0.01, ordered=False, seeds=8):
    res = []
    for sd in range(seeds):
        rnd = random.Random(sd); rr = sorted(rows, key=lambda r: (r[0], r[4] if ordered else 0, rnd.random()))
        eq = 1.0; op = []; paused = {}; peak = 1.0; dd = 0.0; n = w = 0; sr = 0.0
        for a, b, sym, R, _ in rr:
            if start and a < start: continue
            for p in sorted([p for p in op if p[0] <= a]):
                eq += p[2] * p[3]; op.remove(p); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
                if p[2] <= -0.9: paused[p[1]] = p[0] + 6 * 3600
            if len(op) >= max_open or any(p[1] == sym for p in op) or paused.get(sym, 0) > a: continue
            op.append((b, sym, R, eq * risk)); n += 1; w += R > 0; sr += R
        for p in op: eq += p[2] * p[3]
        res.append((eq, n, w, dd, sr))
    e = [r[0] for r in res]; o = res[0]
    return f"final x{np.mean(e):5.2f} ({min(e):.2f}-{max(e):.2f}) trades={o[1]:5d} win={o[2] / o[1] * 100:4.1f}% avgR={np.mean([r[4] / r[1] for r in res]):+.3f} maxDD={np.mean([r[3] for r in res]) * 100:4.1f}%"
if __name__ == "__main__":
    for tuned in (False, True):
        with mp.Pool(4) as p: rows = [x for r in p.map(one, [(s, tuned) for s in coins("all")], chunksize=1) for x in r]
        t = np.array([r[0] for r in rows]); R = np.array([r[3] for r in rows]); mid = (t.min() + t.max()) / 2
        print(f"== {'TUNED per timeframe' if tuned else 'default settings'}: pool n={len(R)} avgR={R.mean():+.3f} h1={R[t < mid].mean():+.3f} h2={R[t >= mid].mean():+.3f} win={np.mean(R > 0) * 100:.1f}%")
        for name, kw in (("6 places x 1%, random order", dict()), ("6 places x 1%, priority order", dict(ordered=True)),
                         ("12 places x 0.5%, priority order", dict(max_open=12, risk=0.005, ordered=True)),
                         ("20 places x 0.3%, priority order", dict(max_open=20, risk=0.003, ordered=True))):
            print(f"  {name:34s} ALL {portfolio(rows, **kw)}"); print(f"  {'':34s} H2  {portfolio(rows, start=mid, **kw)}")
