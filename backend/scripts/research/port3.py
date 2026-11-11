from port import *
import pickle, numpy as np
MOM = ["donchian","turtle","volume_breakout","momentum","box_breakout","wide_bar","bb_breakout","keltner_breakout","adx_breakout","three_soldiers","structure_break","obv_breakout"]
OLD = ["ema_cross","macd_ema","rsi_pullback","bb_reversion","supertrend","donchian","liquidity_sweep","fvg_retest","order_block","sd_zone","squeeze","vwap_reversion","ema_pullback","dmi_adx","ichimoku","inside_bar","stoch_rsi_trend","volume_breakout"]
REC = {"15m": ["volume_breakout"], "30m": ["volume_breakout", "three_soldiers", "bb_breakout"],
       "1h": ["volume_breakout", "three_soldiers", "bb_breakout", "turtle", "keltner_breakout", "momentum", "adx_breakout", "structure_break"], "4h": MOM}
t = np.array([x[2] for x in pickle.load(open("trades_4h_1.pkl", "rb"))]); mid = (t.min() + t.max()) / 2
tfs = ["15m", "30m", "1h", "4h"]
old = load(tfs, {tf: OLD for tf in tfs}); rec = load(tfs, REC)
report("BEFORE: 18 strategies 15m-4h", old); report("BEFORE, second half", old, start=mid)
report("AFTER: recommended sets 15m-4h", rec); report("AFTER, second half", rec, start=mid)
r2 = load(["1h", "4h"], REC); report("AFTER 1h+4h only", r2); report("AFTER 1h+4h, second half", r2, start=mid)
r3 = load(["4h"], REC); report("AFTER 4h only", r3); report("AFTER 4h only, second half", r3, start=mid)
report("AFTER 4h only, risk 0.5%", r3, risk=0.005)
