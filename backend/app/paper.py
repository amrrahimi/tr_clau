"""Paper trading: the bot trades with virtual money (owner's request).

Everything is chosen by the bot: it scans the coins (top 100 by volume, the 30 most volatile, or
the owner's list) on the ticked timeframes (1m-4h) with the strategies of each timeframe, keeps
signals that pass the fee rule per timeframe, the market-state rule and, on the slow charts, the strict
rule (the "reliable" rule was removed by the owner 2026-11-06; optionally the brain and the AI approval), and opens a virtual futures position.
It then watches the price and closes the position at the take-profit, the stop-loss, the
break-even stop or the owner's profit cap. The owner can move the stop and the target on the chart.

Money rules (agreed with the owner):
- risk per trade: 1% of the money in the account (fees included);
- no limit on the number of positions or on positions in the same direction (owner 2026-11-02),
  one per coin; the margin of one position is at most 1/6 of the money, so new trades stop when
  the free margin runs out;
- leverage is set by the bot: the lowest that fits, at most 10x, and the
  liquidation price must stay beyond the stop-loss; if that does not fit,
  the position is made smaller (so the risk is less than 1%, never more);
- smart pause (owner sets it in the panel, 0 = off; defaults 4 losses in a row / 5% fall): no new
  trades for 3 hours; strategies that lost over the last 24 hours are left out for 12 hours;
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
import copy
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
from . import advisor, pretrain, telegram
from .memory import Memory, features
from .scanner import reliable
from .strategies import LONG, STRATEGIES, Fees, breakeven_price, fee_ok, parse_params, reward_ok

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
# Owner's "focus" switch (2026-11-10, research): 5m + 15m on the volatile coins; the earlier settings are kept
# and come back when the switch is turned off.
FOCUS_TIMEFRAMES = ("5m", "15m")
FOCUS_KEYS = ("chosenTimeframes", "coinMode", "coins")
OLD_TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"]   # the bot's list before 30m and 4h were added
SCAN_ORDER = list(reversed(TIMEFRAMES))  # biggest first
STALE_PART = 0.10             # of the stop distance: further than this toward the target = too late
                              # (owner 2026-11-07: 10%, was 25%; the target stays, so a late entry exits sooner)
MODE_OF = {"1m": "scalping", "3m": "scalping", "5m": "scalping", "15m": "daily", "30m": "daily", "1h": "daily",
           "4h": "daily"}
MARKET = "futures"            # long and short (spot cannot short)
RISK = 0.01                   # of the account, per trade
GROUP = {"1m": "fast", "3m": "fast", "5m": "fast", "15m": "slow", "30m": "slow", "1h": "slow", "4h": "slow"}
# Owner 2026-11-02: no limit on the number of open positions, per group or per direction (one per
# coin; it stops when the free margin runs out). Easy to bring back: put numbers here.
UNLIMITED = 1000
GROUP_SLOTS = {"fast": UNLIMITED, "slow": UNLIMITED}
MAX_SAME_SIDE = UNLIMITED
MAX_OPEN = 6                  # sizing: one position may lock at most a sixth of the money as margin
MAX_POSITIONS = 6             # owner 2026-11-07: at most 6 open trades (waiting limit orders count too)

# The owner's design of 2026-11-07 (steps 2-3): the trend of a coin is read on a higher timeframe and a trade
# goes only with it; in a range nothing opens. Efficiency ratio over TREND_CANDLES closed candles: the straight
# move divided by the whole path; at least TREND_ER = trend (direction: the sign of the move), else range.
# Tested 2026-11-07 (18k engine trades): against the higher trend was the worst in every method; independent
# coins on 1h with the 4h trend +0.12 R (both halves positive).
HIGHER_TF = {"1m": "1h", "3m": "1h", "5m": "1h", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d"}
TREND_CANDLES = 20
TREND_ER = 0.3
# Coins that follow Bitcoin (correlation of 1h returns over BTC_LINK_HOURS at least BTC_FOLLOWER) trade only
# with Bitcoin's trend on the same higher timeframe, and not while Bitcoin is in a range (followers then lost
# -0.26 R in both halves, 5.7k live signals). Independent coins: their own trend only. Worked out once a day.
BTC_SYMBOL = "BTC/USDT:USDT"
BTC_FOLLOWER = 0.2
BTC_LINK_HOURS = 720
BTC_LINK_SECONDS = 86400
# Step "blocked money" (owner 2026-11-07): after TIME_BE_CANDLES candles a trade still open aims at break-even:
# in profit, the stop goes to break-even; in loss, it closes when the price comes back to the entry (fees paid).
# Tested on 5m / 15m: -0.18 -> -0.15 and -0.11 -> -0.09 R, better in both halves (no effect on 1h).
# Owner 2026-11-09: long positions are looked at again every few minutes (per timeframe, settable). If the
# trend turned against the position: in profit -> closed at once; in a loss -> the owner is asked on Telegram
# (close / go on); no answer -> asked again at the next look.
REVIEW_AFTER_CANDLES = 20
TELEGRAM_POLL_SECONDS = 3.0
TELEGRAM_EDIT_SECONDS = 300   # a new stop / target price is taken within 5 minutes of the button
REVIEW_EVERY = {"1m": 10, "3m": 10, "5m": 15, "15m": 15, "30m": 15, "1h": 15, "4h": 60}   # minutes
TIME_BE_CANDLES = {"1m": 12, "3m": 12, "5m": 12, "15m": 12}

# Owner's rule: trades on the slow charts take long and move a lot, so they must be much surer.
# A signal on 15m / 1h is traded only if its strategy did clearly well on that coin's history.
STRICT_TIMEFRAMES: tuple[str, ...] = ()   # owner 2026-11-01: off (too strict with the other filters)
STRICT_TRADES = 20          # at least this many past trades (10 elsewhere)
STRICT_PROFIT_FACTOR = 1.5  # wins at least 1.5 times the losses (above 1 elsewhere)
ADVICE_PART = 0.5           # at this share of the way to the target the bot advises: hold or close


@dataclass(frozen=True)
class Profile:
    """How the bot trades (one account since the barrage account was removed on 2026-11-02)."""
    name: str = "main"
    timeframes: tuple[str, ...] = tuple(TIMEFRAMES)
    group_slots: tuple[tuple[str, int], ...] = tuple(GROUP_SLOTS.items())
    max_same_side: int = MAX_SAME_SIDE
    all_signals: bool = False     # True: not only reliable signals
    # The "reliable" rule (scanner.reliable) as a trade filter: removed by the owner 2026-11-06. On 15k live
    # signals the rejected ones did as well (34.8% won, -0.137 R) as the passed ones (32.6%, -0.141 R),
    # better on 30m (+0.42 vs +0.14 R for his strategies), while it threw away 72% of the signals. It is still
    # worked out and kept in memory for every signal, to compare with a better rule later.
    use_reliable: bool = False
    smart_pause: bool = True
    advice: bool = False   # half-way "hold or close?" advice: removed by the owner 2026-11-05 (profit lock does it)
    default_cap: float = 0.0
    size_slots: int = MAX_OPEN    # sizing: one position may use at most equity / size_slots as margin

    @property
    def slots(self) -> dict[str, int]:
        return dict(self.group_slots)

    @property
    def max_open(self) -> int:
        return sum(self.slots.values())


MAIN = Profile()
FLOW_SECONDS = 600          # the screen's counter: what happened to the signals in the last 10 minutes
MAX_LEVERAGE = 10
MAINTENANCE = 0.005           # part of the position the exchange keeps as a minimum (liquidation)
LIQ_BUFFER = 0.005            # extra distance between the stop-loss and the liquidation price
PAUSE_LOSSES = 4             # default: losing trades in a row (the owner can change it, 0 = off)
PAUSE_FALL = 0.05            # default: fall since the last pause or the start (owner can change it, 0 = off)
MAX_PAUSE_LOSSES = 50
MAX_PAUSE_FALL = 50.0        # percent
MAX_BRAIN_THRESHOLD = 0.6    # the owner's brain knob goes from 0 (off) to this
BTC = "BTC/USDT:USDT"        # the market's direction, part of the AI's context
# When the AI does not answer the owner is asked; owner 2026-11-03: with no answer from him either,
# the trade opens by itself after ASK_AUTO_SECONDS (the usual price checks still decide at that moment).
ASK_AUTO_SECONDS = 30.0
# Limit entry (owner's switch, 2026-11-04; paper only, nothing is sent to the exchange): instead of
# buying at the market price (taker fee) the bot places a limit order a little better than the price
# now (maker fee). LIMIT_OFFSET: how much better, as a share of the stop distance. The order fills only
# when the price goes beyond it (touching is not enough), and is cancelled after LIMIT_EXPIRE_CANDLES
# candles of the signal's timeframe or when the price reaches the target or the stop first.
LIMIT_OFFSET = 0.1
LIMIT_EXPIRE_CANDLES = 1
# Profit lock (owner 2026-11-04, off by default): at LOCK_TRIGGER of the way to the target the stop moves
# to LOCK_AT of the way. Tested: 10.7k trades -0.103 R -> -0.088 R (both halves better).
LOCK_TRIGGER = 0.8
LOCK_AT = 0.4
ORDER_CANDLE_TF = "1m"          # waiting orders are checked on 1m candles
ORDER_CANDLE_SECONDS = 60
PAUSE_SECONDS = 3 * 3600
RECOVER_WINS = 2          # a pause ends early when the last this-many results during it were all profits
BENCH_SECONDS = PAUSE_SECONDS  # strategies that lost lately are left out as long as the pause
BENCH_MIN_RESULTS = 5        # ... but only with enough results to judge (a few unlucky signals are not enough)
BENCH_LOOKBACK = 24 * 3600
TOTAL_STOP = 0.30
POLL_SECONDS = 10
PERFORMANCE_SECONDS = 60      # per-strategy results on the screen are recounted at most this often


def _really_cancelled() -> bool:
    """True when this task itself is being cancelled (the app is closing), not just a request inside it."""
    task = asyncio.current_task()
    return task is None or task.cancelling() > 0
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
                  fees: Fees, max_open: int = MAX_OPEN) -> Optional[Size]:
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
    slot = min(equity / max_open, free_margin)
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
               now: float, hole_before: Optional[int] = None) -> Optional[tuple[float, str]]:
    """Exit (price, reason) if the stop or the target was reached, else None.

    Closed candles after the entry candle are checked with their high and low
    (stop first: if one candle touched both, it counts as the stop; a candle that opened past the
    stop exits at its open). Within
    the entry candle and the candle now forming only the live price is used,
    because part of those candles happened before the entry or is not known; a live price past
    the stop exits at that price (slippage), a live price past the target at the target.
    Break-even moves the stop on closed candles, like in the history test.
    hole_before: the first candle after candles the bot never got (it was not watching and the
    exchange did not give them): there the stop or target fills at its own price, as the order on an
    exchange would have, not at that candle's open (that would read the missing hours as a gap)."""
    long_ = position["side"] == LONG
    for c in candles:
        if c["time"] <= position["entryCandle"] or c["time"] < position["checkedFrom"]:
            continue
        if c["time"] + tf_seconds > now:
            break  # still forming
        stop, target = position["stop"], position["takeProfit"]
        be_exit = position.get("beExit")
        if (c["low"] <= stop) if long_ else (c["high"] >= stop):
            reason = _stop_reason(position)
            # A gap past the stop (the candle opened beyond it) fills at the open, worse than the stop.
            gapped = (c["open"] < stop) if long_ else (c["open"] > stop)
            if c["time"] == hole_before:
                gapped = False
            return (c["open"] if gapped else stop), reason
        if (c["high"] >= target) if long_ else (c["low"] <= target):
            return target, "target"
        if be_exit is not None and ((c["high"] >= be_exit) if long_ else (c["low"] <= be_exit)):
            return be_exit, "timeBe"
        position["checkedFrom"] = c["time"] + tf_seconds
        _maybe_breakeven(position, c["high"] if long_ else c["low"], c["time"])
        _maybe_lock(position, c["high"] if long_ else c["low"], c["time"])
        _maybe_time_be(position, c, tf_seconds)
    if last_price is not None:
        stop, target = position["stop"], position["takeProfit"]
        if (last_price <= stop) if long_ else (last_price >= stop):
            if hole_before is not None and not any(c["time"] >= hole_before and c["time"] + tf_seconds <= now
                                                   for c in candles):
                return stop, _stop_reason(position)   # crossed while unseen: the exchange's stop order
            # The price seen is already past the stop: the stop order fills there, not at the stop.
            return last_price, _stop_reason(position)
        if (last_price >= target) if long_ else (last_price <= target):
            return target, "target"
        be_exit = position.get("beExit")
        if be_exit is not None and ((last_price >= be_exit) if long_ else (last_price <= be_exit)):
            return be_exit, "timeBe"
        _maybe_lock(position, last_price, int(now))   # the price seen now can lock the profit too
    return None


MAX_REWARD = 4.0   # a target further than this many times the risk is not what any strategy was tested with


