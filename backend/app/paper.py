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
    smart_pause: bool = True
    advice: bool = True
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
        # Settings, not results: kept (owner 2026-11-03: the manual strategy choice was lost here).
        kept = {k: self.account[k] for k in ("profitCap", "pauseLosses", "pauseFall", "brainThreshold",
                                              "mode", "strategies", "coinMode", "coins", "aiEnabled", "aiTimeframes")
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
            await self._watch_positions(now)
            equity = self.equity()
            self._track_drawdown(equity)
            if equity <= self.account["capital"] * (1 - TOTAL_STOP):
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
            if k not in ("seen", "opened"):
                skipped[k] = skipped.get(k, 0) + 1
        return {"minutes": FLOW_SECONDS // 60, "seen": recent.count("seen"), "opened": recent.count("opened"),
                "skipped": skipped}

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
            elif self.profile.advice and p.get("advice") is None and self._half_way(p, last):
                await self._advise(p, now)

    @staticmethod
    def _half_way(p: dict, price: float) -> bool:
        trigger = p["entryPrice"] + (p["takeProfit"] - p["entryPrice"]) * ADVICE_PART
        return price >= trigger if p["side"] == LONG else price <= trigger

    async def _advise(self, p: dict, now: float) -> None:
        """Half way to the target: look at the chart again and advise the owner to hold or to close.
        close: another strategy now gives a reliable signal the other way, or the market state no
        longer suits the strategy (or turned against the trade). The owner answers with a button;
        without an answer the position simply goes on."""
        tf = p["timeframe"]
        suggest, reason, detail = "hold", "fine", ""
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
        open_pnl = pnl(p, self.prices.get(p["id"], p["entryPrice"]), self.fees.taker)[0]
        p["advice"] = {"time": now, "suggest": suggest, "reason": reason, "detail": detail, "pnl": open_pnl,
                       "answer": None}
        self._event("advice", symbol=p["base"], timeframe=tf, reason=reason, suggest=suggest, detail=detail)

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
                    entry["memoryKey"] = memory.record(entry, tf, feats, now, reliable=ok)
                    if ok and self.brain is not None:
                        entry["chance"] = self.brain.chance(feats, row["strategy"], tf, entry["signal"]["side"])
                        if entry["chance"] is not None:
                            memory.set_chance(entry["memoryKey"], entry["chance"])
                entry["reliable"] = ok
                if ticked:   # the screen's counter: only timeframes the owner trades
                    self._count("seen")
                    if not ok:
                        self._count("unreliable")
                    elif row["strategy"] not in allowed:
                        self._count("benched" if row["strategy"] in benched else "notChosen")
                    elif not trade:
                        self._count("paused" if self._paused(now) else "full")
                # The bot trades reliable signals only, and on the slow charts only very sure ones.
                if ok and row["strategy"] in allowed and strict_ok(entry, tf):
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
        open_coins = {p["symbol"] for p in self.account["positions"]}
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
        used = sum(p["margin"] for p in self.account["positions"])
        equity = self.equity()
        size = position_size(s["side"], entry, stop, equity, equity - used, self.fees, self.profile.size_slots)
        if size is None or size.notional <= 0:
            return skip("full")   # no free money left for another position
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
        self._count("opened")
        self._event("open", symbol=c["base"], side=s["side"], timeframe=tf, strategy=c["strategy"],
                    leverage=size.leverage)
        if self.memory is not None and c.get("memoryKey"):
            self.memory.mark(c["memoryKey"], taken=True)
