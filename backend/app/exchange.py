"""Talking to the exchange: market lists and candles.

This module is the only place that knows about ccxt. The rest of the app
asks MarketService for plain Python data, so the exchange (or a fake one in
tests) can be swapped without touching the server or the analysis code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from . import config


class MarketDataError(Exception):
    """A request the app cannot answer, with a message for the user."""


@dataclass(frozen=True)
class MarketInfo:
    symbol: str        # ccxt symbol, e.g. "BTC/USDT" or "BTC/USDT:USDT"
    base: str          # coin name, e.g. "BTC"
    quote: str         # pricing currency, e.g. "USDT"
    volume_24h: float  # 24h traded volume, measured in the quote currency
    last_price: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "base": self.base,
            "quote": self.quote,
            "volume24h": self.volume_24h,
            "lastPrice": self.last_price,
        }


def create_exchange(market_type: str):
    """Create a ccxt client for the configured exchange and market type.

    ccxt is imported here, not at the top, so the rest of this module can be
    tested on a computer that does not have ccxt installed.
    """
    import ccxt.async_support as ccxt_async

    exchange_class = getattr(ccxt_async, config.EXCHANGE_ID)
    return exchange_class({
        "enableRateLimit": True,  # ccxt waits between requests to respect exchange limits
        "options": {"defaultType": config.MARKET_TYPES[market_type]},
    })


def candle_to_dict(row: list) -> dict[str, float]:
    """Convert one ccxt candle into the shape the chart expects.

    ccxt returns [timestamp_ms, open, high, low, close, volume].
    The chart library uses time in seconds, so milliseconds are divided by 1000.
    """
    timestamp_ms, open_, high, low, close, volume = row[:6]
    return {
        "time": int(timestamp_ms // 1000),
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume or 0.0),
    }


def _ticker_volume(ticker: dict | None) -> float:
    """24h volume in the quote currency.

    Some exchanges only report volume in coins (baseVolume); in that case it
    is multiplied by the last price so every coin is measured in USDT.
    """
    if not ticker:
        return 0.0
    if ticker.get("quoteVolume"):
        return float(ticker["quoteVolume"])
    base_volume = ticker.get("baseVolume") or 0.0
    last = ticker.get("last") or 0.0
    return float(base_volume) * float(last)


class MarketService:
    """Market list and candles for one market type (spot or futures)."""

    def __init__(self, exchange, market_type: str, clock: Callable[[], float] = time.monotonic):
        if market_type not in config.MARKET_TYPES:
            raise MarketDataError(f"Unknown market type: {market_type}")
        self.exchange = exchange
        self.market_type = market_type
        self._ccxt_type = config.MARKET_TYPES[market_type]
        self._clock = clock
        self._markets: dict[str, dict] | None = None
        self._tickers: dict[str, dict] = {}
        self._tickers_time: float | None = None

    async def _load_markets(self) -> dict[str, dict]:
        """Markets of the chosen type, priced in USDT, that are open for trading."""
        if self._markets is None:
            all_markets = await self.exchange.load_markets()
            self._markets = {
                symbol: market
                for symbol, market in all_markets.items()
                if market.get("type") == self._ccxt_type
                and market.get("quote") == config.QUOTE_CURRENCY
                and market.get("active") is not False
            }
            if not self._markets:
                raise MarketDataError(
                    f"No {self.market_type} markets priced in {config.QUOTE_CURRENCY} were found on this exchange."
                )
        return self._markets

    async def _load_tickers(self) -> dict[str, dict]:
        """Latest 24h statistics, reused for a short time to save requests."""
        now = self._clock()
        expired = self._tickers_time is None or now - self._tickers_time >= config.TICKER_CACHE_SECONDS
        if expired:
            markets = await self._load_markets()
            tickers = await self.exchange.fetch_tickers(list(markets))
            self._tickers = tickers or {}
            self._tickers_time = now
        return self._tickers

    async def _market_infos(self) -> list[MarketInfo]:
        markets = await self._load_markets()
        tickers = await self._load_tickers()
        infos = []
        for symbol, market in markets.items():
            ticker = tickers.get(symbol)
            infos.append(MarketInfo(
                symbol=symbol,
                base=market.get("base", symbol),
                quote=market.get("quote", config.QUOTE_CURRENCY),
                volume_24h=_ticker_volume(ticker),
                last_price=(ticker or {}).get("last"),
            ))
        infos.sort(key=lambda info: info.volume_24h, reverse=True)
        return infos

    async def top_markets(self, limit: int = config.TOP_MARKETS_LIMIT) -> list[MarketInfo]:
        """The coins with the highest 24h volume, highest first."""
        return (await self._market_infos())[:limit]

    async def search_markets(self, query: str, limit: int = 100) -> list[MarketInfo]:
        """Coins whose name contains the query (case-insensitive), highest volume first."""
        text = query.strip().upper()
        if not text:
            return await self.top_markets()
        matches = [info for info in await self._market_infos() if text in info.base.upper()]
        # Exact name first (searching "BTC" shows BTC before WBTC), then by volume.
        matches.sort(key=lambda info: (info.base.upper() != text, -info.volume_24h))
        return matches[:limit]

    async def ensure_symbol(self, symbol: str) -> None:
        markets = await self._load_markets()
        if symbol not in markets:
            raise MarketDataError(f"{symbol} is not an available {self.market_type} market.")

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = config.DEFAULT_CANDLE_LIMIT,
        before: int | None = None,
    ) -> list[dict]:
        """Past candles, oldest first, in the chart's format.

        Without `before`: the most recent candles.
        With `before` (a time in seconds): the candles that come just before
        that time. The chart uses this when you scroll into the past.
        """
        if timeframe not in config.ALL_TIMEFRAMES:
            raise MarketDataError(f"Unsupported timeframe: {timeframe}")
        if not 1 <= limit <= config.MAX_CANDLE_LIMIT:
            raise MarketDataError(f"Candle limit must be between 1 and {config.MAX_CANDLE_LIMIT}.")
        await self.ensure_symbol(symbol)

        if before is None:
            rows = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        else:
            # Exchanges return candles starting *from* a time, so start
            # `limit` candles earlier and keep only those before `before`.
            since_seconds = before - limit * config.TIMEFRAME_SECONDS[timeframe]
            rows = await self.exchange.fetch_ohlcv(symbol, timeframe, since=since_seconds * 1000, limit=limit)

        candles = [candle_to_dict(row) for row in rows]
        if before is not None:
            candles = [candle for candle in candles if candle["time"] < before]
        candles.sort(key=lambda candle: candle["time"])
        return candles

    async def close(self) -> None:
        close = getattr(self.exchange, "close", None)
        if close is not None:
            await close()
