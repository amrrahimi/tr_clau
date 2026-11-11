import pickle, sys, numpy as np
from lib import *
MOM = ["donchian","turtle","volume_breakout","momentum","box_breakout","wide_bar","bb_breakout","keltner_breakout","adx_breakout","three_soldiers","structure_break","obv_breakout"]
for tf in sys.argv[1:]:
    res = pickle.load(open(f"trades_{tf}_1.pkl","rb"))
    ks = np.array([x[0] for x in res]); sy = np.array([x[1] for x in res]); t = np.array([x[2] for x in res]); d = np.array([x[4] for x in res]); R = np.array([x[5] for x in res])
    m = np.isin(ks, MOM); top=set(LISTS["top"]); vola=set(LISTS["vola"])
    stock = np.array([s in STOCKS for s in sy]); istop = np.array([s in top for s in sy]); isv = np.array([s in vola for s in sy])
    print(summarize(R[m], t[m], f"{tf} MOM family"))
    print(summarize(R[~m], t[~m], f"{tf} others"))
    print(summarize(R[m & (d>0)], t[m & (d>0)], f"{tf} MOM long")); print(summarize(R[m & (d<0)], t[m & (d<0)], f"{tf} MOM short"))
    print(summarize(R[m & stock], t[m & stock], f"{tf} MOM stocks/metals")); print(summarize(R[m & istop & ~stock], t[m & istop & ~stock], f"{tf} MOM top crypto"))
    print(summarize(R[m & isv], t[m & isv], f"{tf} MOM volatile list"))
    q = ((t - t.min()) // (86400*91)).astype(int)
    print("  per quarter avgR:", " ".join(f"{R[m & (q==x)].mean():+.3f}({(m&(q==x)).sum()})" for x in np.unique(q)))
