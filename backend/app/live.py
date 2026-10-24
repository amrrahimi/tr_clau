"""Live candle updates by asking the exchange repeatedly (polling).

Every few seconds the latest two candles are requested. Two, because when a
new candle starts, the previous one may have received its final price change
since the last request. Only candles that actually changed are passed on.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable

from . import config
from .exchange import MarketService


async def watch_candles(
    service: MarketService,
    symbol: str,
    timeframe: str,
    interval: float = config.POLL_INTERVAL_SECONDS,
    max_failures: int = 5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[dict]:
    """Yield each new or changed candle, forever.

    A single failed request (for example a short network drop) is retried.
    After `max_failures` failures in a row the error is raised, so the caller
    can tell the user instead of silently showing a frozen chart.
    """
    last_sent: dict[int, dict] = {}
    failures = 0
    while True:
        try:
            candles = await service.fetch_candles(symbol, timeframe, limit=2)
            failures = 0
        except Exception:
            failures += 1
            if failures >= max_failures:
                raise
            await sleep(interval)
            continue

        for candle in candles:
            if last_sent.get(candle["time"]) != candle:
                last_sent[candle["time"]] = candle
                yield candle

        # Remember only recent candles so memory does not grow forever.
        for old_time in sorted(last_sent)[:-2]:
            del last_sent[old_time]

        await sleep(interval)
