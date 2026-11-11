"""Priority and filters for the breakout family: chosen on the first half, judged on the second."""
import pickle, sys, random, numpy as np
from lib import summarize
STEP = {"30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400}
D = {}
for tf in STEP:
    res = pickle.load(open(f"feat_{tf}.pkl", "rb"))
    D[tf] = dict(k=np.array([x[0] for x in res]), sym=np.array([x[1] for x in res]), t=np.array([x[2] for x in res]) + STEP[tf],
                 R=np.array([x[4] for x in res]), tx=np.array([x[5] for x in res]), atrr=np.array([x[11] for x in res], float),
                 volr=np.array([x[10] for x in res], float), st=np.array([x[15] for x in res]), adx=np.array([x[12] for x in res], float))
t0 = min(d["t"].min() for d in D.values()); t1 = max(d["t"].max() for d in D.values()); MID = (t0 + t1) / 2
print("== volatility filter (ATR / its 50-candle average at the signal) ==")
for tf, d in D.items():
    for lo, hi in ((0, 1.0), (1.0, 1.3), (1.3, 9)):
        m = (d["atrr"] > lo) & (d["atrr"] <= hi); print(summarize(d["R"][m], d["t"][m], f"{tf} atr ratio ({lo},{hi}]", split=MID))
print("== strategy x timeframe (h1 = first half, h2 = second) ==")
PRIOR = {}
for tf, d in D.items():
    for k in np.unique(d["k"]):
        m = d["k"] == k; a = d["R"][m & (d["t"] < MID)]; b = d["R"][m & (d["t"] >= MID)]
        v = d["atrr"] > 1.0; a2 = d["R"][m & v & (d["t"] < MID)]; b2 = d["R"][m & v & (d["t"] >= MID)]
        PRIOR[(tf, k)] = (a.mean() * len(a) / (len(a) + 300), a2.mean() * len(a2) / (len(a2) + 300), d["R"][m & v].mean() * (m & v).sum() / ((m & v).sum() + 300))
        print(f"{tf:4s}{k:18s} n={m.sum():6d} all h1={a.mean():+.3f} h2={b.mean():+.3f} | atr>1: n={(m & v).sum():6d} h1={a2.mean():+.3f} h2={b2.mean():+.3f}")
def portfolio(tfs, keep, score, start=None, max_open=6, risk=0.01, pause_h=6, seeds=5):
    rows = []
    for tf in tfs:
        d = D[tf]
        for i in range(len(d["R"])):
            if (start is None or d["t"][i] >= start) and keep(tf, d, i): rows.append((d["t"][i], d["tx"][i], d["sym"][i], d["R"][i], score(tf, d, i)))
    out = []
    for s in range(seeds):
        rnd = random.Random(s); rr = sorted(rows, key=lambda r: (r[0], -r[4], rnd.random()))
        eq = 1.0; open_ = []; paused = {}; peak = 1.0; dd = 0.0; n = 0; w = 0; sr = 0.0
        for a, b, sym, R, sc in rr:
            for p in sorted([p for p in open_ if p[0] <= a]):
                eq += p[2] * p[3]; open_.remove(p); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
                if p[2] <= -0.9: paused[p[1]] = p[0] + pause_h * 3600
            if len(open_) >= max_open or any(p[1] == sym for p in open_) or paused.get(sym, 0) > a: continue
            open_.append((b, sym, R, eq * risk)); n += 1; w += R > 0; sr += R
        for p in open_: eq += p[2] * p[3]
        out.append((eq, n, w, dd, sr))
    e = [o[0] for o in out]; o = out[0]
    return f"final x{np.mean(e):5.2f} ({min(e):.2f}-{max(e):.2f}) trades={o[1]:5d} win={o[2] / max(o[1], 1) * 100:4.1f}% avgR={o[4] / max(o[1], 1):+.3f} maxDD={np.mean([x[3] for x in out]) * 100:4.1f}%"
P1H = {"volume_breakout", "three_soldiers", "bb_breakout", "turtle", "keltner_breakout", "momentum", "adx_breakout", "structure_break"}
old = lambda tf, d, i: tf == "4h" or d["k"][i] in P1H
vol = lambda tf, d, i: old(tf, d, i) and d["atrr"][i] > 1.0
rnd0 = lambda tf, d, i: 0.0
by_prior = lambda tf, d, i: PRIOR[(tf, d["k"][i])][0]
by_prior_v = lambda tf, d, i: PRIOR[(tf, d["k"][i])][1]
pos_prior = lambda tf, d, i: vol(tf, d, i) and PRIOR[(tf, d["k"][i])][1] > 0.02
allv = lambda tf, d, i: d["atrr"][i] > 1.0 and PRIOR[(tf, d["k"][i])][1] > 0.02
print("== portfolio on the SECOND half (rules chosen on the first) ==")
for name, tfs, keep, score in (
    ("proven set as built, random order", ["1h", "4h"], old, rnd0),
    ("  + ordered by first-half result", ["1h", "4h"], old, by_prior),
    ("  + volatility filter (atr ratio > 1)", ["1h", "4h"], vol, rnd0),
    ("  + filter + order", ["1h", "4h"], vol, by_prior_v),
    ("  + filter + order + drop weak (h1 <= 0.02)", ["1h", "4h"], pos_prior, by_prior_v),
    ("all family, 1h+4h, filter+order+drop weak", ["1h", "4h"], allv, by_prior_v),
    ("all family, 1h+2h+4h, filter+order+drop weak", ["1h", "2h", "4h"], allv, by_prior_v),
    ("all family, 30m-4h, filter+order+drop weak", ["30m", "1h", "2h", "4h"], allv, by_prior_v)):
    print(f"{name:48s} {portfolio(tfs, keep, score, start=MID)}")
print("== whole period, for reference (in-sample for the order) ==")
for name, tfs, keep, score in (("proven set as built, random order", ["1h", "4h"], old, rnd0), ("  + filter + order", ["1h", "4h"], vol, by_prior_v),
                               ("all family 1h+2h+4h filter+order+drop weak", ["1h", "2h", "4h"], allv, by_prior_v)):
    print(f"{name:48s} {portfolio(tfs, keep, score)}")
