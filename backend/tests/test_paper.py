import asyncio
import tempfile
import unittest
from pathlib import Path

from app import paper as pp
from app.strategies import LONG, SHORT, Fees

FEES = Fees(maker=0.02, taker=0.06)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


class SizeTest(unittest.TestCase):
    def test_one_percent_risk_with_fees(self):
        s = pp.position_size(LONG, 100, 99, 100, 100, FEES)       # stop 1% away
        self.assertAlmostEqual(s.risk, 1.0)                         # 1% of 100 USDT, fees included
        self.assertAlmostEqual(s.notional, 1 / 0.0112)
        self.assertEqual(s.leverage, 3)                             # 89 USDT in a 33 USDT slot
        self.assertLess(s.liquidation, 99)                          # liquidation beyond the stop

    def test_tight_stop_needs_more_leverage_but_never_more_than_ten(self):
        s = pp.position_size(LONG, 100, 99.8, 100, 100, FEES)     # 0.2%
        self.assertEqual(s.leverage, 10)
        self.assertAlmostEqual(s.risk, 1.0)
        s = pp.position_size(LONG, 100, 99.9, 100, 100, FEES)     # 0.1%: does not fit
        self.assertEqual(s.leverage, 10)
        self.assertAlmostEqual(s.notional, 100 / 3 * 10)
        self.assertLess(s.risk, 1.0)                               # smaller position, less risk, never more

    def test_wide_stop_lowers_leverage_for_liquidation(self):
        s = pp.position_size(SHORT, 100, 115, 100, 100, FEES)     # 15% stop: 1x is enough anyway
        self.assertEqual(s.leverage, 1)
        self.assertGreater(s.liquidation, 115)
        self.assertEqual(pp.liquidation_price(LONG, 100, 10), 100 * (1 - 0.1 + pp.MAINTENANCE))

    def test_no_money_no_position(self):
        self.assertIsNone(pp.position_size(LONG, 100, 99, 100, 0, FEES))
        self.assertIsNone(pp.position_size(LONG, 100, 100, 100, 100, FEES))

    def test_pnl_includes_both_fees(self):
        p = {"side": LONG, "quantity": 2, "entryPrice": 100, "entryFee": 200 * 0.0006}
        result, fees = pp.pnl(p, 101, 0.02)
        self.assertAlmostEqual(fees, 0.12 + 202 * 0.0002)
        self.assertAlmostEqual(result, 2 - fees)


def position(**over):
    p = {"id": 1, "side": LONG, "entryPrice": 100, "stop": 99, "stopLoss": 99, "takeProfit": 102,
         "entryCandle": 0, "checkedFrom": 0, "breakevenPart": 0.5,
         "breakevenPrice": 100.2, "breakevenAt": None}
    p.update(over)
    return p


class ExitTest(unittest.TestCase):
    def test_entry_candle_range_is_ignored_live_price_counts(self):
        p = position()
        candles = [bar(0, 100, 105, 95, 100)]                     # entry candle, still forming
        self.assertIsNone(pp.check_exit(p, candles, 100.5, 60, now=30))
        self.assertEqual(pp.check_exit(p, candles, 98.9, 60, now=30), (99, "stop"))

    def test_break_even_then_exit_at_break_even_price(self):
        p = position()
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 101.2, 99.5, 101), bar(120, 101, 101, 100.1, 100.5)]
        self.assertIsNone(pp.check_exit(p, candles, 100.5, 60, now=170))
        self.assertEqual(p["stop"], 100.2)                          # moved after the closed candle at 60
        candles.append(bar(180, 100.5, 100.6, 100.0, 100.1))
        self.assertEqual(pp.check_exit(p, candles, 100.1, 60, now=245), (100.2, "breakeven"))

    def test_both_in_one_candle_is_the_stop_and_target_counts(self):
        p = position(breakevenPart=0)
        both = [bar(0, 100, 100, 100, 100), bar(60, 100, 102.5, 98.5, 100)]
        self.assertEqual(pp.check_exit(p, both, 100, 60, now=125), (99, "stop"))
        p = position(breakevenPart=0)
        win = [bar(0, 100, 100, 100, 100), bar(60, 100, 102.5, 99.5, 102)]
        self.assertEqual(pp.check_exit(p, win, 102, 60, now=125), (102, "target"))

    def test_short(self):
        p = position(side=SHORT, stop=101, stopLoss=101, takeProfit=98, breakevenPart=0)
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 100.5, 97.9, 98)]
        self.assertEqual(pp.check_exit(p, candles, 98, 60, now=125), (98, "target"))


