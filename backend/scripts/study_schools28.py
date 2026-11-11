"""Study 2026-11-11 (owner agreed): the four schools again, on 28 months of Binance USDT-M futures candles
(data.binance.vision, 2024-07..2026-10, the coins of Toobit's top-70 and 40-most-volatile lists: the same data as
docs/RESEARCH-2026-11-11.md). Downloaded by scripts/research/dl.py. Same setup code as study_schools.py (swings,
stops, target 2R, fee rule, market entries taker / limits maker). 15m / 30m / 1h / 4h over the whole period,
5m over the last 12 months. Halves: before / after the middle of the period. Per timeframe, all coins together.
"""

from __future__ import annotations

import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study_schools import Run, swings  # noqa: E402

DATA = Path(os.environ.get("RESEARCH_DATA") or Path(__file__).resolve().parent / "research" / "data")
TFS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
YEAR = 365 * 86400


def candles(a: np.ndarray, sec: int) -> list[dict]:
    """5m rows (time, open, high, low, close, volume) -> candles of `sec` seconds (complete ones only)."""
    if sec == 300:
        return [{"time": int(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in a]
    key = (a[:, 0] // sec).astype(np.int64)
    cut = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate(([0], cut))
    ends = np.concatenate((cut, [len(a)]))
    need = sec // 300
    out = []
    for s, e in zip(starts, ends):
        if e - s != need:
            continue
        seg = a[s:e]
        out.append({"time": int(key[s] * sec), "open": float(seg[0, 1]), "high": float(seg[:, 2].max()),
                    "low": float(seg[:, 3].min()), "close": float(seg[-1, 4]), "volume": float(seg[:, 5].sum())})
    return out


def main() -> int:
    files = sorted(DATA.glob("*.npy"))
    print(len(files), "coins", flush=True)
    acc = defaultdict(lambda: [[0, 0.0, 0], [0, 0.0, 0]])
    monthly = defaultdict(lambda: defaultdict(float))
    t_all = []
    for f in files:
        a = np.load(f)
        if len(a):
            t_all += [a[0, 0], a[-1, 0]]
    mid = (min(t_all) + max(t_all)) / 2
    last_year = max(t_all) - YEAR
    for n, f in enumerate(files):
        a = np.load(f)
        if len(a) < 20000:
            continue
        print(f"[{n + 1}/{len(files)}] {f.stem} {len(a)}", flush=True)
        for tf, sec in TFS.items():
            rows = a[a[:, 0] >= last_year] if tf == "5m" else a
            c = candles(rows, sec)
            if len(c) < 600:
                continue
            m_mid = c[len(c) // 2]["time"] if tf == "5m" else mid

            def add(name, half, r, tf=tf, c=c):
                x = acc[(tf, name)][half]
                x[0] += 1
                x[1] += r
                x[2] += r > 0

            run = Run(c, tf, m_mid, add)
            sw = swings(c)
            run.ict(sw)
            run.qm(sw)
            run.ftr(sw)
            run.ytc(sw)
            run.ichimoku()
            del c, run, sw
    lines = ["# Four schools on 28 months (Binance futures, Toobit's coin lists): avg R per trade (half 1 / half 2)",
             "5m: last 12 months only. Reference (docs/RESEARCH-2026-11-11.md): all 46 bot strategies 15m -0.040,",
             "30m -0.021, 1h +0.004, 4h +0.004; breakout family 1h +0.033, 4h +0.041."]
    for tf in TFS:
        lines.append(f"\n## {tf}")
        for (t, name) in sorted(k for k in acc if k[0] == tf):
            h = acc[(t, name)]
            n = h[0][0] + h[1][0]
            fmt = lambda x: f"{x[1] / x[0]:+.3f}" if x[0] else "-"
            lines.append(f"{name}: {(h[0][1] + h[1][1]) / n:+.3f} ({fmt(h[0])} / {fmt(h[1])}) n={n} "
                         f"won {(h[0][2] + h[1][2]) / n * 100:.0f}% total {h[0][1] + h[1][1]:+.0f}R")
    text = "\n".join(lines)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = main()
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