def anchor_target(side: str, signal_entry: Optional[float], entry: float, stop: float, target: float) -> Optional[float]:
    """The target for the real entry price (owner 2026-11-10: targets were too far). The strategy's own
    reward:risk (measured at the signal's price, at most MAX_REWARD) is kept from the price actually
    entered at, so a better entry (limit order, price moved toward the stop) brings the target closer
    instead of leaving it at 3-8 times the new, smaller risk. Never further than the signal's target.
    None when the levels make no sense (target at or below zero, entry past the stop)."""
    d = 1 if side == LONG else -1
    base = signal_entry if signal_entry is not None else entry
    risk0, risk = (base - stop) * d, (entry - stop) * d
    if risk <= 0 or target <= 0:
        return None
    reward = min((target - base) * d / risk0, MAX_REWARD) if risk0 > 0 else MAX_REWARD
    if reward <= 0:
        return None
    new = entry + d * reward * risk
    new = min(new, target) if d == 1 else max(new, target)
    return new if new > 0 and (new - entry) * d > 0 else None


def check_minutes(position: dict, minutes: list[dict], now: float) -> Optional[tuple[float, str]]:
    """The part of the chart's candle that is still forming, minute by minute (owner 2026-11-09, audit):
    like a stop order on the exchange, a stop crossed inside a minute fills at the stop, and at that
    minute's open only when the minute opened past it (a gap); the target fills at the target. The
    minute of the entry is left out (part of it was before the entry). The minute still forming counts
    too: what it has done so far is after the entry. Returns (price, reason) or None."""
    long_ = position["side"] == LONG
    start = max(position["checkedFrom"], (int(position.get("entryTime") or position["entryCandle"]) // 60) * 60 + 60,
                position.get("checkedMinute") or 0)
    for m in minutes:
        if m["time"] < start or m["time"] > now:
            continue
        stop, target = position["stop"], position["takeProfit"]
        if (m["low"] <= stop) if long_ else (m["high"] >= stop):
            gapped = (m["open"] < stop) if long_ else (m["open"] > stop)
            return (m["open"] if gapped else stop), _stop_reason(position)
        if (m["high"] >= target) if long_ else (m["low"] <= target):
            return target, "target"
        be_exit = position.get("beExit")
        if be_exit is not None and ((m["high"] >= be_exit) if long_ else (m["low"] <= be_exit)):
            return be_exit, "timeBe"
        _maybe_lock(position, m["high"] if long_ else m["low"], int(m["time"]))
        if m["time"] + 60 <= now:
            position["checkedMinute"] = m["time"] + 60   # closed minutes are not looked at again
    return None


def _maybe_time_be(position: dict, candle: dict, tf_seconds: int) -> None:
    """After TIME_BE_CANDLES closed candles the owner is asked on Telegram (owner 2026-11-10: not
    automatic any more); see time_be_answer. Marked here once; the message is sent by the bot."""
    n = TIME_BE_CANDLES.get(position.get("timeframe", ""))
    if not n or position.get("timeBeAt") or candle["time"] < position["entryCandle"] + n * tf_seconds:
        return
    long_ = position["side"] == LONG
    be = position["breakevenPrice"]
    position["timeBeAt"] = candle["time"]
    position["timeBeAsk"] = {"time": candle["time"], "inProfit": (candle["close"] > be) if long_ else (candle["close"] < be),
                             "sent": False, "answer": None}


def time_be_answer(position: dict, price: float, when: int) -> str:
    """The owner said "break-even": in profit the stop moves to break-even; in a loss the trade will close
    at break-even when the price comes back (beExit). Returns what was done: "stop" | "exit" | "none"."""
    long_ = position["side"] == LONG
    be = position["breakevenPrice"]
    if (price > be) if long_ else (price < be):
        if (be > position["stop"]) if long_ else (be < position["stop"]):
            position["stop"] = be
            position["breakevenAt"] = when
            return "stop"
        return "none"
    position["beExit"] = be
    return "exit"


def _stop_reason(position: dict) -> str:
    """Why the stop closed it: lock (the profit lock had moved it), breakeven, or a plain stop."""
    if position.get("lockedAt"):
        return "lock"
    return "breakeven" if position.get("breakevenAt") else "stop"


def _maybe_lock(position: dict, extreme: float, when: int) -> None:
    """Profit lock (owner's option): once the price has gone lock["trigger"] of the way to the target
    (e.g. 0.8), the stop moves to lock["at"] of the way (e.g. 0.4); the target stays. Only ever moves
    the stop toward profit, and once (until the owner moves the stop himself)."""
    lock = position.get("lock")
    if not lock or position.get("lockedAt"):
        return
    long_ = position["side"] == LONG
    way = position["takeProfit"] - position["entryPrice"]
    trigger = position["entryPrice"] + way * lock["trigger"]
    if not ((extreme >= trigger) if long_ else (extreme <= trigger)):
        return
    new_stop = position["entryPrice"] + way * lock["at"]
    if (new_stop > position["stop"]) if long_ else (new_stop < position["stop"]):
        position["stop"] = new_stop
        position["lockedAt"] = when


def price_step(candles: list[dict]) -> Optional[float]:
    """The coin's price step (tick), read from the decimals its candle prices use (e.g. 0.00001)."""
    decimals = 0
    for c in candles[-60:]:
        for k in ("open", "high", "low", "close"):
            text = repr(float(c[k]))
            if "e" in text or "E" in text:
                return None   # very small or large numbers: no rounding
            if "." in text:
                decimals = max(decimals, len(text.split(".")[1].rstrip("0")))
    return 10 ** -decimals if candles else None


def to_step(price: float, step: Optional[float], down: bool) -> float:
    """Round a price to the step: down (a buy order) or up (a sell order), so it stays a little better."""
    if not step:
        return price
    n = price / step
    n = math.floor(n + 1e-9) if down else math.ceil(n - 1e-9)
    return round(n * step, 12)


def _maybe_breakeven(position: dict, extreme: float, when: int) -> None:
    part = position.get("breakevenPart") or 0
    if not part or position.get("breakevenAt"):
        return
    long_ = position["side"] == LONG
    trigger = position["entryPrice"] + (position["takeProfit"] - position["entryPrice"]) * part
    if (extreme >= trigger) if long_ else (extreme <= trigger):
        be = position["breakevenPrice"]
        if (be <= position["stop"]) if long_ else (be >= position["stop"]):
            return   # the stop (moved by the owner) already locks more than break-even
        position["stop"] = be
        position["breakevenAt"] = when


def is_stale(signal_price: float, price: float, stop: float) -> bool:
    """The price moved more than STALE_PART of the stop distance since the signal, toward the target
    (a late entry: less profit left). A move toward the stop is a better entry (owner 2026-11-05: e.g. a
    short signal and the price went up): never stale; the stop itself, the fee rule and the reward rule
    are checked at the price now as before."""
    distance = abs(signal_price - stop)
    toward_target = (price - signal_price) * (signal_price - stop) > 0
    return distance > 0 and toward_target and abs(price - signal_price) > STALE_PART * distance


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


def free_slots(positions: list[dict], timeframe: str, slots: Optional[dict[str, int]] = None) -> int:
    group = GROUP[timeframe]
    used = sum(1 for p in positions if GROUP.get(p["timeframe"]) == group)
    return (slots or GROUP_SLOTS)[group] - used


def side_room(positions: list[dict], max_same_side: int = MAX_SAME_SIDE) -> dict[str, int]:
    return {side: max_same_side - sum(1 for p in positions if p["side"] == side) for side in ("long", "short")}


def strict_ok(entry: dict, timeframe: str) -> bool:
    """The extra-careful rule for the slow charts (other charts: always True)."""
    if timeframe not in STRICT_TIMEFRAMES:
        return True
    s = entry["stats"]
    pf = s.get("profitFactor")
    return (s.get("trades") or 0) >= STRICT_TRADES and (pf is None or pf >= STRICT_PROFIT_FACTOR) \
        and (s.get("netPercent") or 0) > 0


# ---------------------------------------------------------------- the account

# Break-even per timeframe, chosen from the history test of 2026-10-31 (all strategies, 100 coins,
# after fees, avg R): off was best on 3m / 5m / 15m (and the fast charts are noisy), at 50% was best
# on 1h. The differences were small; the owner saw fast trades closed at break-even just before the target.
# 30m and 4h (added 2026-11-02, owner: trade the slower charts) have no test yet: 30m like 15m, 4h like 1h.
BREAKEVEN_BY_TF = {"1m": 0.0, "3m": 0.0, "5m": 0.0, "15m": 0.0, "30m": 0.0, "1h": 0.5, "4h": 0.5}

# Most of the stop distance the round-trip fee may take, per timeframe (main bot only). Chosen from the
# bot's memory on 2026-11-02 (169k history signals, checked on the first 60% and again on the last 40%
# of each timeframe): signals whose fee took under 5% of the stop distance were about break-even on
# 1m/5m/15m/1h, everything above lost more the higher the share; on 3m the 5-10% group held up too.
# The old common limit was 0.33.
# 30m and 4h: no data yet, the limit of their neighbours (15m and 1h).
FEE_RATIO_BY_TF = {"1m": 0.05, "3m": 0.10, "5m": 0.05, "15m": 0.05, "30m": 0.05, "1h": 0.05, "4h": 0.05}


# The strategies the main bot scans and trades, per timeframe. Owner (2026-11-01): the earlier short
# list (only the strategies near break-even in the history test, none on 1m) stacked with the other
# filters left the bot without a single trade for hours. Now every strategy on every timeframe; the
# "reliable" rule, the brain's filter and the smart pause choose. The owner ticks the timeframes.
BOT_STRATEGIES_BY_TF: dict[str, tuple[str, ...]] = {tf: tuple(STRATEGIES) for tf in TIMEFRAMES}
BOT_STRATEGIES: tuple[str, ...] = tuple(k for k in STRATEGIES
                                        if any(k in kinds for kinds in BOT_STRATEGIES_BY_TF.values()))


def all_settings(tf: str) -> dict[str, dict]:
    """Settings of every strategy as the bot would use them on this timeframe."""
    settings = {k: parse_params(k, {}, MODE_OF[tf]) for k in STRATEGIES}
    for params in settings.values():
        params["breakeven"] = BREAKEVEN_BY_TF[tf]
    return settings


def bot_settings(tf: str) -> dict[str, dict]:
    """Settings of the strategies the main bot uses on this timeframe."""
    chosen = BOT_STRATEGIES_BY_TF.get(tf, tuple(STRATEGIES))
    settings = {k: v for k, v in all_settings(tf).items() if k in chosen}
    if tf in FEE_RATIO_BY_TF:
        for params in settings.values():
            params["fee_ratio"] = FEE_RATIO_BY_TF[tf]
    return settings


# Changes when strategies are added or the bot's list changes: every chart is pre-trained again once.
STRATEGY_SET = f"{len(STRATEGIES)}b{len(BOT_STRATEGIES)}"
EVEN_PART = 1e-4    # a result smaller than this share of the position counts as break-even


def trend_of(candles: list[dict], n: int = TREND_CANDLES, threshold: float = TREND_ER) -> Optional[str]:
    """up / down / range from the efficiency ratio of the last n closed candles; None: too few candles."""
    if len(candles) < n + 1:
        return None
    closes = [c["close"] for c in candles[-(n + 1):]]
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    move = closes[-1] - closes[0]
    if not path or abs(move) / path < threshold:
        return "range"
    return "up" if move > 0 else "down"


def btc_correlation(coin: list[dict], btc: list[dict], hours: int = BTC_LINK_HOURS) -> Optional[float]:
    """Correlation of the hourly returns of a coin and Bitcoin (same hours), None with too little data."""
    def returns(rows):
        rows = rows[-(hours + 1):]
        return {b["time"]: math.log(b["close"] / a["close"]) for a, b in zip(rows, rows[1:]) if a["close"] > 0 and b["close"] > 0}
    a, b = returns(coin), returns(btc)
    common = [t for t in a if t in b]
    if len(common) < 200:
        return None
    xs, ys = [b[t] for t in common], [a[t] for t in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def trade_outcome(trade: dict) -> str:
    """win / loss / even. A trade closed at the break-even stop (or with a result of practically
    zero, e.g. a billionth of a dollar from rounding) is "even", not a loss."""
    if trade.get("exitReason") in ("breakeven", "timeBe") or abs(trade["pnl"]) < trade["notional"] * EVEN_PART:
        return "even"
    return "win" if trade["pnl"] > 0 else "loss"


def entry_stats(closed: list[dict], limit_stats: dict) -> dict:
    """Market vs limit entries side by side (owner's comparison): trades, won %, average R, fees;
    for limit entries also the share of placed orders that filled. R: the result over the risk at
    the opening (before the owner moved the stop)."""
    out = {}
    for kind in ("market", "limit"):
        trades = [t for t in closed if t.get("entryType", "market") == kind]
        n = len(trades)
        rs = [t["pnl"] / (t.get("openRisk") or t["risk"]) for t in trades if (t.get("openRisk") or t.get("risk"))]
        out[kind] = {"trades": n,
                     "winRate": sum(1 for t in trades if trade_outcome(t) == "win") / n * 100 if n else None,
                     "avgR": sum(rs) / len(rs) if rs else None,
                     "fees": sum(t["fees"] for t in trades)}
    ended = sum(limit_stats.get(k, 0) for k in ("filled", "expired", "cancelled"))
    out["limit"]["orders"] = {k: limit_stats.get(k, 0) for k in ("placed", "filled", "expired", "cancelled")}
    out["limit"]["fillRate"] = limit_stats.get("filled", 0) / ended * 100 if ended else None
    return out


def new_account(capital: float, now: float) -> dict:
    return {
        "version": 1,
        "capital": capital,
        "balance": capital,
        "status": "stopped",          # stopped | running | halted (30% loss)
        "mode": "auto",               # auto: all strategies | manual: the owner's choice
        "strategies": list(BOT_STRATEGIES),
        "positions": [],
        "closed": [],
        "events": [],
        "peakEquity": capital,
        "maxDrawdown": 0.0,
        "day": time.strftime("%Y-%m-%d", time.gmtime(now)),
        "dayStartEquity": capital,
        "lossStreak": 0,
        "profitCap": 0.0,        # owner's option: close a position once it is this many USDT in profit (0 = off)
        "pauseLosses": PAUSE_LOSSES,       # owner's option: pause after this many losses in a row (0 = off)
        "pauseFall": PAUSE_FALL * 100,     # owner's option: pause after this % fall (0 = off)
        "brainThreshold": None,            # owner's option: least chance the brain must give (None = its own)
        "coinMode": "top",                 # owner's option: top (by volume) | volatile (24h) | manual
        "coins": [],                       # the owner's own list for "manual" (ccxt symbols)
        "aiEnabled": False,                # owner's option: Gemini must approve each trade (advisor.py)
        "aiTimeframes": list(advisor.DEFAULT_TIMEFRAMES),
        "pendingAsks": [],                 # signals waiting for the owner because the AI did not answer
        "limitEntry": False,               # owner's option: enter with a limit order (maker fee), not at the market
        "lockEnabled": False,              # owner's option: profit lock (stop moves to lockAt % of the way ...
        "lockTrigger": LOCK_TRIGGER * 100, # ... once the price has gone lockTrigger % of the way to the target)
        "lockAt": LOCK_AT * 100,
        "reviewEnabled": True,             # owner's option: look again at long positions (REVIEW_*)
        "reviewAfter": REVIEW_AFTER_CANDLES,
        "reviewEvery": dict(REVIEW_EVERY),
        "orders": [],                      # limit orders waiting to fill (limitEntry)
        "limitStats": {"placed": 0, "filled": 0, "expired": 0, "cancelled": 0},
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
                 memory: Optional[Memory] = None, brain: Optional[Brain] = None, profile: Profile = MAIN):
        self.store = store
        self.profile = profile
        self.flow: list[tuple[float, str]] = []
        self.scan_seconds: dict[str, float] = {}
        self.postponed: set[str] = set()           # timeframes already put off once for a new 1m candle   # how long the last scan of each timeframe took  # (time, "seen" | "opened" | skip reason) for the counter
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
        loaded = store.load()
        self.account = loaded or new_account(100.0, now())
        if loaded is None:
            self.account["profitCap"] = profile.default_cap
        for k, v in new_account(self.account.get("capital", 100.0), now()).items():
            self.account.setdefault(k, v)  # files from older versions
        # Timeframes added to the bot since the owner's choice was saved start ticked (owner 2026-11-02:
        # trade the slower charts); the ones the owner unticked stay unticked.
        chosen = self.account.get("chosenTimeframes")
        if chosen:
            known = self.account.get("knownTimeframes") or OLD_TIMEFRAMES
            new = [tf for tf in profile.timeframes if tf not in known and tf not in chosen]
            if new:
                self.account["chosenTimeframes"] = [tf for tf in profile.timeframes if tf in chosen or tf in new]
        self.account["knownTimeframes"] = list(profile.timeframes)
        # Strategies taken off the bot's list since the file was saved are dropped from the choice.
        kept = [k for k in self.account.get("strategies") or [] if k in BOT_STRATEGIES]
        self.account["strategies"] = kept if kept and self.account.get("mode") == "manual" else list(BOT_STRATEGIES)
        self.prices: dict[str, float] = {}    # last price per position id (for the screen)
        self.scanning: Optional[str] = None   # timeframe being scanned
        self.lock = asyncio.Lock()
        self._performance: Optional[tuple[float, dict]] = None   # (time, per-strategy results) cache
        self.ai_ask = advisor.ask            # replaced in tests
        self.ai_consult = advisor.consult    # the owner's "stay or exit?" button (replaced in tests)
        self.btc_links: dict[str, tuple[float, Optional[float]]] = {}   # symbol -> (when, correlation with BTC)
        self.btc_state: dict = {}                                       # Bitcoin's 1h / 4h trend for the panel
        self.ai_keys = advisor.load_keys     # keys live in settings.json on this computer
        self.ai_error: Optional[str] = None  # the last reason Gemini did not answer (for the screen)
        self.ask_timers = True               # open an unanswered question after ASK_AUTO_SECONDS (off in tests)
        self.real = None                      # the owner's real account (account.ExchangeAccount), set by the server
        self._real_tasks: set = set()
        self.tg_post = telegram.default_post  # Telegram messages (replaced in tests)
        self.tg_error: Optional[str] = None   # the last reason a Telegram message did not go
        self._tg_tasks: set = set()

    # ---- what the screen sees

    def strategy_performance(self) -> dict:
        """Per-strategy results of the bot, the signals and the brain's filter (reused for a minute)."""
        if self.memory is None:
            return {}
        now = self.now()
        if self._performance is None or now - self._performance[0] >= PERFORMANCE_SECONDS:
            threshold = None
            if self.brain is not None and self.brain.active():
                threshold = self.brain.champion.threshold
            self._performance = (now, self.memory.strategy_performance(threshold))
        return self._performance[1]

    def equity(self) -> float:
        a = self.account
        open_pnl = sum(pnl(p, self.prices.get(p["id"], p["entryPrice"]), self.fees.taker)[0] for p in a["positions"])
        return a["balance"] + open_pnl

    def public(self) -> dict:
        a = self.account
        closed = a["closed"]
        wins = [t for t in closed if trade_outcome(t) == "win"]
        losses = [t for t in closed if trade_outcome(t) == "loss"]
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
            "ai": {"enabled": a.get("aiEnabled", False), "timeframes": a.get("aiTimeframes", []),
                   "model": advisor.load_model(), "keys": advisor.masked(self.ai_keys()), "lastError": self.ai_error,
                   "results": self.memory.ai_summary() if self.memory is not None else {}},
            "pendingAsks": [{"id": q["id"], "symbol": q["c"]["symbol"], "base": q["c"]["base"],
                             "timeframe": q["tf"], "strategy": q["c"]["strategy"], "side": q["c"]["signal"]["side"],
                             "entry": q["c"]["signal"]["entry"], "stopLoss": q["c"]["signal"]["stopLoss"],
                             "takeProfit": q["c"]["signal"]["takeProfit"], "expires": q["expires"],
                             "error": q.get("error")} for q in a.get("pendingAsks", [])],
            "btc": self.btc_state,
            "telegram": {**telegram.public(), "lastError": self.tg_error},
            "limitEntry": a.get("limitEntry", False),
            "focus": {"on": bool(a.get("focus")), "since": (a.get("focus") or {}).get("since"),
                      "timeframes": list(FOCUS_TIMEFRAMES), "stats": self.focus_stats()},
            "review": {"enabled": a.get("reviewEnabled", True), "after": a.get("reviewAfter", REVIEW_AFTER_CANDLES),
                       "every": {**REVIEW_EVERY, **(a.get("reviewEvery") or {})}},
            "orders": [{k: o[k] for k in ("id", "symbol", "base", "timeframe", "strategy", "side", "price",
                                          "placedPrice", "placedAt", "expires", "stopLoss", "takeProfit", "margin")}
                       for o in a.get("orders", [])],
            "entryStats": entry_stats(closed, a.get("limitStats") or {}),
            "mode": a["mode"],
            "strategies": a["strategies"],
            "positions": positions,
            "closed": list(reversed(closed)),     # the whole kept history (up to KEEP_CLOSED)
            "events": list(reversed(a["events"][-20:])),
            "stats": {
                "trades": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "evens": len(closed) - len(wins) - len(losses),
                # break-even trades are neither won nor lost (owner 2026-11-09)
                "winRate": len(wins) / (len(wins) + len(losses)) * 100 if wins or losses else None,
                "netPnl": equity - a["capital"],
                "netPercent": (equity - a["capital"]) / a["capital"] * 100 if a["capital"] else 0,
                "todayPnl": equity - a["dayStartEquity"],
                "fees": sum(t["fees"] for t in closed),
                "maxDrawdown": a["maxDrawdown"] * 100,
            },
            "scanning": self.scanning,
            "strategyStats": self.strategy_performance(),
            # The bot's list: which strategies it trades on which timeframe (empty: that timeframe is not traded).
            "botStrategies": {tf: list(k) for tf, k in BOT_STRATEGIES_BY_TF.items()},
            "lastScan": a["lastScan"],
            "timeframes": list(self.profile.timeframes),
            "chosenTimeframes": self.chosen_timeframes(),
            "profile": self.profile.name,
            "flow": self.flow_summary(),
            "scanSeconds": self.scan_seconds,
            "rules": {"risk": RISK * 100,
                      "maxOpen": self.max_open(), "timeBeCandles": TIME_BE_CANDLES, "staleTolerance": STALE_PART * 100,
                      "maxSameSide": None if self.profile.max_same_side >= UNLIMITED else self.profile.max_same_side,
                      "brainThreshold": a.get("brainThreshold"),
                      "coinMode": a.get("coinMode", "top"), "coins": a.get("coins", []),
                      "volatileCoins": config.VOLATILE_COINS,
                      "maxLeverage": MAX_LEVERAGE, "smartPause": self.profile.smart_pause,
                      "allSignals": self.profile.all_signals,
                      **({"strictTrades": STRICT_TRADES, "strictProfitFactor": STRICT_PROFIT_FACTOR}
                         if STRICT_TIMEFRAMES else {}),
                      "pauseLosses": a.get("pauseLosses", PAUSE_LOSSES), "pauseFall": a.get("pauseFall", PAUSE_FALL * 100),
                      "pauseHours": PAUSE_SECONDS / 3600, "recoverWins": RECOVER_WINS, "profitCap": self.account.get("profitCap", 0.0), "totalStop": TOTAL_STOP * 100,
                      "limitOffset": LIMIT_OFFSET * 100, "limitExpireCandles": LIMIT_EXPIRE_CANDLES,
                      "lock": {"enabled": a.get("lockEnabled", False), "trigger": a.get("lockTrigger", LOCK_TRIGGER * 100),
                               "at": a.get("lockAt", LOCK_AT * 100)},
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
            self._cancel_orders("limit_cancelled", "botStop")   # a stopped bot opens nothing
            self._event("stop")
            self.save()

    def reset(self, capital: float) -> None:
        # Settings, not results: kept (owner 2026-11-03: the manual strategy choice was lost here).
        self._cancel_orders("limit_cancelled", "reset")
        kept = {k: self.account[k] for k in ("profitCap", "pauseLosses", "pauseFall", "brainThreshold",
                                              "mode", "strategies", "coinMode", "coins", "aiEnabled", "aiTimeframes",
                                              "limitEntry", "lockEnabled", "lockTrigger", "lockAt", "maxOpen",
                                              "reviewEnabled", "reviewAfter", "reviewEvery", "focus")
                if k in self.account}
        chosen = self.account.get("chosenTimeframes")
        self.account = new_account(capital, self.now())
        self.account.update(kept)   # settings, not results: kept
        if chosen:
            self.account["chosenTimeframes"] = chosen
        self.prices.clear()
        self._event("reset", capital=capital)
        self.save()

    def chosen_timeframes(self) -> list[str]:
        """The timeframes the owner ticked for trading (all of the account's by default)."""
        chosen = [tf for tf in self.account.get("chosenTimeframes") or [] if tf in self.profile.timeframes]
        return chosen or list(self.profile.timeframes)

    def set_timeframes(self, timeframes: list[str]) -> None:
        self.account["chosenTimeframes"] = [tf for tf in self.profile.timeframes if tf in timeframes]
        self.save()

    def set_profit_cap(self, usd: float) -> None:
        self.account["profitCap"] = max(0.0, float(usd))
        self.save()

    def set_coins(self, mode: str, coins: list[str]) -> None:
        """Owner's choice of coins: top / volatile / manual (with the list)."""
        self.account["coinMode"] = mode
        if mode == "manual":
            self.account["coins"] = list(dict.fromkeys(coins))
        self.save()

    def set_brain_threshold(self, threshold: Optional[float]) -> None:
        """Owner's knob: the least chance a signal needs (0 = brain off), or None for the brain's own."""
        self.account["brainThreshold"] = None if threshold is None else min(MAX_BRAIN_THRESHOLD, max(0.0, float(threshold)))
        self.save()

    def set_pause_rules(self, losses: int, fall: float) -> None:
        """Owner's option: pause after this many losses in a row / this % fall (0 turns a rule off)."""
        self.account["pauseLosses"] = min(MAX_PAUSE_LOSSES, max(0, int(losses)))
        self.account["pauseFall"] = min(MAX_PAUSE_FALL, max(0.0, float(fall)))
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

    def set_lock_point(self, position_id: int, price: float) -> Optional[str]:
        """The owner drags the profit-lock point of one position (2026-11-07). Only this position changes;
        the stop-after-lock moves with it at the same ratio as the panel's setting (80 -> 40: half the way).
        Errors: missing, lock_off (profit lock is switched off), lock_done (it already moved the stop),
        lock_side (the point must be between the entry and the target)."""
        p = next((x for x in self.account["positions"] if x["id"] == position_id), None)
        if p is None:
            return "missing"
        a = self.account
        if not a.get("lockEnabled"):
            return "lock_off"
        if p.get("lockedAt"):
            return "lock_done"
        way = p["takeProfit"] - p["entryPrice"]
        share = (price - p["entryPrice"]) / way if way else 0
        if not 0.05 <= share <= 0.99:
            return "lock_side"
        ratio = a.get("lockAt", LOCK_AT * 100) / a.get("lockTrigger", LOCK_TRIGGER * 100)
        p["lockOwn"] = {"trigger": share, "at": share * ratio}
        p["lock"] = dict(p["lockOwn"])
        p["edited"] = True
        self._event("levels", symbol=p["base"], timeframe=p["timeframe"], what="lock",
                    old=None, new=price)
        self.save()
        return None

    def set_levels(self, position_id: int, stop: Optional[float] = None,
                   target: Optional[float] = None) -> Optional[str]:
        """Owner drags the stop-loss or the take-profit line of an open position on the chart.

        Takes effect at once. Returns None when done, else why not:
        missing (no such open position), stop_side (the stop must stay on the losing side of the
        price now), stop_liquidation (the stop must come before the liquidation price),
        target_side (the target must stay on the winning side of the price now).
        The size stays, so the risk at the stop is counted again. Break-even is counted again too:
        its trigger follows the new target; it only ever moves the stop toward profit; a stop the
        owner moved away from the break-even price is the owner's stop again (break-even re-arms)."""
        p = next((p for p in self.account["positions"] if p["id"] == position_id), None)
        if p is None:
            return "missing"
        long_ = p["side"] == LONG
        price = self.prices.get(p["id"], p["entryPrice"])
        if stop is not None:
            if not ((stop < price) if long_ else (stop > price)):
                return "stop_side"
            if not ((stop > p["liquidation"]) if long_ else (stop < p["liquidation"])):
                return "stop_liquidation"
        if target is not None and not ((target > price) if long_ else (target < price)):
            return "target_side"
        changes = []
        if stop is not None and stop != p["stop"]:
            changes.append(("stop", p["stop"], stop))
            p["stop"] = stop
            if p.get("breakevenAt") and stop != p["breakevenPrice"]:
                p["breakevenAt"] = None   # the owner's stop now; break-even may move it again later
            p["lockedAt"] = None          # the profit lock too (it only ever moves the stop toward profit)
            p["risk"] = p["notional"] * (abs(p["entryPrice"] - stop) / p["entryPrice"] + 2 * self.fees.taker / 100)
        if target is not None and target != p["takeProfit"]:
            changes.append(("target", p["takeProfit"], target))
            p["takeProfit"] = target
            if stop is None:
                # Only the target moved: if the price already passed the new break-even trigger, move now.
                _maybe_breakeven(p, price, int(self.now()))
        if not changes:
            return None
        p["edited"] = True
        for what, old, new in changes:
            self._event("levels", symbol=p["base"], timeframe=p["timeframe"], what=what, old=old, new=new)
            p.setdefault("edits", []).append({"time": self.now(), "what": what, "old": old, "new": new})
        self.save()
        self.mirror("levels", p)
        return None

    async def close_all_and_stop(self) -> int:
        """Owner's button: close every open position now and switch the bot off."""
        ids = [p["id"] for p in self.account["positions"]]
        for i in ids:
            await self.close_position(i)
        self.stop()
        return len(ids)

    def set_mode(self, mode: str, strategies: list[str]) -> None:
        self.account["mode"] = mode
        chosen = [k for k in strategies if k in BOT_STRATEGIES]
        self.account["strategies"] = list(BOT_STRATEGIES) if mode == "auto" or not chosen else chosen
        self.save()

    # ---- the loop

    async def run_forever(self) -> None:
        while True:
            try:
                if self.account["status"] == "running":
                    await self.step()
                elif self.memory is not None:
                    await self.learn_only()
                self._maybe_learn()
                self._maybe_pretrain()
            except asyncio.CancelledError:
                if _really_cancelled():
                    raise   # the app is closing
                # A cancel that did not come from the app: e.g. the exchange connection was closed
                # while a request was waiting (changing the proxy does that). Before, this ended
                # the loop silently: the bot showed "running" but never scanned again.
                logging.getLogger("trading_bot").warning("bot round interrupted", exc_info=True)
                self._event("error", message="round interrupted (connection was reset)")
            except Exception as error:  # never let one bad answer stop the bot
                logging.getLogger("trading_bot").warning("bot round failed", exc_info=True)
                self._event("error", message=str(error)[:200])
            await asyncio.sleep(POLL_SECONDS)

    def _maybe_pretrain(self) -> None:
        """Once a day: rebuild past signals of every chart from its history, in the background."""
        if self.memory is None or self.brain is None:
            return
        if self.pretraining is not None and not self.pretraining.done():
            return
        last = self.account.get("pretrainedAt")
        if pretrain.due(last, self.now()):
            self.pretraining = asyncio.create_task(self._pretrain_safely())

    async def _pretrain_safely(self) -> int:
        """pretrain_round in the background: a failure is logged, never left unread."""
        try:
            return await self.pretrain_round()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # e.g. the exchange unreachable; tried again next round
            logging.getLogger("trading_bot").warning("pretrain round failed: %s", error)
            return 0

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
                settings = bot_settings(tf)
                for symbol, base in coins:
                    now = self.now()
                    chart_tf = f"{tf}#{STRATEGY_SET}"   # new strategies: every chart is rebuilt once
                    if pretrain.due(memory.pretrain_time(symbol, chart_tf), now):
                        try:
                            rows = closed_only(await self.history(symbol, tf), tf, now)
                            found = await asyncio.to_thread(pretrain.history_signals, symbol, base, tf, rows,
                                                            settings, mode, self.fees)
                            added += await asyncio.to_thread(memory.record_history, tf, found, now)
                            memory.set_pretrain_time(symbol, chart_tf, now)
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
            account = self.account
            now = self.now()
            self._new_day(now)
            await self._auto_open_asks(now)
            if now - self.btc_state.get("time", 0) >= 300:
                await self._btc_view(now)
            await self._watch_orders(now)
            await self._watch_positions(now)
            equity = self.equity()
            self._track_drawdown(equity)
            if equity <= self.account["capital"] * (1 - TOTAL_STOP):
                self._cancel_orders("limit_cancelled", "halted")
                self.account["status"] = "halted"
                self._event("halted", equity=equity)
                self.save()
                return
            if self.profile.smart_pause:
                self._update_pause(now, equity)
            before = {k: dict(v) for k, v in self.account["lastScan"].items()}
            due = self._trading_order(self._due_timeframes(now))
            # Only the ticked timeframes are scanned while trading: scanning all five took minutes
            # (on a phone much longer), so 1m / 5m signals came late or not at all. The others still
            # learn every day from the pre-training.
            chosen = self.chosen_timeframes()
            due = [tf for tf in due if tf in chosen]
            self.save()
        # One timeframe at a time, each under the lock on its own: the buttons (stop, start again,
        # close) wait for one chart scan at most, not for a whole round of five timeframes.
        for i, tf in enumerate(due):
            async with self.lock:
                if self.account is not account or account["status"] != "running":
                    return   # started again or stopped meanwhile
                now = self.now()
                fastest = min(due, key=lambda x: config.TIMEFRAME_SECONDS[x])
                waited = [x for x in due[i:] if x in self.postponed]
                if i and tf != fastest and not waited and self._new_period(fastest, now):
                    # A new candle of the fastest ticked timeframe closed meanwhile: it goes first.
                    # The rest of this round waits for the next loop (not lost), but only once: when
                    # one scan takes longer than a 1m candle (slow computer or phone), waiting every
                    # time would starve the slower timeframes (owner saw only 1m / 3m signals).
                    self.postponed.update(due[i:])
                    for later in due[i:]:
                        if later in before:
                            self.account["lastScan"][later] = before[later]
                        else:
                            self.account["lastScan"].pop(later, None)
                    return
                started = time.time()
                self.postponed.discard(tf)
                # Scanned even when there is no free place or the owner did not tick this timeframe:
                # the memory still learns from the signals. Trades only on the ticked timeframes.
                trade = (not self._paused(now) and tf in self.chosen_timeframes()
                         and free_slots(self.account["positions"], tf, self.profile.slots) > 0)
                await self._scan_and_open(tf, now, trade=trade)
                self.scan_seconds[tf] = round(time.time() - started, 1)
                self.save()

    def _new_period(self, tf: str, now: float) -> bool:
        period = int((now - SCAN_DELAY) // config.TIMEFRAME_SECONDS[tf])
        return self.account["lastScan"].get(tf, {}).get("period") != period

    def _trading_order(self, due: list[str]) -> list[str]:
        """The ticked timeframes first, fastest first (a 1-minute signal goes stale soonest), then the rest."""
        chosen = self.chosen_timeframes()
        return sorted(due, key=lambda tf: (tf not in chosen, config.TIMEFRAME_SECONDS[tf]))

    def _count(self, kind: str, n: int = 1) -> None:
        now = self.now()
        self.flow.extend([(now, kind)] * n)
        self.flow = [f for f in self.flow if f[0] >= now - FLOW_SECONDS]

    def flow_summary(self) -> dict:
        now = self.now()
        recent = [k for t, k in self.flow if t >= now - FLOW_SECONDS]
        skipped: dict[str, int] = {}
        for k in recent:
            if k not in ("seen", "opened", "limitPlaced"):
                skipped[k] = skipped.get(k, 0) + 1
        return {"minutes": FLOW_SECONDS // 60, "seen": recent.count("seen"), "opened": recent.count("opened"),
                "placed": recent.count("limitPlaced"), "skipped": skipped}

    async def learn_only(self) -> None:
        """Bot switched off: keep scanning so the memory keeps learning, open nothing."""
        async with self.lock:
            account = self.account
            due = self._due_timeframes(self.now())
            self.save()
        for i, tf in enumerate(due):
            async with self.lock:
                # Switched on (or started again) meanwhile: leave the rest of this learning round,
                # so the next round trades right away instead of after a 5-minute learning round.
                if self.account is not account or account["status"] == "running":
                    for rest in due[i:]:   # not scanned: due again for the trading round
                        account["lastScan"].pop(rest, None)
                    return
                await self._scan_and_open(tf, self.now(), trade=False)
                self.save()

    def _due_timeframes(self, now: float) -> list[str]:
        due = []
        for tf in [t for t in SCAN_ORDER if t in self.profile.timeframes]:
            if not BOT_STRATEGIES_BY_TF.get(tf, True):
                continue   # no strategy of the bot's list on this timeframe: nothing to scan
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
        losses = int(a.get("pauseLosses", PAUSE_LOSSES) or 0)
        fall = float(a.get("pauseFall", PAUSE_FALL * 100) or 0) / 100
        if losses and a["lossStreak"] >= losses:
            reason = "streak"
        elif fall and equity <= a["pauseBase"] * (1 - fall):
            reason = "fall"
        if reason is None:
            return
        a["pausedUntil"] = now + PAUSE_SECONDS
        a["pausedAt"] = now
        a["pauseReason"] = reason
        benched = []
        if self.memory is not None:
            counts = self.memory.strategy_counts(now - BENCH_LOOKBACK)
            for kind, result in self.memory.strategy_results(now - BENCH_LOOKBACK).items():
                if result < 0 and counts.get(kind, 0) >= BENCH_MIN_RESULTS:
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
            levels = (p["stop"], p["takeProfit"])
            try:
                await self._watch_one(p, now)
                if p in self.account["positions"] and (p["stop"], p["takeProfit"]) != levels:
                    self.mirror("levels", p)   # lock / break-even moved the stop: on the exchange too
            except asyncio.CancelledError:
                raise
            except Exception as error:   # e.g. a timeout for this coin: the other positions are still checked
                logging.getLogger("trading_bot").warning("checking %s failed: %r", p.get("base"), error)

    async def _watch_one(self, p: dict, now: float) -> None:
        a = self.account
        if a.get("lockEnabled"):   # the owner's profit lock, for open positions too (or this position's own)
            p["lock"] = dict(p["lockOwn"]) if p.get("lockOwn") else \
                {"trigger": a.get("lockTrigger", LOCK_TRIGGER * 100) / 100, "at": a.get("lockAt", LOCK_AT * 100) / 100}
        else:
            p.pop("lock", None)
        tf_seconds = config.TIMEFRAME_SECONDS[p["timeframe"]]
        since = max(p["checkedFrom"], p["entryCandle"] + tf_seconds)
        candles, hole_before = await self._candles_since(p, p["symbol"], p["timeframe"], since)
        if not candles:
            return
        last = candles[-1]["close"]
        self.prices[p["id"]] = last
        # The forming candle is read minute by minute (stop fills at the stop, as on the exchange); only
        # if the minutes cannot be had, the price seen now is used as before.
        minutes = None
        if hole_before is None:
            try:
                minutes = await self.recent(p["symbol"], "1m")
            except Exception:
                minutes = None
        hit = check_exit(p, candles, None if minutes else last, tf_seconds, now, hole_before)
        if hit is None and minutes:
            hit = check_minutes(p, minutes, now)
        cap = self.account.get("profitCap") or 0
        if hit is None and cap > 0 and pnl(p, last, self.fees.taker)[0] >= cap:
            hit = (last, "cap")   # owner's profit cap: take the small profit now
        if hit:
            self._close(p, hit[0], hit[1], now)
            return
        ask = p.get("timeBeAsk")
        if ask and not ask["sent"]:
            ask["sent"] = True
            result = pnl(p, last, self.fees.taker)[0]
            self._event("timeBeAsk", symbol=p["base"], timeframe=p["timeframe"], pnl=result)
            self.notify(f"⏱ {p['base']} {p['timeframe']} {telegram.side_word(p)}: "
                        f"{TIME_BE_CANDLES.get(p['timeframe'])} کندل گذشته و به هدف نرسیده (الان {telegram._money(result)}).\n"
                        + ("در سود است: حد ضرر به سربه‌سر برود؟" if result > 0 else
                           "در ضرر است: وقتی قیمت به ورود برگشت، سربه‌سر بسته شود؟")
                        + "\nبی‌جواب: هیچ تغییری داده نمی‌شود.",
                        buttons=[("⚖️ سربه‌سر کن", f"tbe:{p['id']}"), ("ادامه بده", f"tgo:{p['id']}")])
        if self._review_due(p, now):
            await self._review(p, last, now)
        elif self.profile.advice and p.get("advice") is None and self._half_way(p, last):
            await self._advise(p, now)

    # ---- the timed look at long positions (owner 2026-11-09)

    def _review_due(self, p: dict, now: float) -> bool:
        a = self.account
        if not a.get("reviewEnabled", True):
            return False
        tf = p["timeframe"]
        after = (a.get("reviewAfter") or REVIEW_AFTER_CANDLES) * config.TIMEFRAME_SECONDS[tf]
        every = ({**REVIEW_EVERY, **(a.get("reviewEvery") or {})}.get(tf) or 15) * 60
        last = (p.get("review") or {}).get("time")
        return now - p["entryTime"] >= after and (last is None or now - last >= every)

    async def _review(self, p: dict, price: float, now: float) -> None:
        """The trend turned against the position? First the bot's own rule (the higher timeframe's trend, or
        this chart trending the other way); only then Gemini is asked (if there are keys) to confirm.
        Then: in profit -> closed now; in a loss -> the owner decides on Telegram (close / go on)."""
        long_ = p["side"] == LONG
        higher = await self._trend(p["symbol"], p["timeframe"], now)
        _, _, _, state = await self._bot_opinion(p, now)
        against = (higher == "down" if long_ else higher == "up") or \
                  (state == "trend_down" if long_ else state == "trend_up")
        review = {"time": now, "price": price, "higher": higher, "state": state, "against": against,
                  "ai": None, "decision": "hold"}
        p["review"] = review
        view = "against" if against else "with"
        changed = p.get("reviewView") != view
        p["reviewView"] = view
        if not against:
            if changed:   # owner 2026-11-10: asked once when it gets long, again only when the view changes
                await self._ask_stay(p, price, now, higher, state)
            return
        if self.ai_keys():
            answer = await self.consult(p["id"])
            action = ((answer or {}).get("ai") or {}).get("action")
            review["ai"] = action
            if action is not None and action != "exit":
                return   # the AI sees no reason to leave: the position goes on
        if p not in self.account["positions"]:
            return
        result = pnl(p, price, self.fees.taker)[0]
        why = self._review_words(higher, state)
        if result > 0:
            review["decision"] = "close"
            self._close(p, price, "review", now)
            return
        review["decision"] = "ask"
        p["reviewAsk"] = {"time": now, "price": price, "answer": None}
        self._event("reviewAsk", symbol=p["base"], timeframe=p["timeframe"], pnl=result)
        self.notify(telegram.closing_text(p, why, price) + f"\nدر ضرر است ({result:+.2f}$): ببندم یا ادامه بدهم؟",
                    buttons=[("ببند", f"close:{p['id']}"), ("ادامه", f"hold:{p['id']}")])

    async def _ask_stay(self, p: dict, price: float, now: float, higher: Optional[str], state: Optional[str]) -> None:
        """The position got long (or the bot's view changed): stay or close? With the bot's and Gemini's view."""
        result = pnl(p, price, self.fees.taker)[0]
        risk = p.get("openRisk") or p["risk"]
        words = {"up": "صعودی", "down": "نزولی", "range": "رنج"}
        lines = [f"⏳ پوزیشن طولانی شد: {p['base']} {p['timeframe']} {telegram.side_word(p)}",
                 f"الان {telegram._money(result)}" + (f" ({result / risk:+.2f}R)" if risk else "") + f" · قیمت {price:.6g}",
                 f"نظر ربات: روند تایم‌فریم بالاتر {words.get(higher, 'نامعلوم')}، حالت بازار {state or 'نامعلوم'}"
                 f" — {'هم‌جهت با پوزیشن، ماندن' if p.get('reviewView') == 'with' else 'برخلاف پوزیشن'}"]
        if self.ai_keys():
            answer = await self.consult(p["id"])
            ai = (answer or {}).get("ai") or {}
            if ai.get("action"):
                act = {"hold": "بماند", "exit": "خارج شود", "move_stop": "حد ضرر جابه‌جا شود"}.get(ai["action"], ai["action"])
                lines.append(f"نظر Gemini: {act}" + (f" — {ai['reason'][:200]}" if ai.get("reason") else ""))
        if p not in self.account["positions"]:
            return
        p["reviewAsk"] = {"time": now, "price": price, "answer": None}
        self._event("reviewAsk", symbol=p["base"], timeframe=p["timeframe"], pnl=result)
        self.notify("\n".join(lines) + "\nبمانم یا ببندم؟ (بی‌جواب: می‌ماند)",
                    buttons=[("بمان", f"hold:{p['id']}"), ("ببند", f"close:{p['id']}")])

    @staticmethod
    def _review_words(higher: Optional[str], state: Optional[str]) -> str:
        if higher in ("up", "down"):
            return f"روند تایم‌فریم بالاتر {'صعودی' if higher == 'up' else 'نزولی'} شد"
        return f"حالت بازار: {state}"

    async def telegram_forever(self) -> None:
        """Reads the owner's Telegram messages every few seconds while the app is open, also while the bot
        is stopped: the fixed buttons (status, open positions) and the close / go-on taps."""
        while True:
            try:
                await self._telegram_answers(self.now())
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger("trading_bot").warning("telegram round failed", exc_info=True)
            await asyncio.sleep(TELEGRAM_POLL_SECONDS)

    def _telegram_status(self) -> dict:
        a = self.account
        equity = self.equity()
        return {"status": a["status"], "pauseReason": a.get("pauseReason"), "equity": equity, "capital": a["capital"],
                "today": equity - (a.get("dayStartEquity") or equity), "open": len(a["positions"]),
                "orders": len(a.get("orders") or []), "btc": self.btc_state, "lock": a.get("lockEnabled", False),
                "review": a.get("reviewEnabled", True)}

    def _telegram_positions(self) -> list[dict]:
        rows = []
        for p in self.account["positions"]:
            price = self.prices.get(p["id"])
            rows.append({**p, "price": price, "pnl": pnl(p, price, self.fees.taker)[0] if price is not None else None,
                         "risk": p.get("openRisk") or p["risk"]})
        return rows

    async def _telegram_answers(self, now: float) -> None:
        """The owner's messages on Telegram: the two fixed buttons, and close / go on for a position asked
        about in a loss."""
        settings = telegram.load()
        if not (settings["enabled"] and settings["token"] and settings["chatId"] is not None):
            return
        try:
            answers = await telegram.answers(settings, self.tg_post)
        except telegram.TelegramError as error:
            self.tg_error = str(error)
            return
        changed = False
        for a in answers:
            if a["kind"] == "real":
                if a["action"] in ("rok", "rno") and self.real is not None:
                    still = any(x["id"] == a["id"] for x in self.account["positions"])
                    text = await self.real.answer(a["id"], a["action"] == "rok", still)
                elif a["action"] == "panic" and self.real is not None:
                    text = await self.real.panic()
                else:
                    text = "حساب واقعی وصل نیست."
                await self._tg_reply(settings, a["query"], text[:180])
                continue
            if a["kind"] == "manage":
                await self._tg_manage(settings, a, now)
                continue
            if a["kind"] == "number" or (a["kind"] == "ask" and a["what"] == "cancel"):
                await self._tg_price(settings, a, now)
                continue
            if a["kind"] == "ask" and a["what"] == "positions":
                rows = self._telegram_positions()
                try:
                    await telegram.send(telegram.positions_text(rows, now), self.tg_post, settings,
                                        buttons=telegram.position_buttons(rows) or None)
                except telegram.TelegramError as error:
                    self.tg_error = str(error)
                continue
            if a["kind"] == "ask" and a["what"] == "closeall":
                try:
                    await telegram.send("🛑 همه‌ی پوزیشن‌های واقعی بسته شوند و ربات واقعی متوقف شود؟",
                                        self.tg_post, settings, buttons=[("بله، همه را ببند", "panic:0")])
                except telegram.TelegramError as error:
                    self.tg_error = str(error)
                continue
            if a["kind"] == "ask":
                text = (telegram.status_text(self._telegram_status()) + (
                    f"\n{self.real.summary_line()}" if self.real is not None and self.real.summary_line() else "")) \
                    if a["what"] == "status" else \
                    telegram.positions_text(self._telegram_positions(), now) if a["what"] == "positions" else \
                    "با دو دکمه‌ی پایین، وضعیت ربات و پوزیشن‌های باز را بپرس."
                try:
                    await telegram.send_menu(text, settings, self.tg_post)
                except telegram.TelegramError as error:
                    self.tg_error = str(error)
                continue
            action, position_id, query_id = a["action"], a["id"], a["query"]
            changed = True
            p = next((x for x in self.account["positions"] if x["id"] == position_id), None)
            if p is None:
                await self._tg_reply(settings, query_id, "این پوزیشن دیگر باز نیست.")
                continue
            if action == "close":
                price = self.prices.get(p["id"], p["entryPrice"])
                self._close(p, price, "review", now)
                await self._tg_reply(settings, query_id, "بسته شد.")
            else:
                if p.get("reviewAsk"):
                    p["reviewAsk"]["answer"] = "hold"
                await self._tg_reply(settings, query_id, "ادامه می‌دهد.")
            self._event("reviewAnswer", symbol=p["base"], timeframe=p["timeframe"], answer=action)
        if changed:
            self.save()

    async def _tg_say(self, settings: dict, text: str, buttons: Optional[list] = None) -> None:
        try:
            await telegram.send(text, self.tg_post, settings, buttons=buttons)
        except telegram.TelegramError as error:
            self.tg_error = str(error)

    LEVEL_WORDS = {"missing": "این پوزیشن دیگر باز نیست.",
                   "stop_side": "حد ضرر باید سمت ضرر قیمت فعلی باشد (لانگ: پایین‌تر، شورت: بالاتر).",
                   "stop_liquidation": "حد ضرر باید قبل از قیمت لیکوئید باشد.",
                   "target_side": "حد سود باید سمت سود قیمت فعلی باشد (لانگ: بالاتر، شورت: پایین‌تر)."}

    async def _tg_manage(self, settings: dict, a: dict, now: float) -> None:
        """One open position from Telegram: show it, new stop / target (the price comes as the next
        message), break-even, close (asked again first)."""
        action, pid = a["action"], a["id"]
        p = next((x for x in self.account["positions"] if x["id"] == pid), None)
        await self._tg_reply(settings, a["query"], "")
        if p is None:
            await self._tg_say(settings, "این پوزیشن دیگر باز نیست.")
            return
        rows = {x["id"]: x for x in self._telegram_positions()}
        if action in ("tbe", "tgo"):
            ask = p.get("timeBeAsk") or {}
            ask["answer"] = action
            if action == "tgo":
                await self._tg_say(settings, f"{p['base']}: بدون تغییر ادامه می‌دهد.")
            else:
                price = rows[pid].get("price") or p["entryPrice"]
                done = time_be_answer(p, price, int(now))
                self.save()
                self.mirror("levels", p)
                await self._tg_say(settings, {"stop": f"✅ حد ضرر {p['base']} به سربه‌سر ({p['breakevenPrice']:.6g}) رفت.",
                                              "exit": f"✅ {p['base']}: وقتی قیمت به ورود برگشت، سربه‌سر بسته می‌شود.",
                                              "none": f"{p['base']}: حد ضرر از سربه‌سر هم بهتر است؛ تغییری لازم نبود."}[done])
            return
        if action == "pos":
            await self._tg_say(settings, telegram.positions_text([rows[pid]], now), telegram.manage_buttons(p))
        elif action in ("est", "etp"):
            what = "stop" if action == "est" else "target"
            self._tg_wait = {"what": what, "id": pid, "time": now}
            current = p["stop"] if what == "stop" else p["takeProfit"]
            await self._tg_say(settings, f"قیمت جدید {'حد ضرر' if what == 'stop' else 'حد سود'} {p['base']} "
                                         f"{p['timeframe']} را بفرستید (الان {current:.6g}، قیمت {rows[pid].get('price')}).\n"
                                         "برای لغو: /cancel")
        elif action == "pbe":
            price = rows[pid].get("price")
            be = p["breakevenPrice"]
            long_ = p["side"] == LONG
            if price is None or ((price <= be) if long_ else (price >= be)):
                await self._tg_say(settings, "پوزیشن در سود نیست؛ حد ضرر به سربه‌سر نمی‌رود.")
                return
            error = self.set_levels(pid, stop=be)
            await self._tg_say(settings, self.LEVEL_WORDS.get(error, error) if error else
                               f"✅ حد ضرر {p['base']} به سربه‌سر ({be:.6g}) رفت.")
        elif action == "pcl":
            await self._tg_say(settings, f"پوزیشن {p['base']} {p['timeframe']} {telegram.side_word(p)} همین الان بسته شود؟",
                               [("بله، ببند", f"pcy:{pid}")])
        elif action == "pcy":
            done = await self.close_position(pid)
            closed = next((t for t in reversed(self.account["closed"]) if t["id"] == pid), None)
            await self._tg_say(settings, "این پوزیشن دیگر باز نیست." if not done else
                               f"❌ بسته شد: {p['base']} {p['timeframe']} · "
                               f"{telegram._money(closed['pnl']) if closed else ''}")

    async def _tg_price(self, settings: dict, a: dict, now: float) -> None:
        """The price the owner sent after «✏️ حد ضرر / حد سود» (or /cancel)."""
        wait = getattr(self, "_tg_wait", None)
        self._tg_wait = None
        if a["kind"] == "ask":
            await self._tg_say(settings, "لغو شد." if wait else "چیزی در انتظار نبود.")
            return
        if not wait or now - wait["time"] > TELEGRAM_EDIT_SECONDS:
            await self._tg_say(settings, "اول در پیام پوزیشن «✏️ حد ضرر» یا «✏️ حد سود» را بزنید.")
            return
        value = a["value"]
        error = self.set_levels(wait["id"], stop=value) if wait["what"] == "stop" else \
            self.set_levels(wait["id"], target=value)
        if error:
            self._tg_wait = {**wait, "time": now}   # try another price
            await self._tg_say(settings, f"⚠️ {self.LEVEL_WORDS.get(error, error)} عدد دیگری بفرستید یا /cancel.")
            return
        p = next((x for x in self.account["positions"] if x["id"] == wait["id"]), None)
        await self._tg_say(settings, f"✅ {'حد ضرر' if wait['what'] == 'stop' else 'حد سود'} "
                                     f"{p['base'] if p else ''} شد {value:.6g}.", telegram.manage_buttons(p) if p else None)

    async def _tg_reply(self, settings: dict, query_id: str, text: str) -> None:
        try:
            await telegram.reply(settings, query_id, text, self.tg_post)
        except telegram.TelegramError:
            pass

    async def _candles_since(self, item: dict, symbol: str, tf: str, since: int) -> tuple[list[dict], Optional[int]]:
        """The candles from `since` on. Normally the last 60 are enough; after the bot was not watching
        (computer asleep, app closed, no connection) the missing ones come from the long history, so a
        stop or target is found at the candle where it really happened, as on an exchange.
        Returns the candles and, if some could not be had, the time of the first candle after the hole."""
        recent = await self.recent(symbol, tf)
        if not recent or recent[0]["time"] <= since:
            return recent, None
        try:
            older = [c for c in await self.history(symbol, tf) if since <= c["time"] < recent[0]["time"]]
        except Exception:
            older = []
        candles = older + recent
        filled = bool(older) and older[0]["time"] <= since
        if item.get("blindFrom") != since:   # one diary line per hole
            item["blindFrom"] = since
            self._event("blind", symbol=item["base"], timeframe=tf, start=since, end=recent[0]["time"], filled=filled)
        return candles, (None if filled else candles[0]["time"])

    @staticmethod
    def _half_way(p: dict, price: float) -> bool:
        trigger = p["entryPrice"] + (p["takeProfit"] - p["entryPrice"]) * ADVICE_PART
        return price >= trigger if p["side"] == LONG else price <= trigger

    async def _advise(self, p: dict, now: float) -> None:
        """Half way to the target: look at the chart again and advise the owner to hold or to close.
        close: another strategy now gives a reliable signal the other way, or the market state no
        longer suits the strategy (or turned against the trade). The owner answers with a button;
        without an answer the position simply goes on."""
        suggest, reason, detail, _ = await self._bot_opinion(p, now)
        open_pnl = pnl(p, self.prices.get(p["id"], p["entryPrice"]), self.fees.taker)[0]
        p["advice"] = {"time": now, "suggest": suggest, "reason": reason, "detail": detail, "pnl": open_pnl,
                       "answer": None}
        self._event("advice", symbol=p["base"], timeframe=p["timeframe"], reason=reason, suggest=suggest, detail=detail)

    async def _bot_opinion(self, p: dict, now: float) -> tuple[str, str, str, Optional[str]]:
        """The bot's own view of an open position: "close" when another strategy now gives a reliable signal
        the other way (opposite, detail: that strategy) or the market state no longer suits the strategy or
        turned against the trade (state); else "hold". Also returns the market state."""
        tf = p["timeframe"]
        suggest, reason, detail, state = "hold", "fine", "", None
        try:
            rows = await self.history(p["symbol"], tf)
            overview = await asyncio.to_thread(strategy_overview, rows, tf, bot_settings(tf), None, MODE_OF[tf],
                                               now=now, fees=self.fees)
            state = overview["marketState"]
            for row in overview["rows"]:
                sig = row.get("signal")
                e = {"strategy": row["strategy"], "marketState": state, "stats": row["stats"]}
                if sig and sig["side"] != p["side"] and reliable(e):
                    suggest, reason, detail = "close", "opposite", row["strategy"]
                    break
            if suggest == "hold":
                suited = STRATEGIES[p["strategy"]].states
                against = (state == "trend_up" and p["side"] != LONG) or (state == "trend_down" and p["side"] == LONG)
                if state not in suited or against:
                    suggest, reason, detail = "close", "state", state
        except Exception:
            suggest, reason = "hold", "unknown"
        return suggest, reason, detail, state

    # ---- the owner's "stay or exit?" button (2026-11-06)

    async def consult(self, position_id: int) -> Optional[dict]:
        """For one open position: the bot's own view (at once) and Gemini's advice: hold, exit or move the
        stop, with its confidence, reason and the support/resistance it used. Nothing is done automatically:
        the owner decides. Each consultation is kept on the position (and so on the closed trade in memory)
        to check later whether the advice was right. None: no such open position."""
        p = next((x for x in self.account["positions"] if x["id"] == position_id), None)
        if p is None:
            return None
        now = self.now()
        tf = p["timeframe"]
        charts, btc = await self._ai_context(p["symbol"])
        if tf not in charts:
            try:
                charts[tf] = closed_only(await self.recent(p["symbol"], tf), tf, now)
            except Exception:
                charts[tf] = []
        price = self.prices.get(p["id"]) or (charts[tf][-1]["close"] if charts.get(tf) else p["entryPrice"])
        suggest, reason, detail, state = await self._bot_opinion(p, now)
        way = p["takeProfit"] - p["entryPrice"]
        result = pnl(p, price, self.fees.taker)[0]
        risk = p.get("openRisk") or p["risk"]
        own = charts.get(tf) or []
        trends = {k: (advisor.summarize(v) or {}).get("trend") for k, v in charts.items() if v}
        bot = {"suggest": suggest, "reason": reason, "detail": detail, "marketState": state,
               "progress": round((price - p["entryPrice"]) / way * 100, 1) if way else None,
               "pnl": round(result, 4), "r": round(result / risk, 2) if risk else None, "price": price,
               "trends": trends, "rsi": (advisor.summarize(own) or {}).get("rsi") if own else None,
               **(advisor.swings(own) if len(own) > 10 else {"swingHighAbove": None, "swingLowBelow": None})}
        data = {"position": {"coin": p["base"], "timeframe": tf, "side": p["side"], "entry": p["entryPrice"],
                             "stopLoss": p["stop"], "originalStopLoss": p["stopLoss"], "takeProfit": p["takeProfit"],
                             "priceNow": price, "percentOfTheWayToTarget": bot["progress"], "resultInR": bot["r"],
                             "openedMinutesAgo": round((now - p["entryTime"]) / 60), "leverage": p["leverage"],
                             "liquidation": p["liquidation"]},
                "strategy": {"name": STRATEGIES[p["strategy"]].name if p["strategy"] in STRATEGIES else p["strategy"],
                             "suitsMarketStates": list(STRATEGIES[p["strategy"]].states) if p["strategy"] in STRATEGIES else [],
                             "uses": list(STRATEGIES[p["strategy"]].uses) if p["strategy"] in STRATEGIES else []},
                "marketStateNow": state, "botView": {"suggest": suggest, "reason": reason, "detail": detail},
                "timeframes": {k: advisor.summarize(v) for k, v in charts.items() if v},
                "supportResistance": {k: advisor.swings(v) for k, v in charts.items() if len(v) > 10},
                "bitcoin": {k: advisor.summarize(v) for k, v in btc.items() if v}}
        if own:
            data["last30Candles"] = [[round(c["open"], 10), round(c["high"], 10), round(c["low"], 10),
                                      round(c["close"], 10), round(c.get("volume") or 0, 2)] for c in own[-30:]]
        ai, error = None, None
        keys = self.ai_keys()
        if not keys:
            error = "noKeys"
        else:
            try:
                ai = await self.ai_consult(data, p, price, keys)
                self.ai_error = None
            except advisor.AdvisorUnavailable as e:
                error = self.ai_error = str(e)
            except Exception as e:
                error = repr(e)
        answer = {"position": p["id"], "time": now, "bot": bot, "ai": ai, "error": error}
        if p in self.account["positions"]:   # not closed meanwhile
            p["consults"] = (p.get("consults") or [])[-4:] + [answer]
            self._event("consult", symbol=p["base"], timeframe=tf, suggest=(ai or {}).get("action"))
            self.save()
        return answer

    def answer_advice(self, position_id: int, answer: str) -> bool:
        """Owner's answer "hold" (the position goes on). "close" goes through close_position."""
        p = next((p for p in self.account["positions"] if p["id"] == position_id), None)
        if p is None or not p.get("advice"):
            return False
        p["advice"]["answer"] = answer
        self.save()
        return True

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
        self.notify(telegram.closed_text(trade, self.account["balance"]))
        self.mirror("close", p, reason)

    def mirror(self, what: str, p: dict, reason: str = "") -> None:
        """The real account follows the paper bot (open / close / levels), in the background."""
        real = self.real
        if real is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        call = real.on_open(p, self.prices.get(p["id"])) if what == "open" else \
            real.on_close(p, reason) if what == "close" else real.on_levels(dict(p))

        async def go() -> None:
            try:
                await call
            except Exception:
                logging.getLogger("trading_bot").warning("real account %s failed", what, exc_info=True)

        task = loop.create_task(go())
        self._real_tasks.add(task)
        task.add_done_callback(self._real_tasks.discard)

    def notify(self, text: str, buttons: Optional[list] = None) -> None:
        """A Telegram message, sent in the background (the bot does not wait for it)."""
        settings = telegram.load()
        if not (settings["enabled"] and settings["token"] and settings["chatId"] is not None):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def go() -> None:
            try:
                await telegram.send(text, self.tg_post, settings, buttons)
                self.tg_error = None
            except telegram.TelegramError as error:
                self.tg_error = str(error)
                logging.getLogger("trading_bot").warning("telegram: %s", error)

        task = loop.create_task(go())
        self._tg_tasks.add(task)
        task.add_done_callback(self._tg_tasks.discard)

    async def _scan_and_open(self, tf: str, now: float, trade: bool = True) -> None:
        mode = MODE_OF[tf]
        settings = bot_settings(tf)
        benched = {k for k, until in self.account["benched"].items() if until > now}
        allowed = set(self.account["strategies"]) - benched
        memory = self.memory
        gate = asyncio.Semaphore(8)
        candidates: list[dict] = []
        ticked = tf in self.chosen_timeframes()
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
                    entry["memoryKey"] = memory.record(entry, tf, feats, now, reliable=ok,
                                                       seen_price=rows[-1]["close"] if rows else None)
                    if self.brain is not None:
                        entry["chance"] = self.brain.chance(feats, row["strategy"], tf, entry["signal"]["side"])
                        if entry["chance"] is not None:
                            memory.set_chance(entry["memoryKey"], entry["chance"])
                entry["reliable"] = ok
                passed = ok or not self.profile.use_reliable
                if ticked:   # the screen's counter: only timeframes the owner trades
                    self._count("seen")
                    if not passed:
                        self._count("unreliable")
                    elif row["strategy"] not in allowed:
                        self._count("benched" if row["strategy"] in benched else "notChosen")
                    elif not trade:
                        self._count("paused" if self._paused(now) else "full")
                # On the slow charts only very sure ones (strict_ok); the "reliable" rule only if switched on.
                if passed and row["strategy"] in allowed and strict_ok(entry, tf):
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
            if ticked and memory is not None:   # why the bot's signals were not traded
                reason = "paused" if self._paused(now) else "full"
                for c in candidates:
                    memory.mark(c["memoryKey"], skip_reason=reason)
            return
        if self.brain is not None:  # the brain's filter: skip signals with a low chance of profit
            knob = self.account.get("brainThreshold")
            weak = [c for c in candidates if not self.brain.allows(c.get("chance"), knob)]
            if weak:
                candidates = [c for c in candidates if self.brain.allows(c.get("chance"), knob)]
                for c in weak:
                    if memory is not None and c.get("memoryKey"):
                        memory.mark(c["memoryKey"], skip_reason="brain")
                self._event("skip", reason="brain", timeframe=tf, count=len(weak))
                self._count("brain", len(weak))
        open_coins = {p["symbol"] for p in self.account["positions"]} | {o["symbol"] for o in self.account["orders"]}
        positions = self.account["positions"]
        room = self.max_open() - len(positions) - len(self.account.get("orders", []))
        if room <= 0:
            for c in candidates:
                self._skip(c, tf, "full")
            return
        # Steps 2-3 (owner 2026-11-07): only with the coin's higher-timeframe trend, never in a range,
        # and for coins that follow Bitcoin only with Bitcoin's trend.
        fresh = [c for c in candidates if c["symbol"] not in open_coins]
        checked = []
        for c in sorted(fresh, key=lambda c: c["stats"]["trades"], reverse=True)[:max(room * 3, 6)]:
            if await self._direction_ok(c, tf, now):
                checked.append(c)
        chosen = pick(checked, open_coins, min(room, free_slots(positions, tf, self.profile.slots)),
                      side_room(positions, self.profile.max_same_side))
        for c in chosen:
            if self._ai_on(tf):
                await self._ai_review(c, tf, now, settings[c["strategy"]])
            else:
                await self._open(c, tf, now, settings[c["strategy"]])
        chosen_keys = {c.get("memoryKey") for c in chosen}
        if memory is not None:
            for c in candidates:
                if c.get("memoryKey") not in chosen_keys:
                    memory.mark(c["memoryKey"], skip_reason="full")
        left = len({c["symbol"] for c in candidates} - open_coins) - len(chosen)
        if left > 0:
            self._event("skip", reason="full", timeframe=tf, count=left)
            self._count("full", left)

    # ---- the AI's second opinion (advisor.py)

    def _ai_on(self, tf: str) -> bool:
        return bool(self.account.get("aiEnabled")) and tf in (self.account.get("aiTimeframes") or [])

    async def _ai_context(self, symbol: str) -> tuple[dict, dict]:
        async def get(sym: str, tf: str) -> list[dict]:
            try:
                return closed_only(await self.recent(sym, tf), tf, self.now())
            except Exception:
                return []
        charts = {tf: await get(symbol, tf) for tf in advisor.CONTEXT_TIMEFRAMES}
        btc = {tf: await get(BTC, tf) for tf in ("1h", "4h")} if symbol != BTC else {}
        return charts, btc

    async def _ai_review(self, c: dict, tf: str, now: float, params: dict) -> None:
        """Gemini approves (the trade opens), rejects (skipped, with its reason) or does not answer
        (the owner is asked in the panel)."""
        key = c.get("memoryKey")
        try:
            charts, btc = await self._ai_context(c["symbol"])
            if tf not in charts:
                charts[tf] = closed_only(await self.recent(c["symbol"], tf), tf, now)
            verdict = await self.ai_ask(advisor.brief(c, tf, charts, btc), self.ai_keys())
        except advisor.AdvisorUnavailable as error:
            self.ai_error = str(error)
            if self.memory is not None and key:
                self.memory.set_ai(key, "unavailable", None, str(error))
            ask_id = self.account.get("nextAskId", 1)
            self.account["nextAskId"] = ask_id + 1
            expires = self.now() + ASK_AUTO_SECONDS   # from now: the scan and the AI call took time already
            self.account.setdefault("pendingAsks", []).append(
                {"id": ask_id, "tf": tf, "c": c, "expires": expires, "error": str(error)})
            self._event("ask", symbol=c["base"], timeframe=tf, strategy=c["strategy"], reason=str(error))
            self._count("ask")
            if self.ask_timers:
                asyncio.get_running_loop().create_task(self._ask_timer())
            return
        self.ai_error = None
        if self.memory is not None and key:
            self.memory.set_ai(key, "approve" if verdict["approve"] else "reject",
                               verdict["confidence"], verdict["reason"])
        self._event("ai", symbol=c["base"], timeframe=tf, strategy=c["strategy"], approve=verdict["approve"],
                    confidence=verdict["confidence"], text=verdict["reason"])
        if verdict["approve"]:
            await self._open(c, tf, now, params)
        else:
            self._count("ai")
            if self.memory is not None and key:
                self.memory.mark(key, skip_reason="ai")

    async def _ask_timer(self) -> None:
        """Wakes up when a question's 30 seconds are over (the bot's loop may be busy scanning).
        The lock waits for a running chart scan, so it can be a little later than 30 seconds."""
        await asyncio.sleep(ASK_AUTO_SECONDS + 0.5)
        try:
            async with self.lock:
                await self._auto_open_asks(self.now())
                self.save()
        except Exception:
            logging.getLogger("trading_bot").exception("opening an unanswered signal failed")

    async def _auto_open_asks(self, now: float) -> None:
        """No answer from the AI nor from the owner within ASK_AUTO_SECONDS: the trade opens."""
        asks = self.account.get("pendingAsks") or []
        due = [q for q in asks if q["expires"] <= now]
        self.account["pendingAsks"] = [q for q in asks if q["expires"] > now]
        for q in due:
            self._event("askAnswer", symbol=q["c"]["base"], timeframe=q["tf"], answer="auto")
            await self._open(q["c"], q["tf"], now, bot_settings(q["tf"])[q["c"]["strategy"]])

    async def answer_ask(self, ask_id: int, answer: str) -> bool:
        """The owner's answer when the AI did not answer: open the trade or skip it."""
        async with self.lock:
            now = self.now()
            await self._auto_open_asks(now)
            q = next((q for q in self.account.get("pendingAsks", []) if q["id"] == ask_id), None)
            if q is None:
                return False
            self.account["pendingAsks"] = [x for x in self.account["pendingAsks"] if x["id"] != ask_id]
            key = q["c"].get("memoryKey")
            if answer == "open":
                self._event("askAnswer", symbol=q["c"]["base"], timeframe=q["tf"], answer="open")
                await self._open(q["c"], q["tf"], now, bot_settings(q["tf"])[q["c"]["strategy"]])
            else:
                self._event("askAnswer", symbol=q["c"]["base"], timeframe=q["tf"], answer="skip")
                if self.memory is not None and key:
                    self.memory.mark(key, skip_reason="owner")
            self.save()
            return True

    def set_ai(self, enabled: bool, timeframes: list[str]) -> None:
        self.account["aiEnabled"] = bool(enabled)
        self.account["aiTimeframes"] = [tf for tf in self.profile.timeframes if tf in timeframes]
        self.save()

    def _skip(self, c: dict, tf: str, reason: str) -> None:
        self._count(reason)
        self._event("skip", symbol=c["base"], timeframe=tf, reason=reason)
        if self.memory is not None and c.get("memoryKey"):
            self.memory.mark(c["memoryKey"], skip_reason=reason)

    async def _trend(self, symbol: str, tf: str, now: float) -> Optional[str]:
        htf = HIGHER_TF.get(tf)
        if htf is None:
            return None
        try:
            return trend_of(closed_only(await self.history(symbol, htf), htf, now))
        except Exception:
            return None

    async def _btc_link(self, symbol: str, now: float) -> Optional[float]:
        """The coin's correlation with Bitcoin (1h returns, 30 days), worked out once a day per coin."""
        if symbol == BTC_SYMBOL:
            return 1.0
        cached = self.btc_links.get(symbol)
        if cached and now - cached[0] < BTC_LINK_SECONDS:
            return cached[1]
        try:
            coin = closed_only(await self.history(symbol, "1h"), "1h", now)
            btc = closed_only(await self.history(BTC_SYMBOL, "1h"), "1h", now)
            corr = btc_correlation(coin, btc)
        except Exception:
            corr = None
        self.btc_links[symbol] = (now, corr)
        return corr

    async def _direction_ok(self, c: dict, tf: str, now: float) -> bool:
        """Steps 2-3 of the owner's design: the coin's trend on the higher timeframe must be the trade's way
        (range: skip "range"; the other way: "against"); a coin that follows Bitcoin also needs Bitcoin's trend
        the same way (Bitcoin in a range: "btcFlat"; the other way: "btcAgainst")."""
        side = c["signal"]["side"]
        want = "up" if side == LONG else "down"
        trend = await self._trend(c["symbol"], tf, now)
        c["trend"] = trend
        if trend is None:
            return True   # not enough candles to tell: as before
        if trend == "range":
            self._skip(c, tf, "range")
            return False
        if trend != want:
            self._skip(c, tf, "against")
            return False
        link = await self._btc_link(c["symbol"], now)
        c["btcLink"] = link
        if link is not None and link >= BTC_FOLLOWER and c["symbol"] != BTC_SYMBOL:
            btc = await self._trend(BTC_SYMBOL, tf, now)
            c["btcTrend"] = btc
            if btc == "range":
                self._skip(c, tf, "btcFlat")
                return False
            if btc is not None and btc != want:
                self._skip(c, tf, "btcAgainst")
                return False
        return True

    async def _btc_view(self, now: float) -> None:
        """Bitcoin's trend on 1h and 4h for the panel (step 3)."""
        view = {}
        for htf in ("1h", "4h"):
            try:
                view[htf] = trend_of(closed_only(await self.history(BTC_SYMBOL, htf), htf, now))
            except Exception:
                view[htf] = None
        self.btc_state = {"time": now, **view}

    async def _open(self, c: dict, tf: str, now: float, params: dict) -> None:
        recent = await self.recent(c["symbol"], tf)
        if not recent:
            return
        entry = recent[-1]["close"]             # the price now
        s = c["signal"]
        long_ = s["side"] == LONG
        if self.account.get("limitEntry"):      # the entry will be the order's price, a little better
            entry_at = entry - (1 if long_ else -1) * LIMIT_OFFSET * abs(entry - s["stopLoss"])
        else:
            entry_at = entry
        anchored = anchor_target(s["side"], s.get("entry"), entry_at, s["stopLoss"], s["takeProfit"])
        if anchored is not None:                # the target counted from the real entry (see anchor_target)
            s = {**s, "takeProfit": anchored}
            c = {**c, "signal": s}
        stop, target = s["stopLoss"], s["takeProfit"]
        def skip(reason: str) -> None:
            self._count(reason)
            self._event("skip", symbol=c["base"], timeframe=tf, reason=reason)
            if self.memory is not None and c.get("memoryKey"):
                self.memory.mark(c["memoryKey"], skip_reason=reason)

        # The price may have moved since the signal: skip if it already passed the stop or the target,
        # or moved too far for the stop to still be where the strategy meant it.
        if anchored is None or ((entry <= stop or entry >= target) if long_ else (entry >= stop or entry <= target)):
            return skip("past")
        if is_stale(s["entry"], entry, stop):
            return skip("stale")
        if not fee_ok(entry, stop, self.fees, params.get("fee_ratio", 0)):
            return skip("fee")
        # Checked again at the price now: the price may have moved toward the target since the signal.
        if not reward_ok(entry, stop, target, self.fees):
            return skip("reward")
        if any(o["symbol"] == c["symbol"] for o in self.account["orders"]):
            return skip("full")   # a limit order for this coin is already waiting (one per coin)
        if len(self.account["positions"]) + len(self.account.get("orders", [])) >= self.max_open():
            return skip("full")   # owner 2026-11-07: at most 6 open trades
        equity = self.equity()
        if self.account.get("limitEntry"):
            return self._place_order(c, tf, now, params, entry, recent[-1]["time"], equity, skip, price_step(recent))
        size = position_size(s["side"], entry, stop, equity, equity - self.used_margin(), self.fees,
                             self.slots())
        if size is None or size.notional <= 0:
            return skip("full")   # no free money left for another position
        self._new_position(c, tf, now, params, entry, recent[-1]["time"], size, self.fees.taker, "market")

    def used_margin(self) -> float:
        """Margin of the open positions plus the margin set aside for waiting limit orders."""
        return (sum(p["margin"] for p in self.account["positions"])
                + sum(o["margin"] for o in self.account.get("orders", [])))

    def _new_position(self, c: dict, tf: str, now: float, params: dict, entry: float, entry_candle: int,
                      size: Size, entry_fee: float, entry_type: str) -> dict:
        """entry_fee: the entry's fee rate in percent (taker at the market, maker for a filled limit order)."""
        s = c["signal"]
        stop, target = s["stopLoss"], s["takeProfit"]
        a = self.account
        position = {
            "id": a["nextId"], "symbol": c["symbol"], "base": c["base"], "timeframe": tf,
            "strategy": c["strategy"], "side": s["side"], "entryTime": now, "entryPrice": entry,
            "entryCandle": entry_candle, "checkedFrom": entry_candle,
            "signalTime": s["time"], "stopLoss": stop, "stop": stop, "takeProfit": target,
            "quantity": size.quantity, "notional": size.notional, "leverage": size.leverage,
            "margin": size.margin, "risk": size.risk, "openRisk": size.risk, "liquidation": size.liquidation,
            "entryFee": size.notional * entry_fee / 100, "entryType": entry_type,
            "breakevenPart": params.get("breakeven", 0),
            "breakevenPrice": breakeven_price(s["side"], entry, self.fees, entry_fee), "breakevenAt": None,
            "history": {"trades": c["stats"]["trades"], "winRate": c["stats"].get("winRate"),
                        "profitFactor": c["stats"]["profitFactor"]},
            "trend": c.get("trend"), "btcLink": c.get("btcLink"), "btcTrend": c.get("btcTrend"),
            "focus": bool(a.get("focus")),
            # Why the bot entered (the owner's "explanation" button, 2026-11-07).
            "why": {"signalPrice": s.get("entry"), "signalTime": s["time"], "marketState": c.get("marketState"),
                    "higherTf": HIGHER_TF.get(tf), "feeShare": 2 * self.fees.taker / 100 * entry / abs(entry - stop)
                    if entry != stop else None, "reward": abs(target - entry) / abs(entry - stop) if entry != stop else None,
                    "chance": c.get("chance")},
        }
        a["nextId"] += 1
        a["positions"].append(position)
        self.prices[position["id"]] = entry
        self._count("opened")
        self._event("open", symbol=c["base"], side=s["side"], timeframe=tf, strategy=c["strategy"],
                    leverage=size.leverage, entryType=entry_type)
        self.notify(telegram.opened_text(position))
        self.mirror("open", position)
        if self.memory is not None and c.get("memoryKey"):
            self.memory.mark(c["memoryKey"], taken=True)
        return position

    # ---- limit entry (owner's switch; paper only)

    def set_lock(self, enabled: bool, trigger: float, at: float) -> None:
        """Owner's profit lock: on/off, and the two shares of the way to the target in percent."""
        self.account["lockEnabled"] = bool(enabled)
        self.account["lockTrigger"] = float(trigger)
        self.account["lockAt"] = float(at)
        self.save()

    def max_open(self) -> int:
        """Owner's setting (2026-11-10): how many trades may be open at once (waiting limit orders count)."""
        return int(self.account.get("maxOpen") or MAX_POSITIONS)

    def slots(self) -> int:
        """Margin of one position at most equity / this (follows the owner's maximum, as with 6)."""
        return self.max_open() if self.account.get("maxOpen") else self.profile.size_slots

    def set_max_open(self, n: int) -> None:
        self.account["maxOpen"] = max(1, min(20, int(n)))
        self.save()

    def set_focus(self, on: bool) -> None:
        """Owner's focus switch: on = keep the current timeframes / coin choice and trade 5m + 15m on the
        volatile coins; off = the kept settings come back exactly."""
        a = self.account
        if on and not a.get("focus"):
            a["focus"] = {"since": self.now(), "saved": {k: copy.deepcopy(a[k]) for k in FOCUS_KEYS if k in a}}
            a["chosenTimeframes"] = [tf for tf in self.profile.timeframes if tf in FOCUS_TIMEFRAMES] \
                or a.get("chosenTimeframes")
            a["coinMode"] = "volatile"
            self._event("focus", on=True)
        elif not on and a.get("focus"):
            saved = a["focus"].get("saved") or {}
            for k in FOCUS_KEYS:
                if k in saved:
                    a[k] = saved[k]
                else:
                    a.pop(k, None)
            a["coinMode"] = a.get("coinMode", "top")
            a["focus"] = None
            self._event("focus", on=False)
        self.save()

    def focus_stats(self) -> dict:
        """Closed trades opened in focus mode against the others (count, wins, losses, net USDT)."""
        out = {}
        for name, want in (("focus", True), ("other", False)):
            trades = [t for t in self.account["closed"] if bool(t.get("focus")) == want]
            wins = sum(1 for t in trades if trade_outcome(t) == "win")
            losses = sum(1 for t in trades if trade_outcome(t) == "loss")
            out[name] = {"trades": len(trades), "wins": wins, "losses": losses,
                         "pnl": sum(t["pnl"] for t in trades)}
        return out

    def set_review(self, enabled: Optional[bool] = None, after: Optional[int] = None,
                   every: Optional[dict] = None) -> None:
        """Owner's look at long positions: on/off, after how many candles, every how many minutes per timeframe."""
        a = self.account
        if enabled is not None:
            a["reviewEnabled"] = bool(enabled)
        if after is not None:
            a["reviewAfter"] = max(1, min(500, int(after)))
        if every:
            merged = {**REVIEW_EVERY, **(a.get("reviewEvery") or {})}
            for tf, minutes in every.items():
                if tf in REVIEW_EVERY and minutes is not None:
                    merged[tf] = max(1, min(1440, int(minutes)))
            a["reviewEvery"] = merged
        self.save()

    def set_limit_entry(self, enabled: bool) -> None:
        self.account["limitEntry"] = bool(enabled)
        if not enabled:
            self._cancel_orders("limit_cancelled", "off")
        self.save()

    def _place_order(self, c: dict, tf: str, now: float, params: dict, price_now: float, candle: int,
                     equity: float, skip: Callable[[str], None], step: Optional[float] = None) -> None:
        """A limit order a little better than the price now (LIMIT_OFFSET of the stop distance).
        The margin it will need is set aside now, so waiting orders never use more than the money there is."""
        s = c["signal"]
        long_ = s["side"] == LONG
        stop = s["stopLoss"]
        price = price_now - (1 if long_ else -1) * LIMIT_OFFSET * abs(price_now - stop)
        rounded = to_step(price, step, down=long_)   # the coin's price step, like a real order
        # A step too coarse to tell (e.g. candles with whole prices only) must not push the order onto the
        # stop or past the price now: then the unrounded price is kept.
        if (stop < rounded < price_now) if long_ else (price_now < rounded < stop):
            price = rounded
        size = position_size(s["side"], price, stop, equity, equity - self.used_margin(), self.fees,
                             self.slots())
        if size is None or size.notional <= 0:
            return skip("full")
        a = self.account
        order = {"id": a["nextId"], "symbol": c["symbol"], "base": c["base"], "timeframe": tf,
                 "strategy": c["strategy"], "side": s["side"], "price": price, "placedPrice": price_now,
                 "placedAt": now, "expires": now + LIMIT_EXPIRE_CANDLES * config.TIMEFRAME_SECONDS[tf],
                 # Watched on 1m candles (the expiry is exact to the minute); the rest of the minute now:
                 # live price only (which part of it came after the order is not known).
                 "checkedFrom": int(now // ORDER_CANDLE_SECONDS) * ORDER_CANDLE_SECONDS + ORDER_CANDLE_SECONDS,
                 "stopLoss": stop, "takeProfit": s["takeProfit"], "margin": size.margin,
                 "params": {"breakeven": params.get("breakeven", 0), "fee_ratio": params.get("fee_ratio", 0)},
                 "c": {k: c[k] for k in ("symbol", "base", "strategy", "stats", "signal", "trend", "btcLink", "btcTrend",
                                         "marketState", "chance") if k in c}
                      | {"memoryKey": c.get("memoryKey")}}
        a["nextId"] += 1
        a["orders"].append(order)
        a["limitStats"]["placed"] += 1
        self._count("limitPlaced")
        self._event("order", symbol=c["base"], side=s["side"], timeframe=tf, strategy=c["strategy"], price=price)

    def _cancel_order(self, o: dict, reason: str, why: str) -> None:
        """reason: limit_expired | limit_cancelled (memory and counter); why: what happened (diary)."""
        if o not in self.account["orders"]:
            return
        self.account["orders"].remove(o)
        self.account["limitStats"]["expired" if reason == "limit_expired" else "cancelled"] += 1
        self._count(reason)
        self._event("orderCancel", symbol=o["base"], timeframe=o["timeframe"], reason=reason, detail=why)
        key = o["c"].get("memoryKey")
        if self.memory is not None and key:
            self.memory.mark(key, skip_reason=reason)

    def _cancel_orders(self, reason: str, why: str) -> None:
        for o in list(self.account.get("orders", [])):
            self._cancel_order(o, reason, why)

    async def _watch_orders(self, now: float) -> None:
        for o in list(self.account.get("orders", [])):
            try:
                await self._watch_order(o, now)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logging.getLogger("trading_bot").warning("checking the order of %s failed: %r", o.get("base"), error)

    async def _watch_order(self, o: dict, now: float) -> None:
        """Fill only when the price went beyond the order (a buy: below it; a sell: above it). Cancelled
        when the target (or the stop) is reached first, or when it expires. Without optimism: a closed
        candle that reached the target and also crossed the order counts as cancelled (the order inside
        the candle is not known), and a fill whose candle also reached the stop is stopped out at once."""
        m = ORDER_CANDLE_SECONDS
        tf_seconds = config.TIMEFRAME_SECONDS[o["timeframe"]]
        candles, _ = await self._candles_since(o, o["symbol"], ORDER_CANDLE_TF, o["checkedFrom"])
        long_ = o["side"] == LONG
        price, stop, target = o["price"], o["stopLoss"], o["takeProfit"]
        for c in candles or []:
            if c["time"] < o["checkedFrom"]:
                continue
            if c["time"] + m > now or c["time"] + m > o["expires"]:
                break   # still forming, or partly after the expiry
            crossed = (c["low"] < price) if long_ else (c["high"] > price)
            at_target = (c["high"] >= target) if long_ else (c["low"] <= target)
            at_stop = (c["low"] <= stop) if long_ else (c["high"] >= stop)
            if at_target:
                return self._cancel_order(o, "limit_cancelled", "target")
            if crossed:
                gapped = (c["open"] < stop) if long_ else (c["open"] > stop)
                stopped_at = (c["open"] if gapped else stop) if at_stop else None
                p = self._fill(o, c["time"] - c["time"] % tf_seconds, now, stopped_at)
                if p is not None and p in self.account["positions"]:
                    self._after_fill(p, [x for x in candles if c["time"] < x["time"] and x["time"] + m <= now])
                return
            if at_stop:
                return self._cancel_order(o, "limit_cancelled", "stop")
            o["checkedFrom"] = c["time"] + m
        if candles and now < o["expires"]:
            last = candles[-1]["close"]
            if (last >= target) if long_ else (last <= target):
                return self._cancel_order(o, "limit_cancelled", "target")
            if (last < price) if long_ else (last > price):
                stopped_at = last if ((last <= stop) if long_ else (last >= stop)) else None
                return self._fill(o, int(now - now % tf_seconds), now, stopped_at)
        if now >= o["expires"]:
            self._cancel_order(o, "limit_expired", "time")

    def _after_fill(self, p: dict, minutes: list[dict]) -> None:
        """The fill was noticed late (on a closed 1m candle): the minutes since then are checked for the
        stop (first) and the target, like the closed candles of an open position."""
        long_ = p["side"] == LONG
        for c in minutes:
            if (c["low"] <= p["stop"]) if long_ else (c["high"] >= p["stop"]):
                gapped = (c["open"] < p["stop"]) if long_ else (c["open"] > p["stop"])
                return self._close(p, c["open"] if gapped else p["stop"], "stop", self.now())
            if (c["high"] >= p["takeProfit"]) if long_ else (c["low"] <= p["takeProfit"]):
                return self._close(p, p["takeProfit"], "target", self.now())

    def _fill(self, o: dict, entry_candle: int, now: float, stopped_at: Optional[float]) -> Optional[dict]:
        """The order filled at its price: the position opens with the signal's stop and target, a maker
        entry fee, the size counted at the fill price; the fee and reward rules are checked again there."""
        if o not in self.account["orders"]:
            return None   # cancelled meanwhile (the owner switched limit entry off while it was checked)
        self.account["orders"].remove(o)
        c, price = o["c"], o["price"]
        stop, target = o["stopLoss"], o["takeProfit"]
        key = c.get("memoryKey")
        def refuse(reason: str) -> None:   # returns None
            self.account["limitStats"]["cancelled"] += 1
            self._count(reason)
            self._event("orderCancel", symbol=o["base"], timeframe=o["timeframe"], reason="limit_cancelled",
                        detail=reason)
            if self.memory is not None and key:
                self.memory.mark(key, skip_reason=reason)
        if not fee_ok(price, stop, self.fees, o["params"].get("fee_ratio", 0)):
            return refuse("fee")
        if not reward_ok(price, stop, target, self.fees):
            return refuse("reward")
        equity = self.equity()
        size = position_size(o["side"], price, stop, equity, equity - self.used_margin(), self.fees,
                             self.slots())
        if size is None or size.notional <= 0:
            return refuse("full")
        self.account["limitStats"]["filled"] += 1
        # entry_candle: the candle of the trade's timeframe the fill happened in (its rest: live price only).
        p = self._new_position(c, o["timeframe"], now, o["params"], price, entry_candle, size, self.fees.maker, "limit")
        if stopped_at is not None:   # the same candle (or price) also reached the stop
            self._close(p, stopped_at, "stop", now)
        return p
