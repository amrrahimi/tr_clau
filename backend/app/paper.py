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
from . import advisor, pretrain
from .memory import Memory, features
from .scanner import reliable
from .strategies import LONG, STRATEGIES, Fees, breakeven_price, fee_ok, parse_params, reward_ok

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"]
OLD_TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"]   # the bot's list before 30m and 4h were added
SCAN_ORDER = list(reversed(TIMEFRAMES))  # biggest first
STALE_PART = 0.25             # of the stop distance: further than this from the signal price = too late
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
MAX_OPEN = 6                  # sizing only: one position may lock at most a sixth of the money as margin

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
        if (c["low"] <= stop) if long_ else (c["high"] >= stop):
            reason = _stop_reason(position)
            # A gap past the stop (the candle opened beyond it) fills at the open, worse than the stop.
            gapped = (c["open"] < stop) if long_ else (c["open"] > stop)
            if c["time"] == hole_before:
                gapped = False
            return (c["open"] if gapped else stop), reason
        if (c["high"] >= target) if long_ else (c["low"] <= target):
            return target, "target"
        position["checkedFrom"] = c["time"] + tf_seconds
        _maybe_breakeven(position, c["high"] if long_ else c["low"], c["time"])
        _maybe_lock(position, c["high"] if long_ else c["low"], c["time"])
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
        _maybe_lock(position, last_price, int(now))   # the price seen now can lock the profit too
    return None


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


def trade_outcome(trade: dict) -> str:
    """win / loss / even. A trade closed at the break-even stop (or with a result of practically
    zero, e.g. a billionth of a dollar from rounding) is "even", not a loss."""
    if trade.get("exitReason") == "breakeven" or abs(trade["pnl"]) < trade["notional"] * EVEN_PART:
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
        self.ai_keys = advisor.load_keys     # keys live in settings.json on this computer
        self.ai_error: Optional[str] = None  # the last reason Gemini did not answer (for the screen)
        self.ask_timers = True               # open an unanswered question after ASK_AUTO_SECONDS (off in tests)

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
            "ai": {"enabled": a.get("aiEnabled", False), "timeframes": a.get("aiTimeframes", []),
                   "model": advisor.load_model(), "keys": advisor.masked(self.ai_keys()), "lastError": self.ai_error,
                   "results": self.memory.ai_summary() if self.memory is not None else {}},
            "pendingAsks": [{"id": q["id"], "symbol": q["c"]["symbol"], "base": q["c"]["base"],
                             "timeframe": q["tf"], "strategy": q["c"]["strategy"], "side": q["c"]["signal"]["side"],
                             "entry": q["c"]["signal"]["entry"], "stopLoss": q["c"]["signal"]["stopLoss"],
                             "takeProfit": q["c"]["signal"]["takeProfit"], "expires": q["expires"],
                             "error": q.get("error")} for q in a.get("pendingAsks", [])],
            "limitEntry": a.get("limitEntry", False),
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
                "winRate": len(wins) / len(closed) * 100 if closed else None,
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
                      "maxOpen": None if self.profile.max_open >= UNLIMITED else self.profile.max_open,
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
                                              "limitEntry", "lockEnabled", "lockTrigger", "lockAt")
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
        self.save()
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
            try:
                await self._watch_one(p, now)
            except asyncio.CancelledError:
                raise
            except Exception as error:   # e.g. a timeout for this coin: the other positions are still checked
                logging.getLogger("trading_bot").warning("checking %s failed: %r", p.get("base"), error)

    async def _watch_one(self, p: dict, now: float) -> None:
        a = self.account
        if a.get("lockEnabled"):   # the owner's profit lock, for open positions too
            p["lock"] = {"trigger": a.get("lockTrigger", LOCK_TRIGGER * 100) / 100, "at": a.get("lockAt", LOCK_AT * 100) / 100}
        else:
            p.pop("lock", None)
        tf_seconds = config.TIMEFRAME_SECONDS[p["timeframe"]]
        since = max(p["checkedFrom"], p["entryCandle"] + tf_seconds)
        candles, hole_before = await self._candles_since(p, p["symbol"], p["timeframe"], since)
        if not candles:
            return
        last = candles[-1]["close"]
        self.prices[p["id"]] = last
        hit = check_exit(p, candles, last, tf_seconds, now, hole_before)
        cap = self.account.get("profitCap") or 0
        if hit is None and cap > 0 and pnl(p, last, self.fees.taker)[0] >= cap:
            hit = (last, "cap")   # owner's profit cap: take the small profit now
        if hit:
            self._close(p, hit[0], hit[1], now)
        elif self.profile.advice and p.get("advice") is None and self._half_way(p, last):
            await self._advise(p, now)

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
        chosen = pick(candidates, open_coins, free_slots(positions, tf, self.profile.slots),
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

    async def _open(self, c: dict, tf: str, now: float, params: dict) -> None:
        recent = await self.recent(c["symbol"], tf)
        if not recent:
            return
        entry = recent[-1]["close"]             # the price now
        s = c["signal"]
        stop, target = s["stopLoss"], s["takeProfit"]
        long_ = s["side"] == LONG
        def skip(reason: str) -> None:
            self._count(reason)
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
        # Checked again at the price now: the price may have moved toward the target since the signal.
        if not reward_ok(entry, stop, target, self.fees):
            return skip("reward")
        if any(o["symbol"] == c["symbol"] for o in self.account["orders"]):
            return skip("full")   # a limit order for this coin is already waiting (one per coin)
        equity = self.equity()
        if self.account.get("limitEntry"):
            return self._place_order(c, tf, now, params, entry, recent[-1]["time"], equity, skip, price_step(recent))
        size = position_size(s["side"], entry, stop, equity, equity - self.used_margin(), self.fees,
                             self.profile.size_slots)
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
        }
        a["nextId"] += 1
        a["positions"].append(position)
        self.prices[position["id"]] = entry
        self._count("opened")
        self._event("open", symbol=c["base"], side=s["side"], timeframe=tf, strategy=c["strategy"],
                    leverage=size.leverage, entryType=entry_type)
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
                             self.profile.size_slots)
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
                 "c": {k: c[k] for k in ("symbol", "base", "strategy", "stats", "signal") if k in c}
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
                             self.profile.size_slots)
        if size is None or size.notional <= 0:
            return refuse("full")
        self.account["limitStats"]["filled"] += 1
        # entry_candle: the candle of the trade's timeframe the fill happened in (its rest: live price only).
        p = self._new_position(c, o["timeframe"], now, o["params"], price, entry_candle, size, self.fees.maker, "limit")
        if stopped_at is not None:   # the same candle (or price) also reached the stop
            self._close(p, stopped_at, "stop", now)
        return p
