"""Trend Rider: the discrete, buildable version of the trend portfolio.
Score = average of Donchian states over several lookbacks (close >= highest close of n bars -> +1, <= lowest -> -1).
Enter when score >= t_in (short: <= -t_in) at the next open; exit when score <= t_out (or the stop).
Stop: k ATR from the entry (fixed, a disaster stop). Size: `risk` of equity lost at the stop. Mark-to-market equity."""
import sys, math, numpy as np, numba as nb, warnings
from lib import *
from free import panel, roll_max, roll_min, stats
warnings.filterwarnings("ignore")
def score_of(C, lbs):
    N = C.shape[1]; sig = np.zeros_like(C)
    for n in lbs:
        hi = roll_max(C, n); lo = roll_min(C, n); cur = np.zeros(N)
        for i in range(len(C)):
            cur = np.where(C[i] >= hi[i], 1.0, np.where(C[i] <= lo[i], -1.0, cur)); sig[i] = cur / len(lbs) + sig[i]
    return sig
def atr_panel(H, L, C, n):
    pc = np.vstack([C[:1], C[:-1]]); tr = np.fmax(H - L, np.fmax(np.abs(H - pc), np.abs(L - pc))); out = np.full_like(C, np.nan)
    for j in range(C.shape[1]):
        a = np.nan
        for i in range(len(C)):
            x = tr[i, j]
            if np.isnan(x): continue
            a = x if np.isnan(a) else (a * (n - 1) + x) / n; out[i, j] = a
    return out
@nb.njit(cache=True)
def sim(O, H, L, C, S, A, ready, t_in, t_out, k, risk, max_pos, max_lev, cost, fund, short_ok, start):
    T, N = C.shape; eq = 1.0; pos = np.zeros(N); entry = np.zeros(N); stop = np.zeros(N); qty = np.zeros(N)
    curve = np.ones(T); trades = []; npos = 0; last = np.zeros(N); gone = np.zeros(N)
    for t in range(start, T - 1):
        # decisions at the close of t, executed at the open of t+1; stops watched inside t+1
        gross = 0.0
        for j in range(N):
            if not np.isnan(C[t, j]): last[j] = C[t, j]
            if pos[j] != 0: gross += abs(qty[j]) * last[j]
        # exits by score
        for j in range(N):
            if pos[j] != 0 and not np.isnan(O[t + 1, j]):
                s = S[t, j] * pos[j]
                if s <= t_out:
                    px = O[t + 1, j]; pnl = qty[j] * (px - entry[j]) * pos[j] - abs(qty[j]) * px * cost
                    eq += pnl; trades.append((pnl / (abs(qty[j]) * abs(entry[j] - stop[j])), float(t), float(j), pos[j])); gross -= abs(qty[j]) * last[j]
                    pos[j] = 0; qty[j] = 0; npos -= 1
        # entries (strongest score first is not known: by index order after a deterministic shuffle by t)
        for jj in range(N):
            j = (jj + t * 7) % N
            if pos[j] != 0 or not ready[t, j] or np.isnan(O[t + 1, j]) or np.isnan(A[t, j]): continue
            s = S[t, j]
            d = 1.0 if s >= t_in else (-1.0 if (s <= -t_in and short_ok) else 0.0)
            if d == 0 or npos >= max_pos: continue
            px = O[t + 1, j]; dist = k * A[t, j]
            if dist <= 0 or dist / px > 0.5 or dist / px < 0.02 or H[t, j] == L[t, j]: continue
            q = eq * risk / dist
            if gross + q * px > max_lev * eq: q = max(0.0, (max_lev * eq - gross) / px)
            if q * px < 0.001 * eq: continue
            pos[j] = d; entry[j] = px; stop[j] = px - d * dist; qty[j] = q; eq -= q * px * cost; gross += q * px; npos += 1
        # the bar t+1: stops, funding, mark to market
        m2m = 0.0
        for j in range(N):
            if pos[j] == 0: continue
            if np.isnan(C[t + 1, j]):
                gone[j] += 1
                if gone[j] >= 12:      # no candles for 2 days: delisted, settled at the last price
                    pnl = qty[j] * (last[j] - entry[j]) * pos[j] - qty[j] * last[j] * cost
                    eq += pnl; trades.append((pnl / (qty[j] * abs(entry[j] - stop[j])), float(t), float(j), pos[j])); pos[j] = 0; qty[j] = 0; npos -= 1
                else:
                    m2m += qty[j] * (last[j] - entry[j]) * pos[j]
                continue
            gone[j] = 0
            hit = L[t + 1, j] <= stop[j] if pos[j] > 0 else H[t + 1, j] >= stop[j]
            if hit:
                gap = O[t + 1, j] < stop[j] if pos[j] > 0 else O[t + 1, j] > stop[j]
                px = O[t + 1, j] if gap else stop[j]
                pnl = qty[j] * (px - entry[j]) * pos[j] - qty[j] * px * cost
                eq += pnl; trades.append((pnl / (qty[j] * abs(entry[j] - stop[j])), float(t), float(j), pos[j])); pos[j] = 0; qty[j] = 0; npos -= 1
            else:
                eq -= qty[j] * C[t + 1, j] * fund * pos[j]
                m2m += qty[j] * (C[t + 1, j] - entry[j]) * pos[j]
        curve[t + 1] = eq + m2m
    return curve, trades
