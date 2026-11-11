import sys, pickle, numpy as np
from lib import summarize
tf = sys.argv[1]; res = pickle.load(open(f"feat_{tf}.pkl", "rb"))
t = np.array([x[2] for x in res]); R = np.array([x[4] for x in res])
F = {n: np.array([x[5 + i] for x in res], float) for i, n in enumerate(["htf_er", "btc_er", "d_ema20", "btc_d_ema50", "volr", "atrr", "adx", "votes", "dist200"])}
st = np.array([x[14] for x in res])
print(summarize(R, t, f"{tf} all MOM"))
for n in ("htf_er", "btc_er", "d_ema20", "btc_d_ema50"):
    for v in (-1, 0, 1): m = F[n] == v; print(summarize(R[m], t[m], f"  {n}={v:+d}"))
for n, cuts in (("volr", [1, 2, 3, 5]), ("atrr", [0.8, 1, 1.3, 1.7]), ("adx", [15, 20, 25, 35]), ("votes", [1.5, 2.5, 3.5, 5.5]), ("dist200", [0, 0.03, 0.08, 0.15])):
    edges = [-np.inf] + cuts + [np.inf]
    for lo, hi in zip(edges, edges[1:]): m = (F[n] > lo) & (F[n] <= hi); print(summarize(R[m], t[m], f"  {n} ({lo},{hi}]"))
for s in np.unique(st): m = st == s; print(summarize(R[m], t[m], f"  state={s}"))
