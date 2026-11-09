"""Study of 2026-11-09 (owner: "check them all together"). Read-only: changes nothing in the bot.

1. Two-step profit lock: step 1 (stop to the fee break-even at 20/30/40/50% of the way) + the 80/40 lock,
   against no lock and the 80/40 lock alone.
2. Skip a signal when, between the signal and the (late) entry, a 1m candle closed beyond the nearest
   support (long) / resistance (short) against the trade.
3. Turtle 55-candle breakout + EMA200 on 4h with trailing exits.
4. Limit entry (0.1 of the stop distance better, maker fee) against market entry.
5. Crowd data on Toobit: funding / open interest / long-short, and funding vs. signal results.

Results in R (multiples of the risk) after Toobit fees, split in two time halves (a rule that is real
should help in both). Runs in GitHub Actions (needs the exchange); prints one report.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app.history import fetch_history  # noqa: E402
from app.indicators import atr as atr_series, ema as ema_series  # noqa: E402
from app.paper import FEE_RATIO_BY_TF, MODE_OF  # noqa: E402
from app.strategies import (LONG, STRATEGIES, Candles, Fees, _levels, breakeven_price, fee_ok,  # noqa: E402
                            parse_params, reward_ok)

FEES = Fees(maker=0.02, taker=0.06)
COINS = 40
TIMEFRAMES = {"5m": 5000, "15m": 5000, "1h": 4000, "4h": 2500}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
# Live signal delay seen in the bot's memory (2026-11-02): about this long after the candle closes.
DELAY = {"5m": 60, "15m": 105, "1h": 360}
SR_DAYS = 6           # 1m candles for the support / resistance test (per coin)


def R(side: str, entry: float, exit_: float, risk: float, fee_in: float, fee_out: float) -> float:
    d = 1 if side == LONG else -1
    paid = entry * fee_in / 100 + exit_ * fee_out / 100
    return ((exit_ - entry) * d - paid) / risk


def walk(c: list[dict], start: int, side: str, entry: float, stop: float, target: float, steps, fee_in: float,
         limit: int = 400) -> float:
    """One trade from candle `start` on. steps: [(share of the way, new stop as share, or "be")], applied
    from the candle after the one that reached them (a candle that reaches both is a stop first)."""
    long_ = side == LONG
    way = target - entry
    risk = abs(entry - stop)
    s = stop
    done = set()
    for i in range(start, min(len(c), start + limit)):
        k = c[i]
        if (k["low"] <= s) if long_ else (k["high"] >= s):
            gapped = (k["open"] < s) if long_ else (k["open"] > s)
            return R(side, entry, k["open"] if gapped else s, risk, fee_in, FEES.taker)
        if (k["high"] >= target) if long_ else (k["low"] <= target):
            return R(side, entry, target, risk, fee_in, FEES.maker)   # target: a limit order
        best = k["high"] if long_ else k["low"]
        for n, (at, to) in enumerate(steps):
            if n in done or (best - entry) / way < at:
                continue
            done.add(n)
            new = breakeven_price(side, entry, FEES, fee_in) if to == "be" else entry + way * to
            if (new > s) if long_ else (new < s):
                s = new
    k = c[min(len(c), start + limit) - 1]
    return R(side, entry, k["close"], risk, fee_in, FEES.taker)


def signals_of(candles: list[dict], tf: str):
    """Every strategy's signals with the bot's fee and reward rules at the next candle's open."""
    data = Candles(opens=[x["open"] for x in candles], highs=[x["high"] for x in candles],
                   lows=[x["low"] for x in candles], closes=[x["close"] for x in candles],
                   volumes=[x.get("volume", 0.0) for x in candles])
    out = []
    for kind, strategy in STRATEGIES.items():
        params = parse_params(kind, None, MODE_OF[tf])
        for sig in strategy.signals(data, params):
            i = sig.index + 1
            if i >= len(candles) - 2:
                continue
            entry = candles[i]["open"]
            levels = _levels(sig, entry)
            if levels is None or not fee_ok(entry, levels[0], FEES, FEE_RATIO_BY_TF[tf]) \
                    or not reward_ok(entry, levels[0], levels[1], FEES):
                continue
            out.append({"kind": kind, "sig": sig, "i": i, "entry": entry, "stop": levels[0], "target": levels[1],
                        "time": candles[sig.index]["time"]})
    return out


