"""The scanner: every strategy on every coin of the list at once (owner's idea),
so the best coin + strategy pairs can be seen without opening each chart.

Per coin it does exactly what the strategies table does (same candles,
rules, settings and fees). Two lists come out:
- max profit: the best strategy of each coin by total result;
- cautious:   only strategies that suit the coin's current market state, with
              at least MIN_TRADES trades and a profit factor above 1; the best
              profit factor of each coin.
And a third: signals. A strategy that signals on the last closed candle (and
has no position open) would open a trade at the next candle; the last
SIGNAL_LOG of these are kept, the reliable ones (cautious conditions) marked.

A scan runs in the background; the screen asks for its progress and result.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from . import config
from .analysis import strategy_overview
from .strategies import MIN_TRADES, STRATEGIES, Fees

TOP_ROWS = 10
SIGNAL_LOG = 20
PARALLEL = 8  # coins fetched at the same time (ccxt still keeps to the exchange's speed limit)


def _pf(stats: dict) -> float:
    return stats["profitFactor"] if stats["profitFactor"] is not None else float("inf")


def coin_rows(symbol: str, base: str, overview: dict) -> list[dict]:
    """One entry per strategy of one coin."""
    return [{
        "symbol": symbol,
        "base": base,
        "strategy": row["strategy"],
        "marketState": overview["marketState"],
        "stats": row["stats"],
        "signal": row.get("signal"),
    } for row in overview["rows"]]


def reliable(e: dict) -> bool:
    """The cautious conditions: suits the coin's market state, enough trades, profitable."""
    s = e["stats"]
    return (e["marketState"] in STRATEGIES[e["strategy"]].states and s["trades"] >= MIN_TRADES
            and s["netPercent"] > 0 and _pf(s) > 1)


def signal_entries(entries: list[dict]) -> list[dict]:
    return [{**e, "reliable": reliable(e)} for e in entries if e.get("signal")]


def merge_log(old: list[dict], new: list[dict], keep: int = SIGNAL_LOG) -> list[dict]:
    """Newest first (reliable first within the same candle); a signal is listed once."""
    seen: dict[tuple, dict] = {}
    for e in old + new:
        seen[(e["symbol"], e["strategy"], e["signal"]["time"])] = e
    ordered = sorted(seen.values(), key=lambda e: (e["signal"]["time"], e["reliable"]), reverse=True)
    return ordered[:keep]


def top_max_profit(entries: list[dict], n: int = TOP_ROWS) -> list[dict]:
    best: dict[str, dict] = {}
    for e in entries:
        s = e["stats"]
        if s["trades"] == 0 or s["netPercent"] <= 0:
            continue
        current = best.get(e["symbol"])
        if current is None or (s["netPercent"], s["trades"]) > (current["stats"]["netPercent"], current["stats"]["trades"]):
            best[e["symbol"]] = e
    return sorted(best.values(), key=lambda e: (e["stats"]["netPercent"], e["stats"]["trades"]), reverse=True)[:n]


def top_cautious(entries: list[dict], n: int = TOP_ROWS) -> list[dict]:
    best: dict[str, dict] = {}
    for e in entries:
        s = e["stats"]
        if not reliable(e):
            continue
        current = best.get(e["symbol"])
        if current is None or (_pf(s), s["trades"]) > (_pf(current["stats"]), current["stats"]["trades"]):
            best[e["symbol"]] = e
    return sorted(best.values(), key=lambda e: (_pf(e["stats"]), e["stats"]["trades"]), reverse=True)[:n]


@dataclass
class Scan:
    key: str
    period: int  # which candle period it belongs to (a new closed candle starts a new scan)
    total: int = 0
    done: int = 0
    failed: list[str] = field(default_factory=list)
    entries: list[dict] = field(default_factory=list)
    running: bool = True
    error: Optional[str] = None
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)
    previous: Optional[dict] = None  # last finished tables, shown while a new scan runs
    log: list[dict] = field(default_factory=list)  # latest signals, carried from scan to scan

    def tables(self) -> dict:
        return {"maxProfit": top_max_profit(self.entries), "cautious": top_cautious(self.entries),
                "finishedAt": self.finished}

    def public(self) -> dict:
        shown = self.tables() if not self.running else (self.previous or {"maxProfit": [], "cautious": [], "finishedAt": None})
        return {
            "running": self.running,
            "done": self.done,
            "total": self.total,
            "failed": self.failed,
            "error": self.error,
            "signals": self.log,
            **shown,
        }


Coins = Callable[[], Awaitable[list[tuple[str, str]]]]          # -> [(symbol, base)]
Candles = Callable[[str], Awaitable[list[dict]]]                # symbol -> candles


async def run_scan(scan: Scan, coins: Coins, candles: Candles, timeframe: str, trading_mode: str,
                   settings: dict[str, dict], fees: Fees, now: Callable[[], float] = time.time) -> None:
    try:
        targets = await coins()
        scan.total = len(targets)
        gate = asyncio.Semaphore(PARALLEL)

        async def one(symbol: str, base: str) -> None:
            async with gate:
                try:
                    rows = await candles(symbol)
                    overview = strategy_overview(rows, timeframe, settings, None, trading_mode, now=now(), fees=fees)
                    scan.entries.extend(coin_rows(symbol, base, overview))
                except Exception:  # one coin failing does not stop the scan
                    scan.failed.append(base)
                finally:
                    scan.done += 1

        await asyncio.gather(*(one(symbol, base) for symbol, base in targets))
        scan.log = merge_log(scan.log, signal_entries(scan.entries))
    except Exception as error:
        scan.error = str(error)
    finally:
        scan.running = False
        scan.finished = now()


class Scanner:
    """Keeps the latest scan per (market type, timeframe, mode, settings, fees)."""

    def __init__(self, now: Callable[[], float] = time.time):
        self.now = now
        self.scans: dict[str, Scan] = {}

    @staticmethod
    def key(market_type: str, timeframe: str, trading_mode: str, settings: dict, fees: Fees) -> str:
        return json.dumps([market_type, timeframe, trading_mode, settings, [fees.maker, fees.taker]], sort_keys=True)

    def get_or_start(self, key: str, timeframe: str, start: Callable[[Scan], Awaitable[None]]) -> Scan:
        """The scan for this key and candle period; a new one starts when a candle has closed since."""
        period = int(self.now() // config.TIMEFRAME_SECONDS[timeframe])
        scan = self.scans.get(key)
        if scan is not None and (scan.period == period or scan.running):
            return scan
        previous = scan.tables() if scan is not None and scan.error is None else None
        scan = Scan(key=key, period=period, previous=previous, log=list(scan.log) if scan is not None else [])
        self.scans = {k: v for k, v in self.scans.items() if v.running}  # drop old finished scans
        self.scans[key] = scan
        scan.task = asyncio.create_task(start(scan))
        return scan
