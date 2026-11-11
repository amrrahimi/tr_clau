"""Momentum family: features at the signal, to find filters that hold in both halves."""
import sys, numpy as np, multiprocessing as mp, pickle
from lib import *
from app import regime
from app.strategies import STRATEGIES, allowed_by_state, parse_params
MOM = ["donchian","turtle","volume_breakout","momentum","box_breakout","wide_bar","bb_breakout","keltner_breakout","adx_breakout","three_soldiers","structure_break","obv_breakout"]
tf = sys.argv[1]; HT = {"1h": "4h", "2h": "1d", "4h": "1d", "30m": "4h", "15m": "1h"}[tf]
def ema(x, n):
    a = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)): out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out
def er_trend(c, n=20):
    out = np.zeros(len(c))
    d = np.abs(np.diff(c)); cs = np.r_[0, np.cumsum(d)]
    for i in range(n, len(c)):
        path = cs[i] - cs[i - n]; mv = c[i] - c[i - n]
        out[i] = 0 if path == 0 or abs(mv) / path < 0.3 else np.sign(mv)
    return out
def asof(t_src, v_src, step, t):   # value of the last CLOSED higher candle at time t (candle closed at t_src+step)
    j = np.searchsorted(t_src + step, t, side="right") - 1
    return np.where(j >= 0, v_src[np.clip(j, 0, len(v_src) - 1)], np.nan)
btc = None
def one(sym):
    a = load(sym, tf)
    if len(a) < 600: return []
    step = TFS[tf]; c = as_candles(a); cl = a[:, 4]
    rows = [{"high": x[2], "low": x[3], "close": x[4]} for x in a]
    states, adx, atrr = regime.series(rows, "daily")
    h = load(sym, HT); b = load("BTC", HT); d1 = load(sym, "1d"); b1 = load("BTC", "1d")
    tclose = a[:, 0] + step
    ht = asof(h[:, 0], er_trend(h[:, 4]), TFS[HT], tclose)
    bt = asof(b[:, 0], er_trend(b[:, 4]), TFS[HT], tclose)
    dtr = asof(d1[:, 0], np.sign(d1[:, 4] - ema(d1[:, 4], 20)), 86400, tclose)
    btr = asof(b1[:, 0], np.sign(b1[:, 4] - ema(b1[:, 4], 50)), 86400, tclose)
    volr = a[:, 5] / np.maximum(1e-12, np.convolve(a[:, 5], np.ones(20) / 20, "full")[:len(a)])
    e200 = ema(cl, 200)
    sigs_all = {}
    votes = np.zeros(len(a))
    for k in MOM:
        s = STRATEGIES[k]; sg = [x for x in s.signals(c, parse_params(k, {}, "daily")) if allowed_by_state(x, states[x.index], s.states)]
        sigs_all[k] = sg
        for x in sg: votes[x.index] += 1 if x.side == "long" else -1
    v3 = np.convolve(votes, np.ones(3), "full")[:len(a)]   # votes of this and the 2 candles before
    out = []
    for k, sg in sigs_all.items():
        if not sg: continue
        idx = {x.index: x for x in sg}
        for row in run(a, sg, be=0.5 if tf in ("1h", "2h", "4h") else 0):
            i = int(row[0]) - 1; dd = row[2]
            out.append((k, sym, a[i, 0], dd, row[3], ht[i] * dd, bt[i] * dd, dtr[i] * dd, btr[i] * dd, volr[i],
                        atrr[i] or np.nan, adx[i] or np.nan, v3[i] * dd, (cl[i] - e200[i]) / cl[i] * dd, states[i]))
    return out
if __name__ == "__main__":
    with mp.Pool(4) as p: res = [x for r in p.map(one, coins("all"), chunksize=1) for x in r]
    pickle.dump(res, open(f"feat_{tf}.pkl", "wb")); print(len(res))
