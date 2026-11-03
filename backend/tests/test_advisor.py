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
        self.assertIn(f"{advisor.MODEL}:generateContent", calls[0][0])

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


class TestKeysTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_key_is_tried(self):
        async def post(url, headers, body):
            if headers["x-goog-api-key"] == "good-key-1111":
                return 200, gemini_reply({"text": "OK"})
            if headers["x-goog-api-key"] == "bad-key-2222":
                return 400, json.dumps({"error": {"message": "API key not valid"}})
            raise ConnectionError("proxy refused")
        results = await advisor.test_keys(["good-key-1111", "bad-key-2222", "net-key-3333"], post=post)
        self.assertEqual([r["ok"] for r in results], [True, False, False])
        self.assertEqual([r["key"] for r in results], ["…1111", "…2222", "…3333"])
        self.assertEqual(results[1]["error"], f"HTTP 400 ({advisor.MODEL}): API key not valid")
        self.assertIn("proxy refused", results[2]["error"])
        self.assertEqual(await advisor.test_keys([]), [])


class SslTest(unittest.TestCase):
    def test_certificates_come_with_the_app(self):
        import ssl
        context = advisor.ssl_context()
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)     # still checked, never switched off
        self.assertGreater(len(context.get_ca_certs()), 50)          # certifi's list was loaded


class ModelTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_retired_model_moves_on_to_the_next(self):
        tried = []

        async def post(url, headers, body):
            name = url.split("/models/")[1].split(":")[0]
            tried.append(name)
            if name == advisor.MODELS[0]:
                return 404, json.dumps({"error": {"message": "no longer available to new users"}})
            if name == advisor.MODELS[1]:
                return 429, json.dumps({"error": {"message": "Quota exceeded, limit: 0"}})
            return 200, gemini_reply({"approve": True, "confidence": 60, "reason": "ok"})
        used = []
        answer = await advisor._call({}, ["k1", "k2"], advisor.MODELS[0], post, used.append)
        self.assertEqual(used, [advisor.MODELS[2]])
        self.assertEqual(tried, [advisor.MODELS[0]] * 2 + [advisor.MODELS[1]] * 2 + [advisor.MODELS[2]])
        self.assertIn("approve", answer)
        results = await advisor.test_keys(["k1"], advisor.MODELS[0], post=post)
        self.assertEqual((results[0]["ok"], results[0]["model"]), (True, advisor.MODELS[2]))

    async def test_busy_keys_do_not_switch_the_model(self):
        tried = []

        async def post(url, headers, body):
            tried.append(url)
            return 429, json.dumps({"error": {"message": "Resource exhausted, retry in 20s"}})
        with self.assertRaises(advisor.AdvisorUnavailable):
            await advisor._call({}, ["k1", "k2"], advisor.MODELS[0], post, None)
        self.assertEqual(len(tried), 2)        # both keys of the first model, then stop

    def test_model_order(self):
        self.assertEqual(advisor.model_order(advisor.MODELS[2])[0], advisor.MODELS[2])
        self.assertEqual(sorted(advisor.model_order(advisor.MODELS[2])), sorted(advisor.MODELS))