class Tally:
    def __init__(self):
        self.d = defaultdict(lambda: [[0, 0.0, 0], [0, 0.0, 0]])   # name -> [half1, half2] of [n, sumR, wins]

    def add(self, name: str, half: int, r: float) -> None:
        x = self.d[name][half]
        x[0] += 1
        x[1] += r
        x[2] += r > 0

    def report(self, title: str) -> list[str]:
        lines = [f"## {title}", "name | trades | avgR | half1 avgR | half2 avgR | won%"]
        for name, (a, b) in self.d.items():
            n = a[0] + b[0]
            if not n:
                continue
            avg = (a[1] + b[1]) / n
            h1 = a[1] / a[0] if a[0] else float("nan")
            h2 = b[1] / b[0] if b[0] else float("nan")
            lines.append(f"{name} | {n} | {avg:+.3f} | {h1:+.3f} | {h2:+.3f} | {(a[2] + b[2]) / n * 100:.1f}")
        return lines


def swings(candles: list[dict], upto: int, price: float, pivot: int = 3, lookback: int = 300):
    """Nearest swing high above and swing low below the price, from closed candles before `upto`."""
    above = below = None
    for j in range(max(pivot, upto - lookback), upto - pivot):
        h, low = candles[j]["high"], candles[j]["low"]
        if all(h >= candles[j + d]["high"] for d in range(-pivot, pivot + 1) if d):
            if h > price and (above is None or h < above):
                above = h
        if all(low <= candles[j + d]["low"] for d in range(-pivot, pivot + 1) if d):
            if low < price and (below is None or low > below):
                below = low
    return above, below


