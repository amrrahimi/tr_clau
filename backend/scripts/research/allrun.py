"""Every strategy x timeframe on all coins, bot rules. Saves trades to trades_<tf>.npz."""
import sys, numpy as np, multiprocessing as mp, pickle
from lib import *
from app import paper, regime
from app.strategies import STRATEGIES, allowed_by_state, parse_params
tf = sys.argv[1]; filt = int(sys.argv[2]) if len(sys.argv) > 2 else 1
mode = "scalping" if tf in ("1m", "3m", "5m") else "daily"
BE = {"1h": 0.5, "2h": 0.5, "4h": 0.5, "6h": 0.5, "12h": 0.5, "1d": 0.5}
def one(sym):
    a = load(sym, tf)
    if len(a) < 400: return []
    c = as_candles(a); rows = [{"high": x[2], "low": x[3], "close": x[4]} for x in a]
    states, _, _ = regime.series(rows, mode)
    out = []
    for k, s in STRATEGIES.items():
        sigs = s.signals(c, parse_params(k, {}, mode))
        if filt: sigs = [x for x in sigs if allowed_by_state(x, states[x.index], s.states)]
        for row in run(a, sigs, be=BE.get(tf, 0)): out.append((k, sym, a[int(row[0]), 0], a[int(row[1]), 0], row[2], row[3], row[4]))
    return out
if __name__ == "__main__":
    with mp.Pool(4) as p: res = [x for r in p.map(one, coins("all"), chunksize=1) for x in r]
    pickle.dump(res, open(f"trades_{tf}_{filt}.pkl", "wb"))
    ks = np.array([x[0] for x in res]); t = np.array([x[2] for x in res]); R = np.array([x[5] for x in res])
    print(summarize(R, t, f"ALL {tf}"))
    for k in STRATEGIES: print(summarize(R[ks == k], t[ks == k], f"{tf} {k}"))
