"""The owner's real account (2026-11-09): read / shadow / real with safety rules, on a fake exchange."""

import asyncio
import json
import unittest

from app import account as acc
from app import connection


class FakeExchange:
    def __init__(self, fail_protect=False, free=1000.0):
        self.has = {"fetchPositions": True, "fetchOpenOrders": True, "setLeverage": True, "createOrder": True,
                    "cancelAllOrders": True}
        self.orders = []
        self.cancelled = []
        self.positions = []
        self.fail_protect = fail_protect
        self.free = free
        self.leverage = None

    async def fetch_balance(self):
        return {"USDT": {"total": 1000.0, "free": self.free, "used": 0.0}}

    async def fetch_positions(self, symbols=None):
        return list(self.positions)

    async def fetch_open_orders(self):
        return []

    async def load_markets(self):
        return {}

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.3f}"

    def price_to_precision(self, symbol, price):
        return f"{price:.4f}"

    async def set_leverage(self, lev, symbol):
        self.leverage = lev

    def market(self, symbol):
        return {"id": symbol.split("/")[0] + "-SWAP-USDT", "contractSize": 0.1}

    async def privatePostApiV1FuturesOrder(self, body):
        self.orders.append(("order", body))
        self.positions = [{"symbol": "SOL/USDT:USDT", "side": "long" if body["side"] == "BUY_OPEN" else "short",
                           "contracts": float(body["quantity"])}]
        return {"orderId": "1"}

    async def privatePostApiV1FuturesPositionTradingStop(self, body):
        if self.fail_protect:
            raise RuntimeError("not supported")
        self.orders.append(("stops", body))
        return {"code": 200}

    async def privatePostApiV1FuturesFlashClose(self, body):
        self.orders.append(("close", body))
        self.positions = []
        return {"code": 200}

    async def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)

    async def cancel_all_orders(self):
        self.cancelled.append("all")

    async def close(self):
        pass


def position(**kw):
    p = {"id": 7, "symbol": "SOL/USDT:USDT", "base": "SOL", "timeframe": "15m", "side": "long", "entryPrice": 100.0,
         "stop": 98.0, "takeProfit": 104.0, "leverage": 10}
    p.update(kw)
    return p


class AccountTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path = connection.settings_path()
        settings = connection.load_settings(path)
        settings.pop("exchangeAccount", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings), encoding="utf-8")
        self.ex = FakeExchange()
        self.sent = []
        self.a = acc.ExchangeAccount(factory=lambda k, s: self.ex, clock=lambda: 1_000_000.0,
                                     notify=lambda text, buttons=None: self.sent.append((text, buttons)))
        self.a.set(key="KEY1234", secret="SECRETXYZ")

    def test_secrets_never_shown_and_real_needs_agreement(self):
        shown = json.dumps(self.a.public())
        self.assertNotIn("SECRETXYZ", shown)
        self.assertNotIn("KEY1234", shown)
        self.assertTrue(self.a.public()["key"])
        with self.assertRaises(acc.AccountError):
            self.a.set(mode="real")
        with self.assertRaises(acc.AccountError):
            self.a.set(limits={"maxLeverage": 50})
        self.a.set(mode="real", agree_real=True)
        self.assertEqual(self.a.public()["mode"], "real")

    async def test_read_only_sends_nothing(self):
        self.a.set(mode="read")
        await self.a.refresh()
        await self.a.on_open(position())
        self.assertEqual(self.ex.orders, [])
        self.assertEqual(self.a.public()["snapshot"]["total"], 1000.0)

    async def test_shadow_plans_inside_caps(self):
        self.a.set(mode="shadow", limits={"maxMargin": 10, "maxLeverage": 5})
        await self.a.on_open(position())
        plan = self.a.plans[-1]
        self.assertEqual(plan["status"], "shadow")
        self.assertEqual(plan["leverage"], 5)                      # capped
        self.assertAlmostEqual(plan["margin"], 10.0)                # 1% of 1000 / 2 = 5 units = $500 / 5x -> capped at $10
        self.assertEqual(self.ex.orders, [])

    async def test_real_opens_with_exchange_side_stop_and_target(self):
        self.a.set(mode="real", agree_real=True, confirm=False, limits={"maxMargin": 1000, "maxLeverage": 10})
        await self.a.on_open(position())
        (k1, entry), (k2, stops) = self.ex.orders[:2]
        self.assertEqual((k1, entry["side"], entry["priceType"], entry["symbol"]), ("order", "BUY_OPEN", "MARKET", "SOL-SWAP-USDT"))
        self.assertEqual(entry["quantity"], "50.0")                 # $10 risk / $2 = 5 SOL = 50 contracts of 0.1
        self.assertEqual((k2, stops["side"], stops["stopLoss"], stops["takeProfit"]), ("stops", "LONG", "98.0000", "104.0000"))
        self.assertEqual(self.a.plans[-1]["status"], "open")
        # stop moved by the paper bot -> moved on the exchange
        await self.a.on_levels(position(stop=100.5))
        self.assertEqual(self.ex.orders[-1][1]["stopLoss"], "100.5000")
        # paper closed -> real closed
        await self.a.on_close(position(), "review")
        self.assertEqual(self.ex.orders[-1], ("close", {"symbol": "SOL-SWAP-USDT", "side": "LONG"}))
        self.assertEqual(self.ex.positions, [])

    async def test_no_protection_closes_at_once_and_stops(self):
        self.ex.fail_protect = True
        self.a.set(mode="real", agree_real=True, confirm=False, limits={"maxMargin": 1000, "maxLeverage": 10})
        await self.a.on_open(position())
        self.assertEqual(self.ex.orders[-1][0], "close")             # closed at once
        self.assertEqual(self.a.halted, "protection failed")
        await self.a.on_open(position(id=8))
        self.assertTrue(self.a.plans[-1]["status"].startswith("skip: stopped"))

    async def test_confirmation_on_telegram(self):
        self.a.set(mode="real", agree_real=True, confirm=True, limits={"maxMargin": 1000})
        await self.a.on_open(position())
        self.assertEqual(self.ex.orders, [])
        self.assertEqual(self.sent[-1][1], [("باز کن", "rok:7"), ("نه", "rno:7")])
        self.assertEqual(await self.a.answer(7, False, True), "باز نشد.")
        await self.a.on_open(position())
        self.assertEqual(await self.a.answer(7, True, True), "باز شد.")
        self.assertEqual([o[0] for o in self.ex.orders], ["order", "stops"])

    async def test_daily_loss_and_panic(self):
        self.a.set(mode="real", agree_real=True, confirm=False, limits={"dailyLoss": 5})
        await self.a.refresh()
        self.ex.positions = [{"symbol": "X/USDT:USDT", "side": "long", "contracts": 2, "unrealizedPnl": -6}]
        await self.a.refresh()
        self.assertTrue(self.a.halted.startswith("daily"))
        message = await self.a.panic()
        self.assertIn("1 پوزیشن", message)
        self.assertIn("all", self.ex.cancelled)
        self.assertEqual(self.a.public()["mode"], "read")

    async def test_not_enough_margin_skips(self):
        self.ex.free = 1.0
        self.a.set(mode="real", agree_real=True, confirm=False, limits={"maxMargin": 50})
        await self.a.on_open(position())
        self.assertEqual(self.a.plans[-1]["status"], "skip: not enough free margin")
        self.assertEqual(self.ex.orders, [])


if __name__ == "__main__":
    unittest.main()
