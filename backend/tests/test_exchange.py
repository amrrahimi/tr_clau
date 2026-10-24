import unittest

from app import config
from app.exchange import MarketDataError, MarketService, candle_to_dict

from .fake_exchange import FakeExchange, row


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TopMarketsTest(unittest.IsolatedAsyncioTestCase):
    async def test_spot_markets_ranked_by_24h_volume(self):
        service = MarketService(FakeExchange(), "spot")
        bases = [m.base for m in await service.top_markets()]
        # Inactive coin and the EUR pair are left out; futures are left out.
        self.assertEqual(bases, ["BTC", "DOGE", "ETH", "WBTC"])

    async def test_volume_from_coin_volume_times_price(self):
        service = MarketService(FakeExchange(), "spot")
        wbtc = [m for m in await service.top_markets() if m.base == "WBTC"][0]
        self.assertEqual(wbtc.volume_24h, 200.0)

    async def test_futures_list_only_has_futures(self):
        service = MarketService(FakeExchange(), "futures")
        symbols = [m.symbol for m in await service.top_markets()]
        self.assertEqual(symbols, ["ETH/USDT:USDT", "BTC/USDT:USDT"])

    async def test_limit(self):
        service = MarketService(FakeExchange(), "spot")
        self.assertEqual(len(await service.top_markets(limit=2)), 2)

    async def test_tickers_reused_until_cache_expires(self):
        clock = Clock()
        exchange = FakeExchange()
        service = MarketService(exchange, "spot", clock=clock)
        await service.top_markets()
        clock.now = config.TICKER_CACHE_SECONDS - 1
        await service.top_markets()
        self.assertEqual(exchange.calls["fetch_tickers"], 1)
        clock.now = config.TICKER_CACHE_SECONDS + 1
        await service.top_markets()
        self.assertEqual(exchange.calls["fetch_tickers"], 2)
        self.assertEqual(exchange.calls["load_markets"], 1)

    async def test_no_markets_of_type_is_an_error(self):
        service = MarketService(FakeExchange(markets={}), "spot")
        with self.assertRaises(MarketDataError):
            await service.top_markets()

    def test_unknown_market_type(self):
        with self.assertRaises(MarketDataError):
            MarketService(FakeExchange(), "options")


class SearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_exact_name_first_then_volume(self):
        service = MarketService(FakeExchange(), "spot")
        bases = [m.base for m in await service.search_markets("btc")]
        self.assertEqual(bases, ["BTC", "WBTC"])

    async def test_empty_query_returns_top_list(self):
        service = MarketService(FakeExchange(), "spot")
        self.assertEqual(len(await service.search_markets("  ")), 4)


class CandlesTest(unittest.IsolatedAsyncioTestCase):
    def test_candle_format_uses_seconds(self):
        candle = candle_to_dict([1_700_000_000_000, 1, 2, 0.5, 1.5, None])
        self.assertEqual(candle, {"time": 1_700_000_000, "open": 1.0, "high": 2.0,
                                  "low": 0.5, "close": 1.5, "volume": 0.0})

    async def test_candles_sorted_oldest_first(self):
        exchange = FakeExchange(candles=[[row(120, 10), row(60, 9)]])
        service = MarketService(exchange, "spot")
        candles = await service.fetch_candles("BTC/USDT", "1m", limit=2)
        self.assertEqual([c["time"] for c in candles], [60, 120])

    async def test_older_candles_before_a_time(self):
        # Asking for 3 one-minute candles before t=600 starts at t=420 (600 - 3*60).
        answer = [row(420, 1), row(480, 2), row(540, 3), row(600, 4)]
        exchange = FakeExchange(candles=[answer])
        service = MarketService(exchange, "spot")
        candles = await service.fetch_candles("BTC/USDT", "1m", limit=3, before=600)
        self.assertEqual(exchange.last_ohlcv_args["since"], 420 * 1000)
        # The end of the window is sent too, just before t=600.
        self.assertEqual(exchange.last_ohlcv_args["params"], {"until": 600 * 1000 - 1})
        # The candle at t=600 is not "before 600", so it is dropped.
        self.assertEqual([c["time"] for c in candles], [420, 480, 540])

    async def test_latest_candles_do_not_send_since(self):
        exchange = FakeExchange(candles=[[row(60, 1)]])
        service = MarketService(exchange, "spot")
        await service.fetch_candles("BTC/USDT", "1m", limit=1)
        self.assertIsNone(exchange.last_ohlcv_args["since"])

    async def test_rejects_unknown_timeframe_symbol_and_limit(self):
        service = MarketService(FakeExchange(), "spot")
        with self.assertRaises(MarketDataError):
            await service.fetch_candles("BTC/USDT", "2m")
        with self.assertRaises(MarketDataError):
            await service.fetch_candles("NOPE/USDT", "1m")
        with self.assertRaises(MarketDataError):
            await service.fetch_candles("BTC/USDT:USDT", "1m")  # futures symbol in spot
        with self.assertRaises(MarketDataError):
            await service.fetch_candles("BTC/USDT", "1m", limit=0)


if __name__ == "__main__":
    unittest.main()
