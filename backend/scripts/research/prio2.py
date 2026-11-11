import sys, io, contextlib
with contextlib.redirect_stdout(io.StringIO()): from prio import *
def show(name, tfs, keep, score, **kw):
    print(f"{name:54s} H2: {portfolio(tfs, keep, score, start=MID, seeds=8, **kw)}"); print(f"{'':54s} ALL: {portfolio(tfs, keep, score, seeds=8, **kw)}")
for mo, rk in ((6, 0.01), (12, 0.005), (20, 0.003), (40, 0.0015)):
    show(f"proven 1h+4h, {mo} slots, risk {rk * 100:.2f}%", ["1h", "4h"], old, rnd0, max_open=mo, risk=rk)
    show(f"  + volatility filter", ["1h", "4h"], vol, rnd0, max_open=mo, risk=rk)
    show(f"  + filter + priority", ["1h", "4h"], vol, by_prior_v, max_open=mo, risk=rk)
show("family 1h+2h+4h filter+priority, 20 slots 0.3%", ["1h", "2h", "4h"], allv, by_prior_v, max_open=20, risk=0.003)
show("family 1h+2h+4h filter+priority, 40 slots 0.15%", ["1h", "2h", "4h"], allv, by_prior_v, max_open=40, risk=0.0015)
show("proven 1h+4h filter, 20 slots, no coin pause", ["1h", "4h"], vol, rnd0, max_open=20, risk=0.003, pause_h=0)
