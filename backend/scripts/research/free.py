"""Free-form research: portfolio strategies on aligned panels (weights x returns, cost per turnover)."""
import sys, numpy as np, math
from lib import *
def panel(tf, names):
    arrs = {s: load(s, tf) for s in names}
    t0 = min(a[0, 0] for a in arrs.values()); t1 = max(a[-1, 0] for a in arrs.values()); step = TFS[tf]
    T = int((t1 - t0) // step) + 1
    P = {k: np.full((T, len(names)), np.nan) for k in "ohlcv"}
    for j, s in enumerate(names):
        a = arrs[s]; i = ((a[:, 0] - t0) // step).astype(int)
        for k, col in zip("ohlcv", (1, 2, 3, 4, 5)): P[k][i, j] = a[:, col]
    return t0 + np.arange(T) * step, P
def stats(r, per_year, label):
    r = np.nan_to_num(r); eq = np.cumprod(1 + r); peak = np.maximum.accumulate(eq); dd = (1 - eq / peak).max()
    sh = r.mean() / r.std() * math.sqrt(per_year) if r.std() > 0 else 0
    h = len(r) // 2; f = lambda x: x.mean() / x.std() * math.sqrt(per_year) if x.std() > 0 else 0
    cagr = eq[-1] ** (per_year / len(r)) - 1
    print(f"{label:52s} Sharpe={sh:+.2f} (h1 {f(r[:h]):+.2f} h2 {f(r[h:]):+.2f}) CAGR={cagr * 100:+7.1f}% vol={r.std() * math.sqrt(per_year) * 100:5.1f}% maxDD={dd * 100:5.1f}% avg/day={r.mean() * per_year / 365 * 100:+.3f}%")
    return sh
def run_w(W, C, cost, per_year, label, lag=1):
    """W[t] decided at close t, held from close t to close t+1 (lag=1)."""
    ret = C[1:] / C[:-1] - 1; ret = np.nan_to_num(ret)
    W = np.nan_to_num(W); Wl = W[:-1]
    turn = np.abs(np.diff(np.vstack([np.zeros((1, W.shape[1])), W]), axis=0)).sum(1)[:-1]
    r = (Wl * ret).sum(1) - turn * cost
    return stats(r, per_year, label), r
def rolling_std(x, n):
    out = np.full_like(x, np.nan); cs = np.nancumsum(np.nan_to_num(x), 0); cs2 = np.nancumsum(np.nan_to_num(x) ** 2, 0)
    out[n:] = np.sqrt(np.maximum(0, (cs2[n:] - cs2[:-n]) / n - ((cs[n:] - cs[:-n]) / n) ** 2)); return out
def roll_max(x, n):
    out = np.full_like(x, np.nan)
    for i in range(n - 1, len(x)): out[i] = np.nanmax(x[i - n + 1:i + 1], 0)
    return out
def roll_min(x, n):
    out = np.full_like(x, np.nan)
    for i in range(n - 1, len(x)): out[i] = np.nanmin(x[i - n + 1:i + 1], 0)
    return out
if __name__ == "__main__":
    import warnings; warnings.filterwarnings("ignore")
    tf = sys.argv[1]; per_year = 365 * 86400 / TFS[tf]; bars_day = 86400 // TFS[tf]
    names = [s for s in coins("all") if s not in STOCKS]
    t, P = panel(tf, names); C = P["c"]; N = len(names); print(tf, C.shape)
    ret = np.vstack([np.zeros((1, N)), C[1:] / C[:-1] - 1]); vol = rolling_std(ret, 30 * bars_day) * math.sqrt(per_year)
    live = ~np.isnan(C) & ~np.isnan(vol) & (vol > 0); nlive = np.maximum(live.sum(1, keepdims=True), 1)
    TAKER, MAKER = 0.0006, 0.0002
    # A. trend ensemble (Donchian state), vol-targeted, long/short and long-only
    for label, lbs in (("A trend ens 5-80d", (5, 10, 20, 40, 80)), ("A trend 20d", (20,)), ("A trend ens 2-10d", (2, 5, 10))):
        sig = np.zeros_like(C)
        for d in lbs:
            n = d * bars_day; hi = roll_max(C, n); lo = roll_min(C, n); st = np.zeros_like(C); cur = np.zeros(N)
            for i in range(len(C)):
                up = C[i] >= hi[i]; dn = C[i] <= lo[i]; cur = np.where(up, 1.0, np.where(dn, -1.0, cur)); st[i] = cur
            sig += st / len(lbs)
        for side, s2 in (("L/S", sig), ("long only", np.maximum(sig, 0))):
            W = np.where(live, s2 * 0.5 / vol, 0) / nlive * 3          # each coin 50% vol, gross scaled
            W = np.clip(W, -0.2, 0.2)
            run_w(W, C, TAKER, per_year, f"{label} {side}")
    # B. cross-sectional momentum, C. reversal: long top 20%, short bottom 20%, equal weight, gross 1
    def xs(score, hold, label, cost=TAKER, rev=False):
        W = np.zeros_like(C)
        for i in range(0, len(C)):
            if i % hold: W[i] = W[i - 1]; continue
            ok = live[i] & ~np.isnan(score[i]); k = ok.sum() // 5
            if k < 2: continue
            order = np.argsort(np.where(ok, score[i], np.nan)); order = order[:ok.sum()]
            lo_, hi_ = order[:k], order[-k:]
            if rev: lo_, hi_ = hi_, lo_
            W[i, hi_] = 0.5 / k; W[i, lo_] = -0.5 / k
        return run_w(W, C, cost, per_year, label)
    for d in (3, 7, 14, 30):
        n = d * bars_day; sc = np.full_like(C, np.nan); sc[n:] = C[n:] / C[:-n] - 1
        xs(sc, 7 * bars_day if d >= 14 else bars_day, f"B xs momentum {d}d (hold {'7d' if d >= 14 else '1d'})")
    for n, lab in ((1, "1 bar"), (bars_day, "1d"), (3 * bars_day, "3d")):
        sc = np.full_like(C, np.nan); sc[n:] = C[n:] / C[:-n] - 1
        xs(sc, n, f"C xs reversal {lab} (hold same)", rev=True)
        xs(sc, n, f"C xs reversal {lab} maker cost", cost=MAKER, rev=True)
        xs(sc, n, f"C xs reversal {lab} zero cost", cost=0, rev=True)
