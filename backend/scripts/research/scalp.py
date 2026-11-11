"""Scalping with maker limit orders on 5m / 15m: buy a dip k ATR under the last close (sell a spike above it),
take profit with a maker limit, stop with a taker order, time exit. Fill only when the price trades THROUGH the limit."""
import sys, time, numpy as np, numba as nb, multiprocessing as mp, math
from lib import *
@nb.njit(cache=True)
def atr_(h, l, c, n):
    out = np.full(len(c), np.nan); tr = np.empty(len(c)); tr[0] = h[0] - l[0]
    for i in range(1, len(c)): tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    s = 0.0
    for i in range(len(c)):
        if i < n: s += tr[i]; out[i] = s / (i + 1)
        else: out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out
@nb.njit(cache=True)
def sim(o, h, l, c, atr, k, tp, sl, hold, maker, taker, trend, mode):
    """mode 0: fade both ways; 1: only with the trend (dips in up, spikes in down); returns per-trade pct list + entry idx"""
    res = []; idx = []; i = 60; n = len(c)
    while i < n - 2:
        a = atr[i]
        if np.isnan(a) or a <= 0 or a / c[i] < 0.001: i += 1; continue
        done = False
        for d in (1.0, -1.0):
            if mode == 1 and trend[i] * d <= 0: continue
            lim = c[i] - d * k * a; j = i + 1
            through = l[j] < lim if d > 0 else h[j] > lim
            if not through: continue
            e = lim; tgt = e + d * tp * a; stp = e - d * sl * a; x = 0.0; fee = maker; jj = j; first = True
            while True:
                lo = l[jj]; hi = h[jj]
                hit_s = lo <= stp if d > 0 else hi >= stp
                # in the fill candle the target counts only if the close is beyond it (the wick may have come first)
                hit_t = ((hi > tgt) if d > 0 else (lo < tgt)) and (not first or (c[jj] - tgt) * d > 0)
                if hit_s: x = stp; fee = taker; break
                if hit_t: x = tgt; fee = maker; break
                if jj - j + 1 >= hold or jj >= n - 1: x = c[jj]; fee = taker; break
                jj += 1; first = False
            res.append(((x - e) * d - e * maker / 100 - x * fee / 100) / e * 100); idx.append(j)
            i = jj; done = True; break
        i += 1
    return res, idx
def one(args):
    sym, tf, days = args; a = load(sym, tf, time.time() - days * 86400)
    if len(a) < 2000: return {}
    o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]; atr = atr_(h, l, c, 14)
    e = np.empty(len(c)); e[0] = c[0]
    for i in range(1, len(c)): e[i] = e[i - 1] + 2 / 201 * (c[i] - e[i - 1])
    trend = np.sign(c - e); out = {}
    for mode in (0, 1):
        for k in (1.0, 2.0, 3.0):
            for tp, sl, hold in ((0.5, 1.5, 6), (1.0, 2.0, 12), (1.0, 1.0, 12), (2.0, 2.0, 24)):
                r, ix = sim(o, h, l, c, atr, k, tp, sl, hold, 0.02, 0.06, trend, mode)
                out[(mode, k, tp, sl, hold)] = (np.array(r), a[np.array(ix, dtype=np.int64), 0] if ix else np.empty(0))
    return out
if __name__ == "__main__":
    tf = sys.argv[1]; days = float(sys.argv[2]); names = [s for s in coins("all") if s not in STOCKS]
    with mp.Pool(4) as p: res = p.map(one, [(s, tf, days) for s in names], chunksize=1)
    keys = sorted({k for r in res for k in r})
    for k in keys:
        R = np.concatenate([r[k][0] for r in res if k in r]); t = np.concatenate([r[k][1] for r in res if k in r])
        if len(R) == 0: continue
        mid = (t.min() + t.max()) / 2
        print(f"{tf} mode={k[0]} dip={k[1]}ATR tp={k[2]} sl={k[3]} hold={k[4]:2d}: n={len(R):7d} win={np.mean(R > 0) * 100:4.1f}% avg={R.mean():+.4f}% h1={R[t < mid].mean():+.4f}% h2={R[t >= mid].mean():+.4f}%")