def cand(base, pf, trades, side=LONG):
    return {"symbol": f"{base}/USDT:USDT", "base": base, "strategy": "ema_cross", "marketState": "trend_up",
            "stats": {"profitFactor": pf, "trades": trades, "winRate": 50, "netPercent": 5},
            "signal": {"side": side, "time": 0, "entry": 100, "stopLoss": 99 if side == LONG else 101,
                       "takeProfit": 102 if side == LONG else 98, "confirmedAt": 60}}


class PickTest(unittest.TestCase):
    def test_best_first_one_per_coin_and_free_slots_only(self):
        cs = [cand("A", 1.5, 20), cand("B", 3.0, 12), cand("B", 2.0, 40), cand("C", None, 11), cand("D", 1.2, 50)]
        self.assertEqual([c["base"] for c in pp.pick(cs, set(), 3)], ["C", "B", "A"])
        self.assertEqual([c["base"] for c in pp.pick(cs, {"C/USDT:USDT"}, 2)], ["B", "A"])


class BotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "paper.json"
        self.clock = [1_000_000.0]
        self.recent_rows = {"A/USDT:USDT": [bar(999_960, 100, 100, 100, 100)]}

        async def coins():
            return [("A/USDT:USDT", "A")]

        async def history(symbol, tf):
            return []

        async def recent(symbol, tf):
            return self.recent_rows.get(symbol, [])

        self.bot = pp.PaperBot(pp.Store(self.path), coins, history, recent, now=lambda: self.clock[0], fees=FEES)

    def tearDown(self):
        self.dir.cleanup()

    async def test_open_size_and_close_at_target(self):
        bot = self.bot
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        p = bot.account["positions"][0]
        self.assertEqual((p["side"], p["leverage"], p["entryPrice"]), (LONG, 3, 100))
        self.assertAlmostEqual(p["risk"], 1.0)
        # Next candle reaches the take-profit.
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100), bar(1_000_020, 100, 102.5, 99.5, 102)]
        self.clock[0] = 1_000_090
        await bot._watch_positions(self.clock[0])
        self.assertEqual(bot.account["positions"], [])
        trade = bot.account["closed"][0]
        self.assertEqual((trade["exitReason"], trade["exitPrice"]), ("target", 102))
        self.assertGreater(bot.account["balance"], 101.5)           # about +2% of 89 USDT, minus fees
        self.assertEqual(bot.public()["stats"]["trades"], 1)

    async def test_price_past_the_stop_or_target_is_not_entered(self):
        bot = self.bot
        bot.reset(100)
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 98.9, 98.9)]
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(bot.account["positions"], [])

    async def test_account_is_saved_and_loaded(self):
        self.bot.reset(80)
        self.bot.start()
        again = pp.PaperBot(pp.Store(self.path), None, None, None, now=lambda: self.clock[0], fees=FEES)
        self.assertEqual((again.account["capital"], again.account["status"]), (80, "running"))

    async def test_each_timeframe_scanned_once_per_candle_and_daily_stop(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        scanned = []

        async def fake_scan(tf, now):
            scanned.append(tf)
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual(scanned, pp.TIMEFRAMES)
        await bot.step()
        self.assertEqual(scanned, pp.TIMEFRAMES)                     # same candles: no new scan
        self.clock[0] += 60
        await bot.step()
        self.assertIn("1m", scanned[5:])
        # A 5% loss today: no more scans until tomorrow.
        bot.account["balance"] = 94
        self.clock[0] += 3600
        scanned.clear()
        await bot.step()
        self.assertEqual(scanned, [])
        self.assertTrue(bot.public()["pausedToday"])

    async def test_thirty_percent_loss_switches_the_bot_off(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        bot.account["balance"] = 69
        await bot.step()
        self.assertEqual(bot.account["status"], "halted")
        bot.start()
        self.assertEqual(bot.account["status"], "halted")             # stays off until a reset
        bot.reset(100)
        self.assertEqual(bot.account["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
