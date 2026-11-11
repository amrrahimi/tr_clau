"""Per-timeframe tuning: each strategy's main settings, best picked on the first half, judged on the second."""
import sys, numpy as np, multiprocessing as mp
from lib import *
from app import regime
from app.strategies import STRATEGIES, allowed_by_state, parse_params
tf = sys.argv[1]
GRID = {"donchian": {"length": [10, 20, 40, 55]}, "turtle": {"length": [30, 55, 100]}, "volume_breakout": {"volume_mult": [1.5, 2, 3], "kc_mult": [1.5, 2, 2.5]},
        "momentum": {"thrust": [3, 4, 6], "length": [10, 20, 40]}, "bb_breakout": {"mult": [2, 2.5, 3]}, "keltner_breakout": {"kc_mult": [1.5, 2, 2.5]},
        "adx_breakout": {"min_adx": [20, 25, 35], "length": [20, 40]}, "box_breakout": {"box": [3, 4, 6]}, "wide_bar": {"size": [2, 2.5, 3.5]},
        "structure_break": {"pivot": [3, 5, 8]}, "obv_breakout": {"length": [30, 50, 100]}, "three_soldiers": {"size": [0.3, 0.5, 0.8]}}
VAR = []
for k, g in GRID.items():
    VAR.append((k, {}))
    for name, vals in g.items():
        for v in vals:
            if v != [p.default for p in STRATEGIES[k].params if p.name == name][0]: VAR.append((k, {name: v}))
    for r in (1.5, 3):
        VAR.append((k, {"reward": r}))
def one(sym):
    a = load(sym, tf)
    if len(a) < 600: return []
    c = as_candles(a); rows = [{"high": x[2], "low": x[3], "close": x[4]} for x in a]
    states, _, _ = regime.series(rows, "daily"); out = []
    for vi, (k, over) in enumerate(VAR):
        s = STRATEGIES[k]; sg = [x for x in s.signals(c, parse_params(k, over, "daily")) if allowed_by_state(x, states[x.index], s.states)]
        for row in run(a, sg, be=0.5): out.append((vi, a[int(row[0]), 0], row[3]))
    return out
if __name__ == "__main__":
    with mp.Pool(4) as p: res = [x for r in p.map(one, coins("all"), chunksize=1) for x in r]
    vi = np.array([x[0] for x in res]); t = np.array([x[1] for x in res]); R = np.array([x[2] for x in res]); mid = (t.min() + t.max()) / 2
    tot_d = tot_t = 0.0; cur = None; best = None
    for i, (k, over) in enumerate(VAR + [(None, {})]):
        if k != cur:
            if cur is not None:
                d, b = base, best
                print(f"{tf} {cur:17s} default h1={d[0]:+.3f} h2={d[1]:+.3f} | best on h1: {str(b[2]):22s} h1={b[0]:+.3f} h2={b[1]:+.3f}  -> h2 {'BETTER' if b[1] > d[1] + 0.005 else 'same' if abs(b[1] - d[1]) <= 0.005 else 'WORSE'}")
                tot_d += d[1]; tot_t += b[1]
            cur = k; best = None
            if k is None: break
        m = vi == i; a_ = R[m & (t < mid)]; b_ = R[m & (t >= mid)]
        if len(a_) < 100 or len(b_) < 50: continue
        row = (a_.mean(), b_.mean(), over)
        if not over: base = row
        if best is None or row[0] > best[0]: best = row
    print(f"{tf} sum of h2 avgR: default {tot_d:+.3f}, tuned on h1 {tot_t:+.3f}")
