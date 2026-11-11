"""Research harness: Binance futures 5m candles -> any timeframe, the repo's own strategy functions for
signals, a numba simulator with the bot's rules (next-open entry, worst case in one candle, fees) plus
optional trailing exits."""
import sys, json, os, math, numpy as np, numba as nb
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from app.catalog import Candles
D = os.environ.get("RESEARCH_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LISTS = json.load(open(f"{D}/lists.json"))
TFS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}
STOCKS = {"NVDA","SOXL","XAU","SNDK","QQQ","INTC","XAG","SOXS","MSTR","KORU","MU","SKHYNIX","SPCX","SPY","SNXX","AAPL","SKHY","AMD","GOOGL","META","NBIS","COIN","LITE","CRCL","MUU","EWY","CRWV","XBR","XTI"}

def coins(kind="all"):
    have = {f[:-4] for f in os.listdir(D) if f.endswith(".npy")}
    if kind == "top": names = LISTS["top"]
    elif kind == "vola": names = LISTS["vola"]
    else: names = list(dict.fromkeys(LISTS["top"] + LISTS["vola"]))
    return [n for n in names if n in have]

_cache = {}
def load(sym, tf, since=None):
    key = (sym, tf)
    if key not in _cache:
        a = np.load(f"{D}/{sym}.npy")
        s = TFS[tf]
        if s != 300:
            g = (a[:, 0] // s).astype(np.int64)
            idx = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
            end = np.r_[idx[1:], len(a)] - 1
            out = np.empty((len(idx), 6))
            out[:, 0] = g[idx] * s
            out[:, 1] = a[idx, 1]
            out[:, 2] = np.maximum.reduceat(a[:, 2], idx)
            out[:, 3] = np.minimum.reduceat(a[:, 3], idx)
            out[:, 4] = a[end, 4]
            out[:, 5] = np.add.reduceat(a[:, 5], idx)
            a = out
        _cache[key] = a
    a = _cache[key]
    if since is not None: a = a[a[:, 0] >= since]
    return a

def as_candles(a):
    return Candles(opens=a[:, 1].tolist(), highs=a[:, 2].tolist(), lows=a[:, 3].tolist(), closes=a[:, 4].tolist(), volumes=a[:, 5].tolist())

def sig_arrays(sigs):
    """repo Signal list -> arrays (index, dir, stop_price, stop_dist, target_price, reward, trail)"""
    n = len(sigs)
    idx = np.empty(n, np.int64); d = np.empty(n); sp = np.full(n, np.nan); sd = np.full(n, np.nan)
    tp = np.full(n, np.nan); rw = np.full(n, np.nan); tr = np.full(n, np.nan)
    for k, s in enumerate(sigs):
        idx[k] = s.index; d[k] = 1 if s.side == "long" else -1
        if s.stop_price is not None: sp[k] = s.stop_price
        if s.stop_distance is not None: sd[k] = s.stop_distance
        if s.target_price is not None: tp[k] = s.target_price
        if s.reward is not None: rw[k] = s.reward
        t = getattr(s, "trail", None)
        if t is not None: tr[k] = t
    return idx, d, sp, sd, tp, rw, tr

@nb.njit(cache=True)
def sim(o, h, l, c, idx, d, sp, sd, tp, rw, tr, taker, maker, fee_ratio, min_rr, be_part, max_hold, slip,
        rw_override, trail_override, line, overlap):
    """One position at a time (overlap=0) or every signal on its own (overlap=1).
    tr / trail_override: trailing distance in price units (stop follows the best close-candle extreme).
    line: optional trailing line per candle (stop = line of last closed candle, only toward profit); pass empty.
    Returns rows: entry_i, exit_i, dir, R, pct, reason(0 stop,1 target,2 time,3 trail/be stop)."""
    n = len(c); out = []
    busy_until = -1
    for k in range(len(idx)):
        i = idx[k] + 1
        if i >= n: break
        if not overlap and i <= busy_until: continue
        e = o[i]; dd = d[k]
        stop = sp[k] if not np.isnan(sp[k]) else e - dd * sd[k]
        risk = (e - stop) * dd
        if risk <= 0 or e <= 0: continue
        r = rw_override if rw_override > 0 else rw[k]
        target = tp[k] if (not np.isnan(tp[k]) and rw_override <= 0) else e + dd * risk * r
        if np.isnan(target) or (target - e) * dd <= 0: continue
        riskpct = risk / e * 100
        if fee_ratio > 0 and 2 * taker > fee_ratio * riskpct: continue
        fee_t = e * taker / 100 + target * taker / 100
        rr = (abs(target - e) - fee_t) / (risk + e * taker / 100 + stop * taker / 100)
        if min_rr > 0 and rr < min_rr - 1e-9: continue
        trail = trail_override * risk if trail_override > 0 else tr[k]
        best = e; cur = stop; moved = False; reason = -1; xp = 0.0; j = i
        be = e * (1 + taker / 100) / (1 - taker / 100) if dd > 0 else e * (1 - taker / 100) / (1 + taker / 100)
        while j < n:
            lo = l[j]; hi = h[j]
            hit_s = lo <= cur if dd > 0 else hi >= cur
            hit_t = hi >= target if dd > 0 else lo <= target
            if hit_s:
                gap = o[j] < cur if dd > 0 else o[j] > cur
                xp = o[j] if gap else cur
                xp = xp * (1 - dd * slip / 100)
                reason = 3 if moved else 0; break
            if hit_t:
                xp = target; reason = 1; break
            if max_hold > 0 and j - i + 1 >= max_hold:
                xp = c[j]; reason = 2; break
            # after the candle closed: move the stop
            ext = hi if dd > 0 else lo
            if (ext - best) * dd > 0: best = ext
            if be_part > 0 and not moved:
                trig = e + (target - e) * be_part
                if (ext - trig) * dd >= 0 and (be - cur) * dd > 0 and (target - be) * dd > 0:
                    cur = be; moved = True
            if not np.isnan(trail) and trail > 0:
                ns = best - dd * trail
                if (ns - cur) * dd > 0: cur = ns; moved = True
            if len(line) > 0 and not np.isnan(line[j]):
                ns = line[j]
                if (ns - cur) * dd > 0 and (c[j] - ns) * dd > 0: cur = ns; moved = True
            j += 1
        if reason < 0: break   # still open at the end: dropped
        xfee = maker if reason == 1 else taker
        pct = ((xp - e) * dd - e * taker / 100 - xp * xfee / 100) / e * 100
        out.append((float(i), float(j), dd, pct / riskpct, pct, float(reason)))
        busy_until = j
    return out

def run(a, sigs, taker=0.06, maker=0.02, fee_ratio=0.05, min_rr=1.0, be=0.0, max_hold=0, slip=0.0,
        reward=0.0, trail=0.0, line=None, overlap=0):
    if not sigs: return np.empty((0, 6))
    arr = sig_arrays(sigs)
    r = sim(a[:, 1], a[:, 2], a[:, 3], a[:, 4], *arr, taker, maker, fee_ratio, min_rr, be, max_hold, slip,
            reward, trail, np.empty(0) if line is None else line, overlap)
    return np.array(r) if r else np.empty((0, 6))

def summarize(R, t, label="", split=None):
    """R, entry times -> text line: n, win%, avgR, halves, monthly t-stat."""
    n = len(R)
    if n == 0: return f"{label:38s} n=0"
    order = np.argsort(t); R = R[order]; t = t[order]
    split = split or (t[0] + t[-1]) / 2
    a, b = R[t < split], R[t >= split]
    m = (t // (30 * 86400)).astype(int)
    ms = np.array([R[m == x].sum() for x in np.unique(m)])
    ts = ms.mean() / (ms.std(ddof=1) / math.sqrt(len(ms))) if len(ms) > 2 and ms.std() > 0 else 0
    f = lambda x: f"{x.mean():+.3f}" if len(x) else "  n/a"
    return (f"{label:38s} n={n:6d} win={np.mean(R > 0) * 100:4.1f}% avgR={R.mean():+.3f} "
            f"h1={f(a)} h2={f(b)} sumR={R.sum():+8.1f} posMonths={np.mean(ms > 0) * 100:3.0f}% t={ts:+.2f}")
