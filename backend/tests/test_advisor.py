import asyncio
import json
import unittest

from app import advisor


def walk(n=80, start=100.0, step=0.5):
    rows, price = [], start
    for i in range(n):
        o = price
        price = price + (step if i % 5 else -2 * step)
        rows.append({"time": i * 60, "open": o, "high": max(o, price) + 0.2, "low": min(o, price) - 0.2,
                     "close": price, "volume": 10 + i})
    return rows


def gemini_reply(answer: dict) -> str:
    return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]})


class ContextTest(unittest.TestCase):
    def test_summary_sees_an_uptrend(self):
        s = advisor.summarize(walk())
        self.assertEqual(s["trend"], "up")
        self.assertGreater(s["rsi"], 50)
        self.assertIsNone(advisor.summarize(walk(10)))

    def test_nearest_swings(self):
        rows = [{"time": i, "open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 1}
                for i, p in enumerate([10, 12, 15, 12, 10, 8, 5, 8, 10, 11, 10, 9, 10])]
        self.assertEqual(advisor.swings(rows), {"swingHighAbove": 12, "swingLowBelow": 4})   # the nearest ones

    def test_brief_has_the_signal_and_the_context(self):
        c = {"base": "A", "strategy": "donchian", "marketState": "range", "stats": {"trades": 20, "winRate": 30},
             "signal": {"side": "short", "entry": 100.0, "stopLoss": 103.0, "takeProfit": 94.0}}
        b = advisor.brief(c, "1h", {"1h": walk(), "4h": walk()}, {"1h": walk()})
        self.assertEqual((b["side"], b["stopPercent"], b["rewardToRisk"]), ("short", 3.0, 2.0))
        self.assertEqual(set(b["timeframes"]), {"1h", "4h"})
        self.assertIn("1h", b["bitcoin"])
        self.assertEqual(len(b["last30Candles"]), 30)
        self.assertIn('"coin": "A"', advisor.prompt_for(b))


class AskTest(unittest.IsolatedAsyncioTestCase):
    async def test_answer_is_read(self):
        calls = []

        async def post(url, headers, body):
            calls.append((url, headers["x-goog-api-key"]))
            return 200, gemini_reply({"approve": True, "confidence": 72, "reason": "هم‌جهت با روند"})
        verdict = await advisor.ask({"coin": "A"}, ["k1"], post=post)
        self.assertEqual(verdict, {"approve": True, "confidence": 72.0, "reason": "هم‌جهت با روند"})
        self.assertIn("gemini-2.5-flash:generateContent", calls[0][0])

    async def test_next_key_when_the_first_is_out_of_quota(self):
        used = []

        async def post(url, headers, body):
            used.append(headers["x-goog-api-key"])
            if headers["x-goog-api-key"] == "k1":
                return 429, "quota"
            return 200, gemini_reply({"approve": False, "confidence": 40, "reason": "دیر"})
        verdict = await advisor.ask({}, ["k1", "k2"], post=post)
        self.assertEqual((used, verdict["approve"]), (["k1", "k2"], False))

    async def test_unavailable(self):
        async def busy(url, headers, body):
            return 429, "quota"

        async def broken(url, headers, body):
            raise asyncio.TimeoutError()

        async def nonsense(url, headers, body):
            return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "maybe"}]}}]})
        for keys, post in ((["k1", "k2"], busy), (["k1"], broken), (["k1"], nonsense), ([], busy)):
            with self.assertRaises(advisor.AdvisorUnavailable):
                await advisor.ask({}, keys, post=post)

    def test_keys_are_masked_for_the_screen(self):
        self.assertEqual(advisor.masked(["abcdefgh1234"]), ["…1234"])
