"""Portfolio: the bot's money rules on the saved trades (1% risk, max open, one per coin, coin pause after a stop)."""
import sys, pickle, numpy as np, random
STEP = {'15m': 900, '30m': 1800, '1h': 3600, '2h': 7200, '4h': 14400, '1d': 86400}
def load(tfs, kinds, flt=None):
    rows = []
    for tf in tfs:
        for x in pickle.load(open(f"trades_{tf}_1.pkl", "rb")):
            if x[0] in kinds.get(tf, ()): rows.append((x[2], x[3] + STEP[tf], x[1], x[5], tf, x[0]))
    return rows
def simulate(rows, max_open=6, risk=0.01, pause_h=6, seed=0, start=None):
    rnd = random.Random(seed); rows = sorted(rows, key=lambda r: (r[0], rnd.random()))
    eq = 1.0; open_ = []; paused = {}; curve = []; n = 0; wins = 0; peak = 1.0; dd = 0.0; rs = []
    for t0, t1, sym, R, tf, k in rows:
        if start and t0 < start: continue
        for p in sorted([p for p in open_ if p[0] < t0 + 1]):
            eq += p[2] * p[3]; open_.remove(p); curve.append((p[0], eq)); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
            if p[2] <= -0.9: paused[p[1]] = p[0] + pause_h * 3600
        if len(open_) >= max_open or any(p[1] == sym for p in open_) or paused.get(sym, 0) > t0: continue
        open_.append((t1, sym, R, eq * risk)); n += 1; wins += R > 0; rs.append(R)
    for p in sorted(open_): eq += p[2] * p[3]; curve.append((p[0], eq)); peak = max(peak, eq); dd = max(dd, 1 - eq / peak)
    return eq, n, wins, dd, curve, np.array(rs)
def report(name, rows, **kw):
    res = [simulate(rows, seed=s, **kw) for s in range(5)]
    eq, n, wins, dd, curve, rs = res[0]
    c = np.array(curve); months = (c[:, 0] // (30 * 86400)).astype(int); last = {m: e for m, e in zip(months, c[:, 1])}
    ms = sorted(last); vals = [1.0] + [last[m] for m in ms]; mr = np.diff(vals) / np.array(vals[:-1]) * 100
    print(f"{name:44s} trades={n:5d} win={wins / n * 100:4.1f}% avgR={rs.mean():+.3f} final x{np.mean([r[0] for r in res]):6.2f} "
          f"(seeds {min(r[0] for r in res):.2f}-{max(r[0] for r in res):.2f}) maxDD={np.mean([r[3] for r in res]) * 100:4.1f}% "
          f"month avg={mr.mean():+.1f}% med={np.median(mr):+.1f}% pos={np.mean(mr > 0) * 100:.0f}% worst={mr.min():+.1f}%")
    return mr
if __name__ == "__main__":
    MOM = ["donchian","turtle","volume_breakout","momentum","box_breakout","wide_bar","bb_breakout","keltner_breakout","adx_breakout","three_soldiers","structure_break","obv_breakout"]
    OLD = ["ema_cross","macd_ema","rsi_pullback","bb_reversion","supertrend","donchian","liquidity_sweep","fvg_retest","order_block","sd_zone","squeeze","vwap_reversion","ema_pullback","dmi_adx","ichimoku","inside_bar","stoch_rsi_trend","volume_breakout"]
    report("OLD 18 on 1h+4h (before)", load(["1h", "4h"], {"1h": OLD, "4h": OLD}))
    report("MOM family 1h+4h", load(["1h", "4h"], {"1h": MOM, "4h": MOM}))
    report("MOM family 1h+2h+4h", load(["1h", "2h", "4h"], {"1h": MOM, "2h": MOM, "4h": MOM}))
    report("MOM 4h only", load(["4h"], {"4h": MOM}))
    report("MOM 1h only", load(["1h"], {"1h": MOM}))
    report("MOM 1h+4h max_open 10", load(["1h", "4h"], {"1h": MOM, "4h": MOM}), max_open=10)

    report("MOM 1h+4h no limits (max 1000, no pause)", load(["1h", "4h"], {"1h": MOM, "4h": MOM}), max_open=1000, pause_h=0, risk=0.0005)
    report("MOM 1h+4h max 1000, pause 6h", load(["1h", "4h"], {"1h": MOM, "4h": MOM}), max_open=1000, risk=0.0005)
