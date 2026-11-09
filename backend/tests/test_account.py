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

    async def create_order(self, symbol, type_, side, amount, price=None, params=None):
        params = params or {}
        if self.fail_protect and ("stopLossPrice" in params or "takeProfitPrice" in params):
            raise RuntimeError("not supported")
        self.orders.append((symbol, type_, side, amount, params))
        if not params:
            self.positions = [{"symbol": symbol, "side": "long" if side == "buy" else "short", "contracts": amount}]
        elif params.get("reduceOnly") and not ("stopLossPrice" in params or "takeProfitPrice" in params):
            self.positions = []
        return {"id": f"o{len(self.orders)}"}

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
        kinds = [o[4] for o in self.ex.orders]
        self.assertEqual(kinds[0], {})                              # market entry
        self.assertEqual(kinds[1], {"reduceOnly": True, "stopLossPrice": 98.0})
        self.assertEqual(kinds[2], {"reduceOnly": True, "takeProfitPrice": 104.0})
        self.assertEqual(self.ex.orders[0][3], 5.0)                 # $10 risk / $2 distance
        self.assertEqual(self.a.plans[-1]["status"], "open")
        # stop moved by the paper bot -> new stop on the exchange, old one cancelled
        await self.a.on_levels(position(stop=100.5))
        self.assertEqual(self.ex.orders[3][4]["stopLossPrice"], 100.5)
        self.assertIn("o2", self.ex.cancelled)
        # paper closed -> real closed
        await self.a.on_close(position(), "review")
        self.assertEqual(self.ex.orders[-1][4], {"reduceOnly": True})
        self.assertEqual(self.ex.positions, [])

    async def test_no_protection_closes_at_once_and_stops(self):
        self.ex.fail_protect = True
        self.a.set(mode="real", agree_real=True, confirm=False, limits={"maxMargin": 1000, "maxLeverage": 10})
        await self.a.on_open(position())
        self.assertEqual(self.ex.orders[-1][4], {"reduceOnly": True})   # closed
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
        self.assertEqual(len(self.ex.orders), 3)

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
