"""Server tests. They need FastAPI and httpx (requirements-dev.txt);
without them they are skipped instead of failing."""

import json
import unittest

try:
    from fastapi.testclient import TestClient
    from app.server import ALLOWED_ORIGINS, create_app
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False

from app.exchange import MarketService

from .fake_exchange import FakeExchange, row


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ServerTest(unittest.TestCase):
    ORIGIN = {"Origin": "tauri://localhost"}

    def client(self, factory):
        return TestClient(create_app(factory))

    def test_markets_list(self):
        client = self.client(lambda market_type: MarketService(FakeExchange(), market_type))
        response = client.get("/api/markets", params={"market_type": "spot"}, headers=self.ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["markets"][0]["base"], "BTC")

    def test_broken_exchange_library_gives_readable_error(self):
        # The macOS bug: creating the exchange connection crashed while importing.
        def broken(market_type):
            raise ImportError("Symbol not found: _SSL_get0_group_name")

        client = self.client(broken)
        response = client.get("/api/markets", params={"market_type": "spot"}, headers=self.ORIGIN)
        self.assertEqual(response.status_code, 500)
        self.assertIn("SSL_get0_group_name", response.json()["detail"])
        # The permission header must be there, or the app's screen cannot read the message.
        self.assertEqual(response.headers.get("access-control-allow-origin"), "tauri://localhost")
        self.assertIn("tauri://localhost", ALLOWED_ORIGINS)

    def test_analysis_auto_and_manual(self):
        rows = [[i * 60_000, 100 + i, 101 + i, 99 + i, 100 + i, 1] for i in range(300)]
        exchange = FakeExchange(candles=[rows, rows])
        client = self.client(lambda market_type: MarketService(exchange, market_type))
        params = {"symbol": "BTC/USDT", "timeframe": "1m", "trading_mode": "daily"}
        auto = client.get("/api/analysis", params=params)
        self.assertEqual(auto.status_code, 200)
        self.assertTrue(auto.json()["auto"])
        self.assertEqual(exchange.last_ohlcv_args["limit"], 1000)
        mine = json.dumps([{"id": "r", "type": "rsi", "params": {"length": 7}}])
        manual = client.get("/api/analysis", params={**params, "auto": "false", "indicators": mine})
        self.assertFalse(manual.json()["auto"])
        self.assertEqual([i["label"] for i in manual.json()["indicators"]], ["RSI 7"])

    def test_catalog_endpoint(self):
        client = self.client(lambda market_type: MarketService(FakeExchange(), market_type))
        body = client.get("/api/indicators/catalog").json()
        self.assertEqual(len(body["indicators"]), 12)

    def test_analysis_with_indicator_list(self):
        rows = [[i * 60_000, 100 + i, 101 + i, 99 + i, 100 + i, 1] for i in range(300)]
        exchange = FakeExchange(candles=[rows])
        client = self.client(lambda market_type: MarketService(exchange, market_type))
        wanted = [{"id": "e1", "type": "ema", "params": {"length": 9}}, {"id": "s", "type": "stoch"}]
        params = {"symbol": "BTC/USDT", "timeframe": "1m", "auto": "false", "indicators": json.dumps(wanted)}
        body = client.get("/api/analysis", params=params).json()
        self.assertEqual([i["id"] for i in body["indicators"]], ["e1", "s"])
        bad = client.get("/api/analysis", params={**params, "indicators": '[{"type":"nope"}]'})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("unknown indicator", bad.json()["detail"])

    def test_analysis_rejects_bad_settings(self):
        client = self.client(lambda market_type: MarketService(FakeExchange(), market_type))
        bad = json.dumps([{"type": "rsi", "params": {"length": 1}}])
        params = {"symbol": "BTC/USDT", "timeframe": "1m", "auto": "false", "indicators": bad}
        response = client.get("/api/analysis", params=params)
        self.assertEqual(response.status_code, 400)
        self.assertIn("length", response.json()["detail"])
        bad_mode = client.get("/api/analysis", params={"symbol": "BTC/USDT", "timeframe": "1m", "trading_mode": "x"})
        self.assertEqual(bad_mode.status_code, 400)

    def test_candles_and_unknown_market_type(self):
        exchange = FakeExchange(candles=[[row(60, 10), row(120, 11)]])
        client = self.client(lambda market_type: MarketService(exchange, market_type))
        ok = client.get("/api/candles", params={"symbol": "BTC/USDT", "timeframe": "1m"})
        self.assertEqual([c["time"] for c in ok.json()["candles"]], [60, 120])
        bad = client.get("/api/markets", params={"market_type": "options"})
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()
