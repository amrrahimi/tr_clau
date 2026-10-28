"""Long candle history for the strategies table (5000 candles).

Exchanges give at most 1000 candles per request, so the first time a chart
is opened the history is fetched in pages going back in time. It is then
kept in memory, and later requests only fetch the newest page and add it on.
"""

from __future__ import annotations

import time
from array import array
from typing import Awaitable, Callable, Optional

from . import config

STRATEGY_CANDLES = 5000
PAGE = config.MAX_CANDLE_LIMIT
# Keep at most this many charts in memory (oldest used is dropped first).
MAX_CHARTS = 110  # the scanner alone needs 100

Fetch = Callable[[int, Optional[int]], Awaitable[list[dict]]]  # (limit, before) -> candles


def merge(old: list[dict], new: list[dict], keep: int) -> list[dict]:
    """Candles of both lists by time (a newer copy of the same candle wins), oldest first, last `keep`."""
    by_time = {c["time"]: c for c in old}
    for c in new:
        by_time[c["time"]] = c
    return [by_time[t] for t in sorted(by_time)][-keep:]


async def fetch_history(fetch: Fetch, total: int = STRATEGY_CANDLES) -> list[dict]:
    """Newest `total` candles, fetched page by page going back in time."""
    candles = await fetch(PAGE, None)
    while candles and len(candles) < total:
        older = await fetch(PAGE, candles[0]["time"])
        older = [c for c in older if c["time"] < candles[0]["time"]]
        if not older:
            break  # no more history on the exchange
        candles = older + candles
    return candles[-total:]


class HistoryCache:
    def __init__(self, total: int = STRATEGY_CANDLES, clock: Callable[[], float] = time.time,
                 max_charts: int = MAX_CHARTS):
        self.total = total
        self.max_charts = max_charts
        self.clock = clock
        self._charts: dict[tuple, tuple[float, list[dict]]] = {}

    async def get(self, key: tuple, fetch: Fetch) -> list[dict]:
        cached = self._charts.get(key)
        if cached is None:
            candles = await fetch_history(fetch, self.total)
        else:
            # Only the newest page: it overlaps what we have, so nothing is missed
            # unless the app was away for more than 1000 candles (then start over).
            latest = await fetch(PAGE, None)
            old = _unpack(cached[1])
            if latest and old and latest[0]["time"] > old[-1]["time"]:
                candles = await fetch_history(fetch, self.total)
            else:
                candles = merge(old, latest, self.total)
        self._charts[key] = (self.clock(), _pack(candles))
        if len(self._charts) > self.max_charts:
            oldest = min(self._charts, key=lambda k: self._charts[k][0])
            del self._charts[oldest]
        return candles


# Kept as six number arrays (8 bytes a number): about a tenth of the memory of
# dicts, which matters with hundreds of charts (the paper bot keeps 500).
_FIELDS = ("time", "open", "high", "low", "close", "volume")


def _pack(candles: list[dict]) -> tuple:
    return tuple(array("d", (float(c.get(f, 0.0)) for c in candles)) for f in _FIELDS)


def _unpack(columns: tuple) -> list[dict]:
    times = columns[0]
    return [{"time": int(times[i]), "open": columns[1][i], "high": columns[2][i], "low": columns[3][i],
             "close": columns[4][i], "volume": columns[5][i]} for i in range(len(times))]
