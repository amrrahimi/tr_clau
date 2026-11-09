"""Study 2026-11-09 (2): Volume Profile / POC on Toobit history (owner: "run it"). Read-only.

Profile = the 100 closed candles before the candle (24 price rows, each candle's volume spread over its
high-low, Value Area 70%). Variants, in R after fees, two halves:
  A  the bot's signals with their own stop / target (reference)
  B  the bot's signals with Volume Profile levels: stop beyond the nearest level against the trade
     (+ a quarter of a row), target the nearest level in the trade's direction; taken only if reward >= risk
  C  the bot's signals, only longs below the POC and shorts above it (own stop / target)
  D  Value Area edge: a closed candle that went outside the Value Area and closed back inside ->
     toward the POC (stop beyond that candle's extreme)
  E  "80% rule": two closes in a row inside the Value Area after being outside -> to the opposite edge
     (stop beyond the edge it came in from)
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study import COINS, FEES, Tally, signals_of, walk  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.strategies import LONG, fee_ok  # noqa: E402

ROWS, VA, LOOK, EVERY = 24, 0.70, 100, 5
TIMEFRAMES = {"5m": 5000, "15m": 5000, "1h": 4000, "4h": 2500}


def profile(c: list[dict]) -> dict:
    top = max(k["high"] for k in c)
    bot = min(k["low"] for k in c)
    step = (top - bot) / ROWS or 1e-12
    v = [0.0] * ROWS
    for k in c:
        h, low, vol = k["high"], k["low"], k.get("volume", 0.0) or 0.0
        if h > low:
            a = max(0, min(ROWS - 1, int((low - bot) / step)))
            b = max(0, min(ROWS - 1, int((h - bot) / step)))
            for i in range(a, b + 1):
                lo = bot + i * step
                ov = min(h, lo + step) - max(low, lo)
                if ov > 0:
                    v[i] += vol * ov / (h - low)
        else:
            v[max(0, min(ROWS - 1, int((k["close"] - bot) / step)))] += vol
    mx = max(v)
    p = v.index(mx)
    total = sum(v)
    up = dn = p
    acc = mx
    while acc < total * VA and (up < ROWS - 1 or dn > 0):
        u = v[up + 1] if up < ROWS - 1 else -1.0
        d = v[dn - 1] if dn > 0 else -1.0
        if u >= d:
            up += 1
            acc += u
        else:
            dn -= 1
            acc += d
    return {"poc": bot + (p + 0.5) * step, "vah": bot + (up + 1) * step, "val": bot + dn * step,
            "high": top, "low": bot, "step": step}


def profiles(c: list[dict]) -> dict[int, dict]:
    """Profile for candle i from the LOOK candles before it, recomputed every EVERY candles."""
    out, last = {}, None
    for i in range(LOOK, len(c)):
        if last is None or (i - LOOK) % EVERY == 0:
            last = profile(c[i - LOOK:i])
        out[i] = last
    return out


def vp_levels(side: str, entry: float, vp: dict):
    gap = entry * 0.003
    buf = vp["step"] * 0.25
    below = sorted([x for x in (vp["val"], vp["poc"], vp["low"]) if x < entry - gap], reverse=True)
    above = sorted([x for x in (vp["poc"], vp["vah"], vp["high"]) if x > entry + gap])
    if not below or not above:
        return None
    return (below[0] - buf, above[0]) if side == LONG else (above[0] + buf, below[0])


def trade(t: Tally, name: str, half: int, c, i, side, entry, stop, target) -> None:
    if stop is None or target is None:
        return
    risk = abs(entry - stop)
    if risk <= 0 or abs(target - entry) < risk or not fee_ok(entry, stop, FEES, 0.05):
        return
    if (side == LONG and not stop < entry < target) or (side != LONG and not target < entry < stop):
        return
    t.add(name, half, walk(c, i, side, entry, stop, target, [], FEES.taker))


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    t = Tally()
    try:
        coins = [m.symbol for m in await service.top_markets(limit=COINS)]
        for n, symbol in enumerate(coins):
            print(f"[{n + 1}/{len(coins)}] {symbol}", flush=True)
            for tf, total in TIMEFRAMES.items():
                try:
                    c = await fetch_history(
                        lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                except Exception as error:
                    print("  skip", tf, error, flush=True)
                    continue
                c = c[:-1]
                if len(c) < 600:
                    continue
                mid = c[len(c) // 2]["time"]
                vps = profiles(c)
                # A / B / C on the bot's signals
                for s in signals_of(c, tf):
                    i, side, entry = s["i"], s["sig"].side, s["entry"]
                    vp = vps.get(s["sig"].index)
                    if vp is None:
                        continue
                    half = 0 if s["time"] < mid else 1
                    own = walk(c, i, side, entry, s["stop"], s["target"], [], FEES.taker)
                    t.add(f"{tf} A bot levels", half, own)
                    lv = vp_levels(side, entry, vp)
                    if lv:
                        trade(t, f"{tf} B VP levels (rr>=1)", half, c, i, side, entry, *lv)
                    if (side == LONG and entry < vp["poc"]) or (side != LONG and entry > vp["poc"]):
                        t.add(f"{tf} C POC side: kept", half, own)
                    else:
                        t.add(f"{tf} C POC side: removed", half, own)
                # D / E: the Value Area's own setups
                for i in range(LOOK + 1, len(c) - 2):
                    vp = vps[i]
                    k = c[i]
                    half = 0 if k["time"] < mid else 1
                    entry = c[i + 1]["open"]
                    buf = vp["step"] * 0.25
                    if k["low"] < vp["val"] < k["close"] < vp["poc"]:
                        trade(t, f"{tf} D VAL edge -> POC (long)", half, c, i + 1, LONG, entry, k["low"] - buf, vp["poc"])
                    if k["high"] > vp["vah"] > k["close"] > vp["poc"]:
                        trade(t, f"{tf} D VAH edge -> POC (short)", half, c, i + 1, "short", entry, k["high"] + buf, vp["poc"])
                    prev = c[i - 1]
                    was_out = c[i - 2]["close"] < vps[i - 2]["val"] or c[i - 2]["close"] > vps[i - 2]["vah"]
                    inside = vp["val"] < prev["close"] < vp["vah"] and vp["val"] < k["close"] < vp["vah"]
                    if was_out and inside:
                        if c[i - 2]["close"] < vps[i - 2]["val"]:
                            trade(t, f"{tf} E 80% rule (long to VAH)", half, c, i + 1, LONG, entry, vp["val"] - buf, vp["vah"])
                        else:
                            trade(t, f"{tf} E 80% rule (short to VAL)", half, c, i + 1, "short", entry, vp["vah"] + buf, vp["val"])
    finally:
        await service.close()
    text = "\n".join(t.report("Volume Profile / POC study (40 coins)"))
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
