import unittest

from app.exchange import MarketService
from app.live import watch_candles

from .fake_exchange import FakeExchange, row


async def no_sleep(_seconds):
    return None


async def collect(generator, count):
    items = []
    async for item in generator:
        items.append(item)
        if len(items) == count:
            break
    return items


class WatchCandlesTest(unittest.IsolatedAsyncioTestCase):
    async def test_sends_only_new_or_changed_candles(self):
        answers = [
            [row(60, 10), row(120, 11)],   # first poll: both are new
            [row(60, 10), row(120, 11)],   # nothing changed: nothing sent
            [row(60, 10), row(120, 12)],   # current candle price moved
            [row(120, 12), row(180, 13)],  # a new candle started
        ]
        service = MarketService(FakeExchange(candles=answers), "spot")
        updates = await collect(watch_candles(service, "BTC/USDT", "1m", sleep=no_sleep), 4)
        self.assertEqual([(c["time"], c["close"]) for c in updates],
                         [(60, 10.0), (120, 11.0), (120, 12.0), (180, 13.0)])

    async def test_retries_a_single_failure(self):
        answers = [ConnectionError("drop"), [row(60, 10)]]
        service = MarketService(FakeExchange(candles=answers), "spot")
        updates = await collect(watch_candles(service, "BTC/USDT", "1m", sleep=no_sleep), 1)
        self.assertEqual(updates[0]["time"], 60)

    async def test_gives_up_after_repeated_failures(self):
        answers = [ConnectionError("drop")] * 3
        service = MarketService(FakeExchange(candles=answers), "spot")
        with self.assertRaises(ConnectionError):
            await collect(watch_candles(service, "BTC/USDT", "1m", max_failures=3, sleep=no_sleep), 1)


if __name__ == "__main__":
    unittest.main()
