"""A pretend exchange for tests: same methods as ccxt, fixed answers, no internet."""


class FakeExchange:
    def __init__(self, markets=None, tickers=None, candles=None):
        self.markets = markets if markets is not None else default_markets()
        self.tickers = tickers if tickers is not None else default_tickers()
        # candles: list of answers; each fetch_ohlcv call returns the next one.
        self.candle_answers = list(candles or [])
        self.calls = {"load_markets": 0, "fetch_tickers": 0, "fetch_ohlcv": 0}
        self.closed = False

    async def load_markets(self):
        self.calls["load_markets"] += 1
        return self.markets

    async def fetch_tickers(self, symbols=None):
        self.calls["fetch_tickers"] += 1
        return {s: t for s, t in self.tickers.items() if symbols is None or s in symbols}

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls["fetch_ohlcv"] += 1
        self.last_ohlcv_args = {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        answer = self.candle_answers.pop(0) if self.candle_answers else []
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        self.closed = True


def market(symbol, base, type_="spot", quote="USDT", active=True):
    return {"symbol": symbol, "base": base, "quote": quote, "type": type_, "active": active}


def default_markets():
    return {
        "BTC/USDT": market("BTC/USDT", "BTC"),
        "ETH/USDT": market("ETH/USDT", "ETH"),
        "WBTC/USDT": market("WBTC/USDT", "WBTC"),
        "DOGE/USDT": market("DOGE/USDT", "DOGE"),
        "OLD/USDT": market("OLD/USDT", "OLD", active=False),
        "BTC/EUR": market("BTC/EUR", "BTC", quote="EUR"),
        "BTC/USDT:USDT": market("BTC/USDT:USDT", "BTC", type_="swap"),
        "ETH/USDT:USDT": market("ETH/USDT:USDT", "ETH", type_="swap"),
    }


def default_tickers():
    return {
        "BTC/USDT": {"quoteVolume": 900.0, "last": 60000.0},
        "ETH/USDT": {"quoteVolume": 500.0, "last": 3000.0},
        # Only coin volume reported: 2 coins * 100 = 200 USDT.
        "WBTC/USDT": {"quoteVolume": None, "baseVolume": 2.0, "last": 100.0},
        "DOGE/USDT": {"quoteVolume": 700.0, "last": 0.1},
        "BTC/USDT:USDT": {"quoteVolume": 100.0, "last": 60010.0},
        "ETH/USDT:USDT": {"quoteVolume": 300.0, "last": 3001.0},
    }


def row(time_s, close, volume=1.0):
    """A ccxt candle row: [ms, open, high, low, close, volume]."""
    return [time_s * 1000, close - 1, close + 1, close - 2, close, volume]
