"""Paper trading: the bot trades with virtual money (owner's request).

Everything is chosen by the bot: it scans the top coins on five timeframes
with all strategies, keeps only reliable signals (the cautious conditions,
the fee rule and the market-state rule all apply), takes the best one and
opens a virtual futures position. It then watches the price and closes the
position at the take-profit, the stop-loss or the break-even stop.

Money rules (agreed with the owner):
- risk per trade: 1% of the money in the account (fees included);
- separate places for fast and slow trades (owner's choice): at most 3 on
  1m/3m/5m and 3 on 15m/1h, one per coin, and at most 4 in the same
  direction (coins tend to move together, so many longs are one big bet);
- leverage is set by the bot: the lowest that fits, at most 10x, and the
  liquidation price must stay beyond the stop-loss; if that does not fit,
  the position is made smaller (so the risk is less than 1%, never more);
- smart pause (owner's choice, instead of a daily stop): after 4 losing
  trades in a row, or a 5% fall since the last pause, no new trades for 3
  hours; strategies that lost over the last 24 hours (real and shadow
  trades) are left out for 12 hours;
- a 30% fall from the starting money switches the bot off.
The bot keeps scanning while it is switched off too: it then only learns
(records and follows signals in its memory) and opens nothing.
A signal is "stale" (skipped) when the price has moved more than a quarter
of the stop distance since the signal: the stop would then sit closer than
the strategy meant. Bigger timeframes are checked first, so their signals
do not wait behind the small ones.

The account is saved to a file, so it survives closing the app.
Futures funding payments are not counted yet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from . import config
from .analysis import closed_only, strategy_overview
from .brain import Brain
from . import pretrain
from .memory import Memory, features
from .scanner import reliable
from .strategies import LONG, STRATEGIES, Fees, breakeven_price, fee_ok, parse_params

TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"]
SCAN_ORDER = list(reversed(TIMEFRAMES))  # biggest first
STALE_PART = 0.25             # of the stop distance: further than this from the signal price = too late
MODE_OF = {"1m": "scalping", "3m": "scalping", "5m": "scalping", "15m": "daily", "1h": "daily"}
MARKET = "futures"            # long and short (spot cannot short)
RISK = 0.01                   # of the account, per trade
GROUP = {"1m": "fast", "3m": "fast", "5m": "fast", "15m": "slow", "1h": "slow"}
GROUP_SLOTS = {"fast": 3, "slow": 3}
MAX_OPEN = sum(GROUP_SLOTS.values())
MAX_SAME_SIDE = 4
MAX_LEVERAGE = 10
MAINTENANCE = 0.005           # part of the position the exchange keeps as a minimum (liquidation)
LIQ_BUFFER = 0.005            # extra distance between the stop-loss and the liquidation price
PAUSE_LOSSES = 4             # losing trades in a row
PAUSE_FALL = 0.05            # fall since the last pause (or the start)
PAUSE_SECONDS = 3 * 3600
RECOVER_WINS = 2          # a pause ends early when the last this-many results during it were all profits
BENCH_SECONDS = 12 * 3600    # strategies that lost lately are left out this long
BENCH_LOOKBACK = 24 * 3600
TOTAL_STOP = 0.30
POLL_SECONDS = 10
SCAN_DELAY = 3                # seconds after a candle closes before scanning (final price)
KEEP_CLOSED = 500
KEEP_EVENTS = 50


def default_path() -> Path:
    custom = os.environ.get("TRADING_BOT_DATA")
    base = Path(custom) if custom else Path.home() / ".trading-bot"
    return base / "paper.json"


# ---------------------------------------------------------------- sizing

@dataclass(frozen=True)
class Size:
    notional: float     # position value in USDT
    quantity: float     # coins
    leverage: int
    margin: float       # USDT put aside from the account
    risk: float         # USDT lost at the stop-loss, fees included
    liquidation: float  # price where the exchange would close the position


def liquidation_price(side: str, entry: float, leverage: int) -> float:
    if side == LONG:
        return entry * (1 - 1 / leverage + MAINTENANCE)
    return entry * (1 + 1 / leverage - MAINTENANCE)


def position_size(side: str, entry: float, stop: float, equity: float, free_margin: float,
                  fees: Fees) -> Optional[Size]:
    """Size so that the loss at the stop (with both taker fees) is RISK of the account.

    Leverage: the lowest that fits the slot (a third of the account), at most
    MAX_LEVERAGE, and low enough that liquidation lies beyond the stop.
    If that is not enough, the position gets smaller (less risk)."""
    if equity <= 0 or entry <= 0:
        return None
    stop_frac = abs(entry - stop) / entry
    if stop_frac <= 0:
        return None
    loss_frac = stop_frac + 2 * fees.taker / 100           # price move + fees in and out
    notional = equity * RISK / loss_frac
    slot = min(equity / MAX_OPEN, free_margin)
    if slot <= 0:
        return None
    # Highest leverage whose liquidation price is still beyond the stop (with a buffer).
    safe = math.floor(1 / (stop_frac + MAINTENANCE + LIQ_BUFFER))
    max_lev = max(1, min(MAX_LEVERAGE, safe))
    needed = max(1, math.ceil(notional / slot))
    leverage = min(needed, max_lev)
    notional = min(notional, slot * leverage)
    margin = notional / leverage
    return Size(notional=notional, quantity=notional / entry, leverage=leverage, margin=margin,
                risk=notional * loss_frac, liquidation=liquidation_price(side, entry, leverage))


def pnl(position: dict, exit_price: float, exit_fee: float) -> tuple[float, float]:
    """(result in USDT after both fees, fees paid)."""
    direction = 1 if position["side"] == LONG else -1
    gross = position["quantity"] * (exit_price - position["entryPrice"]) * direction
    fees = position["entryFee"] + position["quantity"] * exit_price * exit_fee / 100
    return gross - fees, fees


# ---------------------------------------------------------------- exits

def check_exit(position: dict, candles: list[dict], last_price: Optional[float], tf_seconds: int,
               now: float) -> Optional[tuple[float, str]]:
    """Exit (price, reason) if the stop or the target was reached, else None.

    Closed candles after the entry candle are checked with their high and low
    (stop first: if one candle touched both, it counts as the stop). Within
    the entry candle and the candle now forming only the live price is used,
    because part of those candles happened before the entry or is not known.
    Break-even moves the stop on closed candles, like in the history test."""
    long_ = position["side"] == LONG
    for c in candles:
        if c["time"] <= position["entryCandle"] or c["time"] < position["checkedFrom"]:
            continue
        if c["time"] + tf_seconds > now:
            break  # still forming
        stop, target = position["stop"], position["takeProfit"]
        if (c["low"] <= stop) if long_ else (c["high"] >= stop):
            reason = "breakeven" if position.get("breakevenAt") else "stop"
            return stop, reason
        if (c["high"] >= target) if long_ else (c["low"] <= target):
            return target, "target"
        position["checkedFrom"] = c["time"] + tf_seconds
        _maybe_breakeven(position, c["high"] if long_ else c["low"], c["time"])
    if last_price is not None:
        stop, target = position["stop"], position["takeProfit"]
        if (last_price <= stop) if long_ else (last_price >= stop):
            return stop, "breakeven" if position.get("breakevenAt") else "stop"
        if (last_price >= target) if long_ else (last_price <= target):
            return target, "target"
    return None


def _maybe_breakeven(position: dict, extreme: float, when: int) -> None:
    part = position.get("breakevenPart") or 0
    if not part or position.get("breakevenAt"):
        return
    long_ = position["side"] == LONG
    trigger = position["entryPrice"] + (position["takeProfit"] - position["entryPrice"]) * part
    if (extreme >= trigger) if long_ else (extreme <= trigger):
        position["stop"] = position["breakevenPrice"]
        position["breakevenAt"] = when


def is_stale(signal_price: float, price: float, stop: float) -> bool:
    """The price moved more than STALE_PART of the stop distance since the signal."""
    distance = abs(signal_price - stop)
    return distance > 0 and abs(price - signal_price) > STALE_PART * distance


# ---------------------------------------------------------------- choosing

def pick(candidates: list[dict], open_coins: set[str], slots: int,
         side_room: Optional[dict[str, int]] = None) -> list[dict]:
    """Best reliable signals first (profit factor, then number of trades), one per
    coin, at most `slots`, and no more per direction than `side_room` allows."""
    def score(c):
        pf = c["stats"]["profitFactor"]
        return (pf if pf is not None else float("inf"), c["stats"]["trades"])
    room = dict(side_room) if side_room is not None else None
    chosen, coins = [], set(open_coins)
    for c in sorted(candidates, key=score, reverse=True):
        if len(chosen) >= slots:
            break
        side = c["signal"]["side"]
        if c["symbol"] in coins or (room is not None and room.get(side, 0) <= 0):
            continue
        chosen.append(c)
        coins.add(c["symbol"])
        if room is not None:
            room[side] -= 1
    return chosen


def free_slots(positions: list[dict], timeframe: str) -> int:
    group = GROUP[timeframe]
    used = sum(1 for p in positions if GROUP.get(p["timeframe"]) == group)
    return GROUP_SLOTS[group] - used


def side_room(positions: list[dict]) -> dict[str, int]:
    return {side: MAX_SAME_SIDE - sum(1 for p in positions if p["side"] == side) for side in ("long", "short")}


# ---------------------------------------------------------------- the account

EVEN_PART = 1e-4    # a result smaller than this share of the position counts as break-even


def trade_outcome(trade: dict) -> str:
    """win / loss / even. A trade closed at the break-even stop (or with a result of practically
    zero, e.g. a billionth of a dollar from rounding) is "even", not a loss."""
    if trade.get("exitReason") == "breakeven" or abs(trade["pnl"]) < trade["notional"] * EVEN_PART:
        return "even"
    return "win" if trade["pnl"] > 0 else "loss"


def new_account(capital: float, now: float) -> dict:
    return {
        "version": 1,
        "capital": capital,
        "balance": capital,
        "status": "stopped",          # stopped | running | halted (30% loss)
        "mode": "auto",               # auto: all strategies | manual: the owner's choice
        "strategies": list(STRATEGIES),
        "positions": [],
        "closed": [],
        "events": [],
        "peakEquity": capital,
        "maxDrawdown": 0.0,
        "day": time.strftime("%Y-%m-%d", time.gmtime(now)),
        "dayStartEquity": capital,
        "lossStreak": 0,
        "profitCap": 0.0,        # owner's option: close a position once it is this many USDT in profit (0 = off)
        "pausedUntil": None,
        "pausedAt": None,
        "pauseReason": None,
        "pauseBase": capital,
        "benched": {},
        "lastScan": {},
        "createdAt": now,
        "nextId": 1,
    }


class Store:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) and data.get("version") == 1 else None
        except (OSError, ValueError):
            return None

    def save(self, account: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(account, f)
        os.replace(tmp, self.path)  # never a half-written file


Coins = Callable[[], Awaitable[list[tuple[str, str]]]]
History = Callable[[str, str], Awaitable[list[dict]]]        # (symbol, timeframe) -> long history
Recent = Callable[[str, str], Awaitable[list[dict]]]         # (symbol, timeframe) -> last candles


class PaperBot:
    def __init__(self, store: Store, coins: Coins, history: History, recent: Recent,
                 now: Callable[[], float] = time.time, fees: Optional[Fees] = None,
                 memory: Optional[Memory] = None, brain: Optional[Brain] = None):
        self.store = store
        self.memory = memory
        self.brain = brain                    # the learning signal filter (step B)
        self.training: Optional[asyncio.Task] = None
        self.pretraining: Optional[asyncio.Task] = None
        self.pretrain_progress = {"done": 0, "total": 0, "running": False}
        self.coins = coins
        self.history = history
        self.recent = recent
        self.now = now
        self.fees = fees or Fees(**config.DEFAULT_FEES[MARKET])
        self.account = store.load() or new_account(100.0, now())
        for k, v in new_account(self.account.get("capital", 100.0), now()).items():
            self.account.setdefault(k, v)  # files from older versions
        self.prices: dict[str, float] = {}    # last price per position id (for the screen)
        self.scanning: Optional[str] = None   # timeframe being scanned
        self.lock = asyncio.Lock()

    # ---- what the screen sees

    def equity(self) -> float:
        a = self.account
        open_pnl = sum(pnl(p, self.prices.get(p["id"], p["entryPrice"]), self.fees.taker)[0] for p in a["positions"])
        return a["balance"] + open_pnl

    def public(self) -> dict:
        a = self.account
        closed = a["closed"]
        wins = [t for t in closed if t["pnl"] > 0]
        equity = self.equity()
        summary = self.memory.summary() if self.memory else None
        positions = []
        for p in a["positions"]:
            price = self.prices.get(p["id"])
            positions.append({**p, "lastPrice": price,
                              "openPnl": pnl(p, price, self.fees.taker)[0] if price is not None else None})
        return {
            "capital": a["capital"],
            "balance": a["balance"],
            "equity": equity,
            "status": a["status"],
            "pausedUntil": a["pausedUntil"],
            "pauseReason": a["pauseReason"],
            "benched": {k: v for k, v in a["benched"].items() if v > self.now()},
            "memory": summary,
            "brain": {**self.brain.public(summary), "pretrain": self.pretrain_progress} if self.brain else None,
            "mode": a["mode"],
            "strategies": a["strategies"],
            "positions": positions,
            "closed": list(reversed(closed)),     # the whole kept history (up to KEEP_CLOSED)
            "events": list(reversed(a["events"][-20:])),
            "stats": {
                "trades": len(closed),
                "wins": len(wins),
                "winRate": len(wins) / len(closed) * 100 if closed else None,
                "netPnl": equity - a["capital"],
                "netPercent": (equity - a["capital"]) / a["capital"] * 100 if a["capital"] else 0,
                "todayPnl": equity - a["dayStartEquity"],
                "fees": sum(t["fees"] for t in closed),
                "maxDrawdown": a["maxDrawdown"] * 100,
            },
            "scanning": self.scanning,
            "lastScan": a["lastScan"],
            "timeframes": TIMEFRAMES,
            "rules": {"risk": RISK * 100, "maxOpen": MAX_OPEN, "maxFast": GROUP_SLOTS["fast"],
                      "maxSlow": GROUP_SLOTS["slow"], "maxSameSide": MAX_SAME_SIDE, "maxLeverage": MAX_LEVERAGE,
                      "pauseLosses": PAUSE_LOSSES, "pauseFall": PAUSE_FALL * 100,
                      "pauseHours": PAUSE_SECONDS / 3600, "recoverWins": RECOVER_WINS, "profitCap": self.account.get("profitCap", 0.0), "totalStop": TOTAL_STOP * 100,
                      "fees": {"maker": self.fees.maker, "taker": self.fees.taker}},
        }

    # ---- owner's buttons

    def _event(self, kind: str, **data) -> None:
        self.account["events"].append({"time": self.now(), "kind": kind, **data})
        del self.account["events"][:-KEEP_EVENTS]

    def save(self) -> None:
        self.store.save(self.account)

    def start(self) -> None:
        if self.account["status"] != "halted":
            self.account["status"] = "running"
            self._event("start")
            self.save()

    def stop(self) -> None:
        if self.account["status"] == "running":
            self.account["status"] = "stopped"
            self._event("stop")
            self.save()

    def reset(self, capital: float) -> None:
        cap = self.account.get("profitCap", 0.0)
        self.account = new_account(capital, self.now())
        self.account["profitCap"] = cap   # a setting, not a result: kept
        self.prices.clear()
        self._event("reset", capital=capital)
        self.save()

    def set_profit_cap(self, usd: float) -> None:
        self.account["profitCap"] = max(0.0, float(usd))
        self.save()

    async def close_position(self, position_id: int) -> bool:
        """Owner's button: close one open position now, at the current price (taker fee)."""
        # No waiting for the bot's lock: a long scan must not delay the owner's button.
        p = next((p for p in self.account["positions"] if p["id"] == position_id), None)
        if p is None:
            return False
        candles = await self.recent(p["symbol"], p["timeframe"])
        price = candles[-1]["close"] if candles else self.prices.get(p["id"], p["entryPrice"])
        if p not in self.account["positions"]:
            return False   # closed by the bot meanwhile
        self._close(p, price, "manual", self.now())
        self.save()
        return True

    async def close_all_and_stop(self) -> int:
        """Owner's button: close every open position now and switch the bot off."""
        ids = [p["id"] for p in self.account["positions"]]
        for i in ids:
            await self.close_position(i)
        self.stop()
        return len(ids)

    def set_mode(self, mode: str, strategies: list[str]) -> None:
        self.account["mode"] = mode
        self.account["strategies"] = list(STRATEGIES) if mode == "auto" else strategies
        self.save()

    # ---- the loop

    async def run_forever(self) -> None:
        while True:
            try:
                if self.account["status"] == "running":
                    await self.step()
                elif self.memory is not None:
                    await self.learn_only()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # never let one bad answer stop the bot
                logging.getLogger("trading_bot").warning("bot round failed", exc_info=True)
                self._event("error", message=str(error)[:200])
            self._maybe_learn()
            self._maybe_pretrain()
            await asyncio.sleep(POLL_SECONDS)

    def _maybe_pretrain(self) -> None:
        """Once a day: rebuild past signals of every chart from its history, in the background."""
        if self.memory is None or self.brain is None:
            return
        if self.pretraining is not None and not self.pretraining.done():
            return
        last = self.account.get("pretrainedAt")
        if pretrain.due(last, self.now()):
            self.pretraining = asyncio.create_task(self.pretrain_round())

    async def pretrain_round(self) -> int:
        """One round over all charts; charts done in the last day are skipped. Returns new signals."""
        memory = self.memory
        coins = await self.coins()
        progress = self.pretrain_progress
        progress.update(done=0, total=len(coins) * len(TIMEFRAMES), running=True)
        added = 0
        try:
            for tf in SCAN_ORDER:
                mode = MODE_OF[tf]
                settings = {k: parse_params(k, {}, mode) for k in STRATEGIES}
                for symbol, base in coins:
                    now = self.now()
                    if pretrain.due(memory.pretrain_time(symbol, tf), now):
                        try:
                            rows = closed_only(await self.history(symbol, tf), tf, now)
                            found = await asyncio.to_thread(pretrain.history_signals, symbol, base, tf, rows,
                                                            settings, mode, self.fees)
                            added += await asyncio.to_thread(memory.record_history, tf, found, now)
                            memory.set_pretrain_time(symbol, tf, now)
                        except Exception:
                            pass  # one bad chart does not stop the round; it is tried again next round
                    progress["done"] += 1
        finally:
            progress["running"] = False
        self.account["pretrainedAt"] = self.now()
        if added:
            self._event("pretrain", count=added)
            if self.brain is not None and self.brain.champion is None:
                self.brain.last = None   # learn right away from the new examples
        self.save()
        return added

    def _maybe_learn(self) -> None:
        """Every few hours the brain learns again, in the background (the bot keeps working)."""
        if self.brain is None or (self.training is not None and not self.training.done()):
            return
        if self.brain.due(self.now()):
            self.training = asyncio.create_task(self.learn())

    async def learn(self) -> dict:
        outcome = await asyncio.to_thread(self.brain.train)
        if outcome["result"] != "few":
            self._event("brain", reason=outcome["result"], version=outcome.get("version"))
            self.save()
        return outcome

    async def step(self) -> None:
        async with self.lock:
            now = self.now()
            self._new_day(now)
            await self._watch_positions(now)
            equity = self.equity()
            self._track_drawdown(equity)
            if equity <= self.account["capital"] * (1 - TOTAL_STOP):
                self.account["status"] = "halted"
                self._event("halted", equity=equity)
                self.save()
                return
            self._update_pause(now, equity)
            for tf in self._due_timeframes(now):
                # Scanned even when there is no free place: the memory still learns from the signals.
                trade = not self._paused(now) and free_slots(self.account["positions"], tf) > 0
                await self._scan_and_open(tf, now, trade=trade)
            self.save()

    async def learn_only(self) -> None:
        """Bot switched off: keep scanning so the memory keeps learning, open nothing."""
        async with self.lock:
            now = self.now()
            for tf in self._due_timeframes(now):
                await self._scan_and_open(tf, now, trade=False)
            self.save()

    def _due_timeframes(self, now: float) -> list[str]:
        due = []
        for tf in SCAN_ORDER:
            period = int((now - SCAN_DELAY) // config.TIMEFRAME_SECONDS[tf])
            if self.account["lastScan"].get(tf, {}).get("period") != period:
                self.account["lastScan"][tf] = {"period": period, "time": now}
                due.append(tf)
        return due

    # ---- smart pause

    def _paused(self, now: float) -> bool:
        until = self.account["pausedUntil"]
        return until is not None and now < until

    def _recovered(self, now: float) -> bool:
        """During a pause: did the last RECOVER_WINS results all end in profit? Results are the
        bot's own trades that closed during the pause plus the reliable signals of the strategies it
        may use that came during the pause and ended (followed in the memory, no money at risk)."""
        a = self.account
        since = a.get("pausedAt")
        if since is None:
            return False
        results = [(t["exitTime"], t.get("outcome") or trade_outcome(t)) for t in a["closed"]
                   if t["exitTime"] >= since and t.get("exitReason") != "manual"]
        if self.memory is not None:
            benched = {k for k, until in a["benched"].items() if until > now}
            allowed = set(a["strategies"]) - benched
            results += [(when, status) for when, status, kind in self.memory.outcomes_since(since) if kind in allowed]
        results = sorted(r for r in results if r[1] in ("win", "loss"))
        last = results[-RECOVER_WINS:]
        return len(last) == RECOVER_WINS and all(status == "win" for _, status in last)

    def _update_pause(self, now: float, equity: float) -> None:
        a = self.account
        early = a["pausedUntil"] is not None and now < a["pausedUntil"] and self._recovered(now)
        if a["pausedUntil"] is not None and (now >= a["pausedUntil"] or early):
            a["pausedUntil"] = None
            a["pausedAt"] = None
            a["pauseReason"] = None
            a["lossStreak"] = 0
            a["pauseBase"] = equity
            if early:
                self._event("resume", reason="recovered")
            else:
                self._event("resume")
        if a["pausedUntil"] is not None:
            return
        reason = None
        if a["lossStreak"] >= PAUSE_LOSSES:
            reason = "streak"
        elif equity <= a["pauseBase"] * (1 - PAUSE_FALL):
            reason = "fall"
        if reason is None:
            return
        a["pausedUntil"] = now + PAUSE_SECONDS
        a["pausedAt"] = now
        a["pauseReason"] = reason
        benched = []
        if self.memory is not None:
            for kind, result in self.memory.strategy_results(now - BENCH_LOOKBACK).items():
                if result < 0:
                    a["benched"][kind] = now + BENCH_SECONDS
                    benched.append(kind)
        self._event("pause", reason=reason, until=a["pausedUntil"], strategies=benched)

    def _new_day(self, now: float) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        if day != self.account["day"]:
            self.account["day"] = day
            self.account["dayStartEquity"] = self.equity()

    def _track_drawdown(self, equity: float) -> None:
        a = self.account
        a["peakEquity"] = max(a["peakEquity"], equity)
        if a["peakEquity"] > 0:
            a["maxDrawdown"] = max(a["maxDrawdown"], (a["peakEquity"] - equity) / a["peakEquity"])

    async def _watch_positions(self, now: float) -> None:
        for p in list(self.account["positions"]):
            candles = await self.recent(p["symbol"], p["timeframe"])
            if not candles:
                continue
            last = candles[-1]["close"]
            self.prices[p["id"]] = last
            hit = check_exit(p, candles, last, config.TIMEFRAME_SECONDS[p["timeframe"]], now)
            cap = self.account.get("profitCap") or 0
            if hit is None and cap > 0 and pnl(p, last, self.fees.taker)[0] >= cap:
                hit = (last, "cap")   # owner's profit cap: take the small profit now
            if hit:
                self._close(p, hit[0], hit[1], now)

    def _close(self, p: dict, price: float, reason: str, now: float) -> None:
        if p not in self.account["positions"]:
            return   # already closed (e.g. by the owner's button while the bot was checking it)
        exit_fee = self.fees.maker if reason == "target" else self.fees.taker
        result, fees = pnl(p, price, exit_fee)
        self.account["balance"] += result
        self.account["positions"].remove(p)
        self.prices.pop(p["id"], None)
        trade = {**p, "exitPrice": price, "exitTime": now, "exitReason": reason, "pnl": result, "fees": fees,
                 "pnlPercent": result / p["margin"] * 100 if p["margin"] else 0}
        self.account["closed"].append(trade)
        del self.account["closed"][:-KEEP_CLOSED]
        outcome = trade_outcome(trade)
        trade["outcome"] = outcome
        if reason == "manual":
            pass   # closed by the owner: says nothing about the market, the pause count stays
        elif outcome == "loss":
            self.account["lossStreak"] += 1
        elif outcome == "win":
            self.account["lossStreak"] = 0
        # break-even: neither a loss nor a win, the count stays as it was
        if self.memory is not None:
            self.memory.save_trade(trade, now)
        self._event("close", symbol=p["base"], reason=reason, pnl=result)

    async def _scan_and_open(self, tf: str, now: float, trade: bool = True) -> None:
        mode = MODE_OF[tf]
        settings = {k: parse_params(k, {}, mode) for k in STRATEGIES}
        benched = {k for k, until in self.account["benched"].items() if until > now}
        allowed = set(self.account["strategies"]) - benched
        memory = self.memory
        gate = asyncio.Semaphore(8)
        candidates: list[dict] = []
        self.scanning = tf

        def work(symbol: str, base: str, rows: list[dict]) -> None:
            """The heavy part of one chart (runs in a worker thread so the engine keeps answering the screen)."""
            overview = strategy_overview(rows, tf, settings, None, mode, now=now, fees=self.fees)
            if memory is not None:  # results of earlier signals of this chart
                memory.resolve(symbol, tf, closed_only(rows, tf, now), settings, self.fees, now)
            extra = {"adx": overview.get("adx"), "atrRatio": overview.get("atrRatio")}
            for row in overview["rows"]:
                entry = {"symbol": symbol, "base": base, "strategy": row["strategy"],
                         "marketState": overview["marketState"], "stats": row["stats"], "signal": row.get("signal")}
                if not entry["signal"]:
                    continue
                ok = reliable(entry)
                if memory is not None:  # every signal is remembered (traded or not, reliable or not)
                    feats = features(entry, extra, self.fees)
                    feats["reliable"] = ok
                    entry["memoryKey"] = memory.record(entry, tf, feats, now, reliable=ok)
                    if ok and self.brain is not None:
                        entry["chance"] = self.brain.chance(feats, row["strategy"], tf, entry["signal"]["side"])
                        if entry["chance"] is not None:
                            memory.set_chance(entry["memoryKey"], entry["chance"])
                if ok and row["strategy"] in allowed:   # the bot trades reliable signals only
                    candidates.append(entry)

        async def one(symbol: str, base: str) -> None:
            async with gate:
                try:
                    rows = await self.history(symbol, tf)
                    await asyncio.to_thread(work, symbol, base, rows)
                except Exception:
                    return

        try:
            await asyncio.gather(*(one(s, b) for s, b in await self.coins()))
        finally:
            self.scanning = None
        if not trade:
            return
        if self.brain is not None:  # the brain's filter: skip signals with a low chance of profit
            weak = [c for c in candidates if not self.brain.allows(c.get("chance"))]
            if weak:
                candidates = [c for c in candidates if self.brain.allows(c.get("chance"))]
                for c in weak:
                    if memory is not None and c.get("memoryKey"):
                        memory.mark(c["memoryKey"], skip_reason="brain")
                self._event("skip", reason="brain", timeframe=tf, count=len(weak))
        open_coins = {p["symbol"] for p in self.account["positions"]}
        positions = self.account["positions"]
        chosen = pick(candidates, open_coins, free_slots(positions, tf), side_room(positions))
        for c in chosen:
            await self._open(c, tf, now, settings[c["strategy"]])
        chosen_keys = {c.get("memoryKey") for c in chosen}
        if memory is not None:
            for c in candidates:
                if c.get("memoryKey") not in chosen_keys:
                    memory.mark(c["memoryKey"], skip_reason="full")
        left = len({c["symbol"] for c in candidates} - open_coins) - len(chosen)
        if left > 0:
            self._event("skip", reason="full", timeframe=tf, count=left)

    async def _open(self, c: dict, tf: str, now: float, params: dict) -> None:
        recent = await self.recent(c["symbol"], tf)
        if not recent:
            return
        entry = recent[-1]["close"]             # the price now
        s = c["signal"]
        stop, target = s["stopLoss"], s["takeProfit"]
        long_ = s["side"] == LONG
        def skip(reason: str) -> None:
            self._event("skip", symbol=c["base"], timeframe=tf, reason=reason)
            if self.memory is not None and c.get("memoryKey"):
                self.memory.mark(c["memoryKey"], skip_reason=reason)

        # The price may have moved since the signal: skip if it already passed the stop or the target,
        # or moved too far for the stop to still be where the strategy meant it.
        if (entry <= stop or entry >= target) if long_ else (entry >= stop or entry <= target):
            return skip("past")
        if is_stale(s["entry"], entry, stop):
            return skip("stale")
        if not fee_ok(entry, stop, self.fees, params.get("fee_ratio", 0)):
            return skip("fee")
        used = sum(p["margin"] for p in self.account["positions"])
        equity = self.equity()
        size = position_size(s["side"], entry, stop, equity, equity - used, self.fees)
        if size is None or size.notional <= 0:
            return
        a = self.account
        position = {
            "id": a["nextId"], "symbol": c["symbol"], "base": c["base"], "timeframe": tf,
            "strategy": c["strategy"], "side": s["side"], "entryTime": now, "entryPrice": entry,
            "entryCandle": recent[-1]["time"], "checkedFrom": recent[-1]["time"],
            "signalTime": s["time"], "stopLoss": stop, "stop": stop, "takeProfit": target,
            "quantity": size.quantity, "notional": size.notional, "leverage": size.leverage,
            "margin": size.margin, "risk": size.risk, "liquidation": size.liquidation,
            "entryFee": size.notional * self.fees.taker / 100,
            "breakevenPart": params.get("breakeven", 0),
            "breakevenPrice": breakeven_price(s["side"], entry, self.fees), "breakevenAt": None,
            "history": {"trades": c["stats"]["trades"], "winRate": c["stats"].get("winRate"),
                        "profitFactor": c["stats"]["profitFactor"]},
        }
        a["nextId"] += 1
        a["positions"].append(position)
        self.prices[position["id"]] = entry
        self._event("open", symbol=c["base"], side=s["side"], timeframe=tf, strategy=c["strategy"],
                    leverage=size.leverage)
        if self.memory is not None and c.get("memoryKey"):
            self.memory.mark(c["memoryKey"], taken=True)