def go(tf, names, label, lbs_days=(5, 10, 20, 40, 80), t_in=0.6, t_out=0.0, k=4.0, risk=0.01, max_pos=20, max_lev=3.0,
       cost=0.0008, fund=0.0, short_ok=True, quiet=False):
    key = (tf, tuple(names))
    if key not in go.cache:
        t, P = panel(tf, names); go.cache[key] = (t, P, {})
    t, P, sc = go.cache[key]; bd = 86400 // TFS[tf]
    if lbs_days not in sc: sc[lbs_days] = score_of(P["c"], [d * bd for d in lbs_days])
    S = sc[lbs_days]
    if "atr" not in sc: sc["atr"] = atr_panel(P["h"], P["l"], P["c"], 14 * bd)   # ATR of about 14 days of bars
    ready = np.zeros(P["c"].shape, dtype=np.bool_); need = max(lbs_days) * bd
    cnt = np.cumsum(~np.isnan(P["c"]), 0); ready[:] = cnt >= need
    start = 0
    curve, trades = sim(P["o"], P["h"], P["l"], P["c"], S, sc["atr"], ready, t_in, t_out, k, risk, max_pos, max_lev, cost, fund * TFS[tf] / 28800, short_ok, start)
    # daily returns
    daily = curve[::bd]; r = daily[1:] / daily[:-1] - 1
    tr = np.array([x[0] for x in trades]) if trades else np.zeros(1)
    if not quiet:
        stats(r, 365, f"{label} | n={len(trades)} win={np.mean(tr > 0) * 100:.0f}% avgR={tr.mean():+.2f}")
    return r, curve, tr
go.cache = {}
if __name__ == "__main__":
    crypto = [s for s in coins("all") if s not in STOCKS]
    for tf in ("4h",):
        go(tf, crypto, f"{tf} base L/S in0.6 out0 k4 r1% max20")
        go(tf, crypto, f"{tf} long only", short_ok=False)
        go(tf, crypto, f"{tf} L/S in1.0 (all agree)", t_in=1.0)
        go(tf, crypto, f"{tf} L/S in0.6 out-0.2", t_out=-0.2)
        go(tf, crypto, f"{tf} L/S in0.6 out0.2", t_out=0.2)
        go(tf, crypto, f"{tf} L/S stop 2 ATR", k=2.0)
        go(tf, crypto, f"{tf} L/S stop 8 ATR", k=8.0)
        go(tf, crypto, f"{tf} L/S lookbacks 2-10d", lbs_days=(2, 3, 5, 7, 10))
        go(tf, crypto, f"{tf} L/S lookbacks 10-60d", lbs_days=(10, 20, 30, 45, 60))
        go(tf, crypto, f"{tf} L/S max 10 positions", max_pos=10)
        go(tf, crypto, f"{tf} L/S max 6 positions", max_pos=6)
        go(tf, crypto, f"{tf} L/S cost x2 (0.16%)", cost=0.0016)
        go(tf, crypto, f"{tf} L/S funding 0.01%/8h vs longs", fund=0.0001)
        go(tf, [s for s in LISTS["top"] if s in crypto], f"{tf} L/S top-volume coins only")
        go(tf, [s for s in LISTS["vola"] if s in crypto], f"{tf} L/S volatile-list coins only")
        go(tf, coins("all"), f"{tf} L/S with stock tokens too")
    go("1d", crypto, "1d base L/S"); go("1h", crypto, "1h base L/S")