async def main() -> int:
    service = MarketService(create_exchange("futures"), "futures")
    report: list[str] = [f"# Study 2026-11-09 — {COINS} top coins, Toobit fees maker 0.02% taker 0.06%"]
    lock = Tally()
    limit = Tally()
    sr = Tally()
    turtle = Tally()
    funding_rows = []
    try:
        coins = [m.symbol for m in await service.top_markets(limit=COINS)]
        report.append("coins: " + ", ".join(c.split("/")[0] for c in coins))
        ex = service.exchange
        crowd = {k: bool(ex.has.get(k)) for k in ("fetchFundingRateHistory", "fetchFundingRate",
                                                   "fetchOpenInterestHistory", "fetchOpenInterest",
                                                   "fetchLongShortRatioHistory")}
        report.append("## 5. Crowd data on Toobit (ccxt says)\n" + json.dumps(crowd))
        for n, symbol in enumerate(coins):
            print(f"[{n + 1}/{len(coins)}] {symbol}", flush=True)
            for tf, total in TIMEFRAMES.items():
                try:
                    candles = await fetch_history(
                        lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before), total)
                except Exception as error:
                    print("  skip", tf, error, flush=True)
                    continue
                if len(candles) < 600:
                    continue
                candles = candles[:-1]   # the last one is still open
                mid = candles[len(candles) // 2]["time"]
                sigs = signals_of(candles, tf)
                # 1. profit lock variants
                for s in sigs:
                    half = 0 if s["time"] < mid else 1
                    args = (candles, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"])
                    lock.add(f"{tf} none", half, walk(*args, [], FEES.taker))
                    lock.add(f"{tf} lock80/40", half, walk(*args, [(0.8, 0.4)], FEES.taker))
                    for first in (0.2, 0.3, 0.4, 0.5):
                        lock.add(f"{tf} BE@{int(first * 100)}+80/40", half,
                                 walk(*args, [(first, "be"), (0.8, 0.4)], FEES.taker))
                    # 4. limit entry: 0.1 of the stop distance better, must trade beyond it in the next candle
                    long_ = s["sig"].side == LONG
                    risk = abs(s["entry"] - s["stop"])
                    price = s["entry"] - 0.1 * risk if long_ else s["entry"] + 0.1 * risk
                    k = candles[s["i"]]
                    filled = k["low"] < price if long_ else k["high"] > price
                    market = walk(*args, [], FEES.taker)
                    limit.add(f"{tf} market", half, market)
                    if filled:
                        # filled during candle i: from there the same stop / target (same candle: stop first)
                        r = walk(candles, s["i"], s["sig"].side, price, s["stop"], s["target"], [], FEES.maker)
                        limit.add(f"{tf} limit (filled)", half, r)
                        limit.add(f"{tf} limit per signal (missed=0)", half, r)
                        limit.add(f"{tf} market, same signals as filled", half, market)
                    else:
                        limit.add(f"{tf} limit per signal (missed=0)", half, 0.0)
                        limit.add(f"{tf} market, signals limit missed", half, market)
                # 3. Turtle on 4h
                if tf == "4h":
                    turtle_test(candles, mid, turtle)
                # funding vs results (if available): later
                if tf == "1h" and crowd["fetchFundingRateHistory"]:
                    try:
                        rates = await ex.fetch_funding_rate_history(symbol, since=candles[0]["time"] * 1000, limit=1000)
                        funding_rows.append((symbol, len(rates), rates[-1]["fundingRate"] if rates else None))
                        by_time = sorted((int(x["timestamp"] / 1000), x["fundingRate"]) for x in rates)
                        for s in sigs:
                            past = [f for t, f in by_time if t <= s["time"]]
                            if not past:
                                continue
                            f = past[-1]
                            crowded = (f > 0.0001 and s["sig"].side == LONG) or (f < -0.0001 and s["sig"].side != LONG)
                            half = 0 if s["time"] < mid else 1
                            r = walk(candles, s["i"], s["sig"].side, s["entry"], s["stop"], s["target"], [], FEES.taker)
                            lock.add("1h funding: with the crowd" if crowded else "1h funding: not crowded", half, r)
                    except Exception as error:
                        funding_rows.append((symbol, "error", str(error)[:80]))
            # 2. support / resistance between signal and late entry (15m, 1h; 5m)
            try:
                await sr_test(service, symbol, sr)
            except Exception as error:
                print("  sr skip", error, flush=True)
        report += lock.report("1. Profit lock (all signals; + funding split if available)")
        report += limit.report("4. Limit vs market entry")
        report += sr.report("2. Skip when a 1m candle closed beyond S/R against the trade before the late entry")
        report += turtle.report("3. Turtle 55 + EMA200 on 4h, exits")
        if funding_rows:
            report.append("funding sample: " + json.dumps(funding_rows[:5]))
    finally:
        await service.close()
    text = "\n".join(report)
    print("\n\n" + text)
    Path("study-report.md").write_text(text, encoding="utf-8")
    return 0


def turtle_test(c: list[dict], mid: int, t: Tally) -> None:
    closes = [x["close"] for x in c]
    highs = [x["high"] for x in c]
    lows = [x["low"] for x in c]
    e200 = ema_series(closes, 200)
    a20 = atr_series(highs, lows, closes, 20)
    for i in range(220, len(c) - 2):
        if e200[i] is None or a20[i] is None:
            continue
        up = closes[i] > max(highs[i - 55:i]) and closes[i] > e200[i]
        down = closes[i] < min(lows[i - 55:i]) and closes[i] < e200[i]
        if not (up or down):
            continue
        side = LONG if up else "short"
        entry = c[i + 1]["open"]
        stop = entry - 2 * a20[i] if up else entry + 2 * a20[i]
        risk = abs(entry - stop)
        if not fee_ok(entry, stop, FEES, 0.05):
            continue
        half = 0 if c[i]["time"] < mid else 1
        for name, rule in (("2R target", ("fixed", 2)), ("3R target", ("fixed", 3)),
                           ("exit 20-channel", ("chan", 20)), ("exit 10-channel", ("chan", 10)),
                           ("chandelier 3 ATR", ("atr", 3.0)), ("chandelier 4 ATR", ("atr", 4.0))):
            t.add(name, half, _turtle_exit(c, i + 1, side, entry, stop, risk, rule, a20))


def _turtle_exit(c, start, side, entry, stop, risk, rule, a20, limit=600) -> float:
    long_ = side == LONG
    s = stop
    kind, k = rule
    target = entry + (k * risk if long_ else -k * risk) if kind == "fixed" else None
    best = entry
    for i in range(start, min(len(c), start + limit)):
        x = c[i]
        if (x["low"] <= s) if long_ else (x["high"] >= s):
            gapped = (x["open"] < s) if long_ else (x["open"] > s)
            return R(side, entry, x["open"] if gapped else s, risk, FEES.taker, FEES.taker)
        if target is not None and ((x["high"] >= target) if long_ else (x["low"] <= target)):
            return R(side, entry, target, risk, FEES.taker, FEES.maker)
        # the trailing stop moves after the candle (toward profit only)
        if kind == "chan" and i - k >= 0:
            new = min(y["low"] for y in c[i - k + 1:i + 1]) if long_ else max(y["high"] for y in c[i - k + 1:i + 1])
        elif kind == "atr" and a20[i] is not None:
            best = max(best, x["high"]) if long_ else min(best, x["low"])
            new = best - k * a20[i] if long_ else best + k * a20[i]
        else:
            new = s
        if (new > s) if long_ else (new < s):
            s = new
    x = c[min(len(c), start + limit) - 1]
    return R(side, entry, x["close"], risk, FEES.taker, FEES.taker)


async def sr_test(service, symbol: str, t: Tally) -> None:
    """Signals of the last SR_DAYS days on 5m / 15m / 1h; entry DELAY seconds after the close (as live);
    the 1m candles closed in between decide 'crossed' (beyond the nearest swing level against the trade)."""
    minutes = await fetch_history(lambda lim, before: service.fetch_candles(symbol, "1m", limit=lim, before=before),
                                  SR_DAYS * 1440)
    if len(minutes) < 1000:
        return
    m_index = {x["time"]: n for n, x in enumerate(minutes)}
    start = minutes[0]["time"]
    mid = minutes[len(minutes) // 2]["time"]
    for tf, delay in DELAY.items():
        candles = await fetch_history(lambda lim, before: service.fetch_candles(symbol, tf, limit=lim, before=before),
                                      1500)
        candles = candles[:-1]
        for s in signals_of(candles, tf):
            close_time = s["time"] + TF_SECONDS[tf]
            if close_time < start + 3600:
                continue
            first = m_index.get(close_time)
            if first is None:
                continue
            # entry at the 1m candle where the delay ends (its open + the part of a minute: use its close)
            k = first + delay // 60
            if k + 2 >= len(minutes):
                continue
            entry = minutes[k]["close"] if delay % 60 else minutes[k]["open"]
            levels = _levels(s["sig"], entry)
            if levels is None or not fee_ok(entry, levels[0], FEES, FEE_RATIO_BY_TF[tf]) \
                    or not reward_ok(entry, levels[0], levels[1], FEES):
                continue
            above, below = swings(candles, s["sig"].index + 1, candles[s["sig"].index]["close"])
            long_ = s["sig"].side == LONG
            level = below if long_ else above
            between = minutes[first:k + (1 if delay % 60 else 0)]
            crossed = level is not None and any((m["close"] < level) if long_ else (m["close"] > level)
                                                for m in between)
            r = walk(minutes, k + 1, s["sig"].side, entry, levels[0], levels[1], [], FEES.taker, limit=6000)
            half = 0 if s["time"] < mid else 1
            t.add(f"{tf} all", half, r)
            t.add(f"{tf} {'crossed (would skip)' if crossed else 'kept'}", half, r)
            # a bigger delay: price may cross more often (what if the bot is slower)
            k3 = first + 3
            if k3 + 2 < len(minutes):
                e3 = minutes[k3]["open"]
                lv3 = _levels(s["sig"], e3)
                if lv3 is not None:
                    c3 = level is not None and any((m["close"] < level) if long_ else (m["close"] > level)
                                                   for m in minutes[first:k3])
                    r3 = walk(minutes, k3, s["sig"].side, e3, lv3[0], lv3[1], [], FEES.taker, limit=6000)
                    t.add(f"{tf} 3-min delay {'crossed' if c3 else 'kept'}", half, r3)


if __name__ == "__main__":
    started = time.time()
    code = asyncio.run(main())
    print(f"\n(took {(time.time() - started) / 60:.1f} min)")
    sys.exit(code)
