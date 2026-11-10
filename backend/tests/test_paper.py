import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app import paper as pp
from app import telegram as tg
from app.strategies import LONG, SHORT, Fees

FEES = Fees(maker=0.02, taker=0.06)


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


class SizeTest(unittest.TestCase):
    def test_one_percent_risk_with_fees(self):
        s = pp.position_size(LONG, 100, 99, 100, 100, FEES)       # stop 1% away
        self.assertAlmostEqual(s.risk, 1.0)                         # 1% of 100 USDT, fees included
        self.assertAlmostEqual(s.notional, 1 / 0.0112)
        self.assertEqual(s.leverage, 6)                             # 89 USDT in a 16.7 USDT slot (6 places)
        self.assertLess(s.liquidation, 99)                          # liquidation beyond the stop

    def test_tight_stop_needs_more_leverage_but_never_more_than_ten(self):
        s = pp.position_size(LONG, 100, 99.5, 100, 100, FEES)     # 0.5%: needs 10x in a sixth of the account
        self.assertEqual(s.leverage, 10)
        self.assertAlmostEqual(s.risk, 1.0)
        s = pp.position_size(LONG, 100, 99.9, 100, 100, FEES)     # 0.1%: does not fit
        self.assertEqual(s.leverage, 10)
        self.assertAlmostEqual(s.notional, 100 / pp.MAX_OPEN * 10)
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
        # The live price already passed the stop: the exit is at that price (slippage), not at 99.
        self.assertEqual(pp.check_exit(p, candles, 98.9, 60, now=30), (98.9, "stop"))

    def test_candle_that_opens_past_the_stop_exits_at_its_open(self):
        p = position(breakevenPart=0)
        gap = [bar(0, 100, 100, 100, 100), bar(60, 98.5, 99.2, 98.0, 98.8)]
        self.assertEqual(pp.check_exit(p, gap, 98.8, 60, now=125), (98.5, "stop"))
        p = position(side=SHORT, stop=101, stopLoss=101, takeProfit=98, breakevenPart=0)
        gap = [bar(0, 100, 100, 100, 100), bar(60, 101.6, 101.9, 101.0, 101.2)]
        self.assertEqual(pp.check_exit(p, gap, 101.2, 60, now=125), (101.6, "stop"))
        # Touched inside the candle (opened before the stop): the stop price.
        p = position(breakevenPart=0)
        touch = [bar(0, 100, 100, 100, 100), bar(60, 99.5, 99.6, 98.7, 99.3)]
        self.assertEqual(pp.check_exit(p, touch, 99.3, 60, now=125), (99, "stop"))

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


class SlotsTest(unittest.TestCase):
    def test_no_limit_on_open_positions(self):
        # Owner 2026-11-02: no limit per group or per direction (only one per coin and the free money).
        positions = [{"timeframe": "1m", "side": LONG}, {"timeframe": "5m", "side": LONG}, {"timeframe": "3m", "side": SHORT}]
        self.assertGreater(pp.free_slots(positions, "1m"), 100)
        self.assertGreater(pp.free_slots(positions, "1h"), 100)
        self.assertGreater(pp.side_room(positions)["long"], 100)
        cs = [cand(c, 3.0 - i * 0.1, 20) for i, c in enumerate("ABCDEFGHIJ")]
        self.assertEqual(len(pp.pick(cs, set(), pp.free_slots([], "1h"), pp.side_room([]))), 10)
        # The old limits still work as numbers, if they come back.
        three = [{"timeframe": "1m", "side": LONG}] * 3
        self.assertEqual(pp.free_slots(three, "1m", {"fast": 3, "slow": 3}), 0)

    def test_at_most_four_in_one_direction(self):
        cs = [cand(c, 3.0 - i * 0.1, 20) for i, c in enumerate("ABCDEF")]
        chosen = pp.pick(cs, set(), 6, {"long": 4, "short": 4})
        self.assertEqual([c["base"] for c in chosen], ["A", "B", "C", "D"])
        mixed = cs[:3] + [cand("S", 1.1, 20, SHORT)]
        self.assertEqual([c["base"] for c in pp.pick(mixed, set(), 3, {"long": 1, "short": 4})], ["A", "S"])


class ProfitLockTest(unittest.TestCase):
    """Owner's example: entry 100, stop 98, target 110; at 80% (108) the stop moves to 40% (104)."""
    def pos(self, **over):
        return position(**{"stop": 98, "stopLoss": 98, "takeProfit": 110, "breakevenPart": 0,
                           "lock": {"trigger": 0.8, "at": 0.4}, **over})

    def test_reaching_80_percent_moves_the_stop_to_40_percent_and_a_return_exits_there(self):
        p = self.pos()
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 108.2, 99.5, 107)]
        self.assertIsNone(pp.check_exit(p, candles, 107, 60, now=125))
        self.assertEqual((p["stop"], p["lockedAt"]), (104, 60))
        candles.append(bar(120, 107, 107.5, 103, 103.5))           # back down: exits at 104 with a profit
        self.assertEqual(pp.check_exit(p, candles, 103.5, 60, now=185), (104, "lock"))

    def test_straight_to_the_target_keeps_the_full_profit(self):
        p = self.pos()
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 108.5, 99.8, 108), bar(120, 108, 110.5, 107, 110)]
        self.assertEqual(pp.check_exit(p, candles, 110, 60, now=185), (110, "target"))

    def test_below_80_percent_nothing_changes_and_the_live_price_can_lock(self):
        p = self.pos()
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 107.9, 99.5, 107)]
        self.assertIsNone(pp.check_exit(p, candles, 107.5, 60, now=125))
        self.assertEqual(p["stop"], 98)
        self.assertIsNone(pp.check_exit(p, candles, 108.1, 60, now=126))   # the price seen now: 81%
        self.assertEqual(p["stop"], 104)

    def test_never_pulls_a_better_stop_back_and_short_side(self):
        p = self.pos(stop=105)                                          # the owner already locked more
        pp._maybe_lock(p, 109, 1)
        self.assertEqual(p["stop"], 105)
        s = position(side=SHORT, stop=102, stopLoss=102, takeProfit=90, breakevenPart=0, lock={"trigger": 0.8, "at": 0.4})
        pp._maybe_lock(s, 91.9, 1)                                      # 81% of the way down
        self.assertEqual(s["stop"], 96)

    def test_off_means_as_before(self):
        p = self.pos()
        p.pop("lock")
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 109, 99.5, 107), bar(120, 107, 107, 97.5, 98)]
        self.assertEqual(pp.check_exit(p, candles, 98, 60, now=185), (98, "stop"))


class BotTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # These tests are about the loop, not the bot's strategy list: every strategy on every timeframe.
        from unittest import mock
        every = tuple(pp.STRATEGIES)
        for name, value in (("BOT_STRATEGIES_BY_TF", {tf: every for tf in pp.TIMEFRAMES}), ("BOT_STRATEGIES", every)):
            patcher = mock.patch.object(pp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
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
        self.assertEqual((p["side"], p["leverage"], p["entryPrice"]), (LONG, 6, 100))
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
        self.assertEqual(bot.account["events"][-1]["reason"], "past")

    async def test_stale_signal_is_skipped_with_reason(self):
        bot = self.bot
        bot.reset(100)
        # Signal at 100 with the stop at 99: 100.15 is more than 10% of the stop distance away (owner 2026-11-07).
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.15, 100, 100.15)]
        await bot._open(cand("A", 2.0, 20), "15m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(bot.account["positions"], [])
        self.assertEqual((bot.account["events"][-1]["kind"], bot.account["events"][-1]["reason"]), ("skip", "stale"))
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.08, 100, 100.08)]   # within 10%: taken
        await bot._open(cand("A", 2.0, 20), "15m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(len(bot.account["positions"]), 1)
        self.assertEqual(bot.account["positions"][0]["takeProfit"], 102)   # the target stays: a late entry exits sooner
        self.assertTrue(pp.is_stale(100, 100.15, 99))    # a buy: the price went up (toward the target): late
        self.assertFalse(pp.is_stale(100, 100.1, 99))
        # Owner 2026-11-05: a move toward the stop is a better entry, never stale (the stop itself still counts).
        self.assertFalse(pp.is_stale(100, 99.3, 99))      # a buy, cheaper now
        self.assertFalse(pp.is_stale(100, 100.7, 101))    # a sell, higher now
        self.assertTrue(pp.is_stale(100, 99.85, 101))     # a sell, already fell: late

    async def test_short_signal_after_the_price_rose_is_entered_at_the_better_price(self):
        bot = self.bot
        bot.reset(100)
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.5, 100, 100.5)]   # short at 100, stop 101
        await bot._open(cand("A", 2.0, 20, side=SHORT), "15m", self.clock[0], {"fee_ratio": 0.33})
        p = bot.account["positions"][0]
        self.assertEqual((p["entryPrice"], p["stop"], p["takeProfit"]), (100.5, 101, 99.5))
        self.recent_rows["B/USDT:USDT"] = [bar(999_960, 100, 101.2, 100, 101.2)]   # past the stop: still no
        await bot._open(cand("B", 2.0, 20, side=SHORT), "15m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(bot.account["events"][-1]["reason"], "past")

    async def test_account_is_saved_and_loaded(self):
        self.bot.reset(80)
        self.bot.start()
        again = pp.PaperBot(pp.Store(self.path), None, None, None, now=lambda: self.clock[0], fees=FEES)
        self.assertEqual((again.account["capital"], again.account["status"]), (80, "running"))

    async def test_each_timeframe_scanned_once_per_candle(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append((tf, trade))
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual([tf for tf, _ in scanned], pp.TIMEFRAMES)   # fastest first
        self.assertEqual(pp.TIMEFRAMES, ["1m", "3m", "5m", "15m", "30m", "1h", "4h"])
        self.assertTrue(all(trade for _, trade in scanned))
        await bot.step()
        self.assertEqual(len(scanned), 7)                             # same candles: no new scan
        self.clock[0] += 60
        await bot.step()
        self.assertIn(("1m", True), scanned[7:])

    async def test_new_timeframes_start_ticked_in_old_files(self):
        old = pp.new_account(100, self.clock[0])
        old["chosenTimeframes"] = ["1m", "15m", "1h"]      # saved before 30m and 4h; 3m and 5m unticked
        old.pop("knownTimeframes", None)
        path = Path(self.dir.name) / "old.json"
        pp.Store(path).save(old)
        bot = pp.PaperBot(pp.Store(path), self.bot.coins, self.bot.history, self.bot.recent,
                          now=lambda: self.clock[0], fees=FEES)
        self.assertEqual(bot.chosen_timeframes(), ["1m", "15m", "30m", "1h", "4h"])
        bot.set_timeframes(["1h"])                          # the owner's later choice stays
        bot.save()
        again = pp.PaperBot(pp.Store(path), self.bot.coins, self.bot.history, self.bot.recent,
                            now=lambda: self.clock[0], fees=FEES)
        self.assertEqual(again.chosen_timeframes(), ["1h"])

    async def test_ticked_timeframes_scanned_first(self):
        bot = self.bot
        bot.reset(100)
        bot.set_timeframes(["15m"])
        bot.start()
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append(tf)
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual(scanned, ["15m"])        # only the ticked timeframe while trading

    async def test_reset_during_a_round_stops_the_round(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append(tf)
            if len(scanned) == 2:
                bot.reset(50)          # pressed while the round runs
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual(len(scanned), 2)     # the rest of the old round is dropped
        self.assertEqual(bot.account["capital"], 50)

    async def test_switching_on_ends_the_learning_round(self):
        bot = self.bot
        bot.memory = object()   # learn_only only runs with a memory
        bot.reset(100)
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append((tf, trade))
            bot.start()                # pressed while the learning round runs
        bot._scan_and_open = fake_scan
        await bot.learn_only()
        self.assertEqual(scanned, [("4h", False)])     # biggest first
        await bot.step()               # the next round trades straight away
        self.assertTrue(any(trade for _, trade in scanned[1:]))

    async def test_lock_is_free_between_timeframes(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        free = []

        async def fake_scan(tf, now, trade=True):
            await asyncio.sleep(0)
        bot._scan_and_open = fake_scan
        task = asyncio.create_task(bot.step())

        async def press():
            async with bot.lock:   # what the "start again" button waits for
                free.append(True)
        await asyncio.gather(task, press())
        self.assertEqual(free, [True])

    async def test_smart_pause_after_four_losses_then_resume(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append((tf, trade))
        bot._scan_and_open = fake_scan
        bot.account["lossStreak"] = 4
        await bot.step()
        self.assertEqual(bot.public()["pauseReason"], "streak")
        self.assertTrue(scanned and not any(trade for _, trade in scanned))   # still scans (learning), no trades
        self.clock[0] += pp.PAUSE_SECONDS + 1
        scanned.clear()
        await bot.step()
        self.assertIsNone(bot.public()["pausedUntil"])
        self.assertEqual(bot.account["lossStreak"], 0)
        self.assertTrue(all(trade for _, trade in scanned))
        self.assertEqual([e["kind"] for e in bot.account["events"]][-2:], ["pause", "resume"])

    async def test_owner_pause_rules(self):
        bot = self.bot
        bot.reset(100)
        bot.start()

        async def fake_scan(tf, now, trade=True):
            pass
        bot._scan_and_open = fake_scan
        self.assertEqual((bot.public()["rules"]["pauseLosses"], bot.public()["rules"]["pauseFall"]), (4, 5.0))
        bot.set_pause_rules(0, 5)                       # losses rule off
        bot.account["lossStreak"] = 9
        await bot.step()
        self.assertIsNone(bot.account["pausedUntil"])
        bot.set_pause_rules(6, 0)                       # 6 losses, fall rule off
        bot.account["balance"] = 80                     # a 20% fall: no pause with the rule off
        bot.account["lossStreak"] = 5
        await bot.step()
        self.assertIsNone(bot.account["pausedUntil"])
        bot.account["lossStreak"] = 6
        await bot.step()
        self.assertEqual(bot.account["pauseReason"], "streak")
        rules = bot.public()["rules"]
        self.assertEqual((rules["pauseLosses"], rules["pauseFall"]), (6, 0.0))
        bot.reset(100)                                  # settings, not results: kept
        self.assertEqual((bot.account["pauseLosses"], bot.account["pauseFall"]), (6, 0.0))
        bot.set_pause_rules(500, 99)                    # limited
        self.assertEqual((bot.account["pauseLosses"], bot.account["pauseFall"]), (pp.MAX_PAUSE_LOSSES, pp.MAX_PAUSE_FALL))

    async def test_owner_brain_knob(self):
        class FakeBrain:
            threshold = 0.34
            def active(self):
                return True
        from app.brain import Brain
        brain = FakeBrain()
        brain.champion = FakeBrain()
        allows = Brain.allows.__get__(brain)
        self.assertFalse(allows(0.30))                 # the brain's own threshold
        self.assertTrue(allows(0.30, 0.25))            # the owner's knob, looser
        self.assertFalse(allows(0.30, 0.40))           # stricter
        self.assertTrue(allows(0.01, 0.0))             # 0 = brain off
        self.assertTrue(allows(None, 0.5))             # no chance known: not blocked
        bot = self.bot
        bot.reset(100)
        self.assertIsNone(bot.public()["rules"]["brainThreshold"])
        bot.set_brain_threshold(0.25)
        self.assertEqual(bot.public()["rules"]["brainThreshold"], 0.25)
        bot.reset(50)                                   # a setting survives "start again"
        self.assertEqual(bot.account["brainThreshold"], 0.25)
        bot.set_brain_threshold(5)
        self.assertEqual(bot.account["brainThreshold"], pp.MAX_BRAIN_THRESHOLD)
        bot.set_brain_threshold(None)
        self.assertIsNone(bot.account["brainThreshold"])

    async def test_owner_coin_choice_is_kept(self):
        bot = self.bot
        bot.reset(100)
        self.assertEqual(bot.public()["rules"]["coinMode"], "top")
        bot.set_coins("manual", ["ETH/USDT:USDT", "BTC/USDT:USDT", "ETH/USDT:USDT"])
        bot.reset(50)
        self.assertEqual((bot.account["coinMode"], bot.account["coins"]), ("manual", ["ETH/USDT:USDT", "BTC/USDT:USDT"]))
        bot.set_coins("volatile", [])
        self.assertEqual(bot.public()["rules"]["coinMode"], "volatile")
        self.assertEqual(bot.account["coins"], ["ETH/USDT:USDT", "BTC/USDT:USDT"])   # the list stays for later

    async def test_ai_approves_rejects_or_the_owner_is_asked(self):
        from app import advisor
        from app.memory import Memory
        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        bot = self.bot
        bot.memory = memory
        bot.reset(100)
        bot.ai_keys = lambda: ["k"]
        bot.ask_timers = False          # the test moves the clock itself
        rule = {"fee_ratio": 0.33, "breakeven": 0}
        self.assertFalse(bot._ai_on("1h"))
        bot.set_ai(True, ["15m", "1h", "nope"])
        self.assertTrue(bot._ai_on("1h") and not bot._ai_on("1m"))
        self.assertEqual(bot.public()["ai"]["timeframes"], ["15m", "1h"])
        self.assertEqual(bot.public()["ai"]["keys"], ["…k"])
        seen = []

        async def yes(data, keys):
            seen.append(data)
            return {"approve": True, "confidence": 80, "reason": "خوب"}

        async def no(data, keys):
            return {"approve": False, "confidence": 30, "reason": "دیر است"}

        async def silent(data, keys):
            raise advisor.AdvisorUnavailable("HTTP 429")

        def signal(base):
            c = cand(base, 2.0, 20)
            c["memoryKey"] = memory.record(c, "1h", {}, self.clock[0])
            self.recent_rows[c["symbol"]] = [bar(999_960, 100, 100, 100, 100)]
            return c

        bot.ai_ask = yes
        await bot._ai_review(signal("A"), "1h", self.clock[0], rule)
        self.assertEqual([p["base"] for p in bot.account["positions"]], ["A"])
        self.assertEqual((seen[0]["coin"], seen[0]["side"]), ("A", LONG))
        bot.ai_ask = no
        b = signal("B")
        await bot._ai_review(b, "1h", self.clock[0], rule)
        self.assertEqual(len(bot.account["positions"]), 1)
        row = memory.db.execute("SELECT ai_decision, ai_reason, skip_reason FROM signals WHERE key = ?",
                                (b["memoryKey"],)).fetchone()
        self.assertEqual(row, ("reject", "دیر است", "ai"))
        self.assertEqual(bot.account["events"][-1]["text"], "دیر است")
        # No answer: the owner is asked; "open" opens it, an old question disappears.
        bot.ai_ask = silent
        wide = signal("C")      # the owner's "open" uses the bot's own 1h rules: a stop far enough for the fees
        wide["signal"].update(stopLoss=97, takeProfit=106)
        await bot._ai_review(wide, "1h", self.clock[0], rule)
        wide_d = signal("D")
        wide_d["signal"].update(stopLoss=97, takeProfit=106)
        await bot._ai_review(wide_d, "1h", self.clock[0], rule)
        asks = bot.public()["pendingAsks"]
        self.assertEqual([q["base"] for q in asks], ["C", "D"])
        self.assertEqual(bot.public()["ai"]["lastError"], "HTTP 429")
        self.assertTrue(await bot.answer_ask(asks[0]["id"], "open"))
        self.assertEqual(sorted(p["base"] for p in bot.account["positions"]), ["A", "C"])
        # No answer from the owner either: after 30 seconds the trade opens by itself.
        self.clock[0] += pp.ASK_AUTO_SECONDS - 1
        await bot._auto_open_asks(self.clock[0])
        self.assertEqual(len(bot.public()["pendingAsks"]), 1)
        self.clock[0] += 2
        await bot._auto_open_asks(self.clock[0])
        self.assertEqual(bot.public()["pendingAsks"], [])
        self.assertEqual(sorted(p["base"] for p in bot.account["positions"]), ["A", "C", "D"])
        self.assertFalse(await bot.answer_ask(asks[1]["id"], "skip"))     # already decided
        self.assertEqual(bot.account["events"][-1]["kind"], "open")
        self.assertEqual(set(memory.ai_summary()), set())                  # nothing finished yet
        bot.reset(50)                                                       # the settings stay
        self.assertEqual((bot.account["aiEnabled"], bot.account["aiTimeframes"]), (True, ["15m", "1h"]))

    async def test_start_again_keeps_the_manual_strategy_choice(self):
        bot = self.bot
        bot.reset(100)
        bot.set_mode("manual", ["donchian", "supertrend"])
        bot.reset(50)
        bot.start()
        self.assertEqual((bot.account["mode"], bot.account["strategies"]), ("manual", ["donchian", "supertrend"]))

    async def test_break_even_trades_do_not_count_as_losses(self):
        bot = self.bot
        bot.reset(100)
        base = {"notional": 100, "margin": 10, "exitTime": self.clock[0]}
        self.assertEqual(pp.trade_outcome({**base, "pnl": -1e-9, "exitReason": "stop"}), "even")   # rounding dust
        self.assertEqual(pp.trade_outcome({**base, "pnl": -0.02, "exitReason": "breakeven"}), "even")
        self.assertEqual(pp.trade_outcome({**base, "pnl": -0.5, "exitReason": "stop"}), "loss")
        bot.account["lossStreak"] = 3
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        p = bot.account["positions"][0]
        bot._close(p, pp.breakeven_price(p["side"], p["entryPrice"], FEES), "breakeven", self.clock[0])
        self.assertEqual(bot.account["lossStreak"], 3)          # unchanged: no 4th "loss", no pause
        self.assertEqual(bot.account["closed"][-1]["outcome"], "even")

    async def test_pause_ends_early_after_two_profits(self):
        from app.memory import Memory
        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        bot = self.bot
        bot.memory = memory
        bot.reset(100)
        bot.start()

        async def fake_scan(tf, now, trade=True):
            pass
        bot._scan_and_open = fake_scan
        bot.account["lossStreak"] = 4
        await bot.step()
        paused_at = self.clock[0]
        self.assertIsNotNone(bot.account["pausedUntil"])
        # During the pause: one shadow signal wins, then one loses -> still paused.
        rows = [("w1", "win", 100), ("l1", "loss", 200)]
        for key, status, dt in rows:
            memory.db.execute("INSERT INTO signals (key, strategy, status, exit_time, confirmed_at, reliable, source, taken)"
                              " VALUES (?, 'ema_cross', ?, ?, ?, 1, 'live', 0)", (key, status, paused_at + dt, paused_at + 10))
        memory.db.commit()
        self.clock[0] += 300
        await bot.step()
        self.assertIsNotNone(bot.account["pausedUntil"])
        # A bot trade closes in profit, then a shadow signal wins: two profits in a row -> back to work.
        bot.account["closed"].append({"exitTime": paused_at + 400, "pnl": 1.0, "notional": 100, "exitReason": "target"})
        memory.db.execute("INSERT INTO signals (key, strategy, status, exit_time, confirmed_at, reliable, source, taken)"
                          " VALUES ('w2', 'ema_cross', 'win', ?, ?, 1, 'live', 0)", (paused_at + 500, paused_at + 20))
        memory.db.commit()
        self.clock[0] += 300
        await bot.step()
        self.assertIsNone(bot.account["pausedUntil"])
        self.assertEqual(bot.account["events"][-1], {"time": self.clock[0], "kind": "resume", "reason": "recovered"})

    async def test_smart_pause_after_five_percent_fall(self):
        bot = self.bot
        bot.reset(100)
        bot.start()

        async def fake_scan(tf, now, trade=True):
            pass
        bot._scan_and_open = fake_scan
        bot.account["balance"] = 94.9
        await bot.step()
        self.assertEqual(bot.public()["pauseReason"], "fall")

    async def test_losing_strategies_are_benched_at_a_pause(self):
        from app.memory import Memory
        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        t = self.clock[0] - 100
        rows = [(f"d{i}", "donchian", "loss", t, -1.5) for i in range(pp.BENCH_MIN_RESULTS)]
        rows += [("b", "supertrend", "win", t, 2.0), ("e", "ema_cross", "loss", t, -1.0)]  # one loss: too few
        memory.db.executemany("INSERT INTO signals (key, strategy, status, exit_time, pnl_percent)"
                              " VALUES (?, ?, ?, ?, ?)", rows)
        memory.db.commit()
        bot = self.bot
        bot.memory = memory
        bot.reset(100)
        bot.start()

        async def fake_scan(tf, now, trade=True):
            pass
        bot._scan_and_open = fake_scan
        bot.account["lossStreak"] = 4
        await bot.step()
        self.assertEqual(list(bot.public()["benched"]), ["donchian"])
        self.assertEqual(bot.account["events"][-1]["strategies"], ["donchian"])

    async def test_switched_off_bot_still_learns(self):
        bot = self.bot
        bot.reset(100)
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append((tf, trade))
        bot._scan_and_open = fake_scan
        await bot.learn_only()
        self.assertEqual(len(scanned), 7)
        self.assertFalse(any(trade for _, trade in scanned))

    async def test_brain_skips_weak_signals_and_remembers_why(self):
        from unittest import mock
        from app.memory import Memory

        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)

        class Picky:   # a brain that thinks every signal is weak
            def chance(self, feats, strategy, tf, side):
                return 0.1

            def allows(self, chance, threshold=None):
                return chance is None or chance >= (0.5 if threshold is None else threshold)

        bot = self.bot
        bot.memory, bot.brain = memory, Picky()
        bot.reset(100)
        c = cand("A", 2.0, 20)
        overview = {"marketState": "trend_up", "adx": 30, "atrRatio": 1,
                    "rows": [{"strategy": "ema_cross", "stats": c["stats"], "signal": c["signal"]}]}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=True)
        self.assertEqual(bot.account["positions"], [])
        self.assertEqual(bot.account["events"][-1]["reason"], "brain")
        chance, reason = memory.db.execute("SELECT chance, skip_reason FROM signals").fetchone()
        self.assertEqual((chance, reason), (0.1, "brain"))
        # The owner's knob lets it through (0 = brain off).
        bot.set_brain_threshold(0.0)
        memory.db.execute("DELETE FROM signals")
        self.clock[0] += 60
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=True)
        # Past the brain now: it reaches the next rule (here the fee limit or a position).
        self.assertNotEqual(memory.db.execute("SELECT skip_reason FROM signals").fetchone()[0], "brain")
        self.assertNotEqual(bot.account["events"][-1]["reason"] if bot.account["events"][-1]["kind"] == "skip" else "",
                            "brain")

    async def test_signals_not_traded_while_paused_are_marked(self):
        from unittest import mock
        from app.memory import Memory

        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        bot = self.bot
        bot.memory = memory
        bot.reset(100)
        bot.account["pausedUntil"] = self.clock[0] + 600
        c = cand("A", 2.0, 20)
        overview = {"marketState": "trend_up", "adx": 30, "atrRatio": 1,
                    "rows": [{"strategy": "ema_cross", "stats": c["stats"], "signal": c["signal"]}]}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=False)
        self.assertEqual(memory.db.execute("SELECT skip_reason FROM signals").fetchone()[0], "paused")

    async def test_pretraining_round_fills_the_memory_once_a_day(self):
        from app.memory import Memory
        from tests.test_pretrain import walk

        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)

        class NoModel:
            champion = None
            last = {"result": "few"}

        candles = walk(3000)
        last_time = candles[-1]["time"]
        self.clock[0] = last_time + 400

        async def history(symbol, tf):
            return candles

        bot = self.bot
        bot.memory, bot.brain, bot.history = memory, NoModel(), history
        added = await bot.pretrain_round()
        self.assertGreater(added, 0)
        self.assertEqual(memory.summary()["history"], added)
        self.assertEqual(bot.pretrain_progress, {"done": 7, "total": 7, "running": False})
        self.assertEqual(bot.account["events"][-1]["kind"], "pretrain")
        self.assertIsNone(bot.brain.last)                 # the brain learns right away
        self.assertEqual(await bot.pretrain_round(), 0)   # charts done today are skipped

    async def test_every_signal_is_remembered_and_unreliable_ones_are_tried_too(self):
        from unittest import mock
        from app.memory import Memory

        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        bot = self.bot
        bot.memory = memory
        bot.reset(100)
        weak = cand("A", 0.5, 20)      # profit factor below 1: not reliable
        overview = {"marketState": "trend_up", "adx": 30, "atrRatio": 1,
                    "rows": [{"strategy": "ema_cross", "stats": weak["stats"], "signal": weak["signal"]}]}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=True)
        # Owner 2026-11-06: the "reliable" rule no longer filters. This one still is marked not reliable in
        # memory, and went on to the trade checks (here the 1m fee rule stopped it).
        self.assertEqual(memory.db.execute("SELECT reliable, skip_reason FROM signals").fetchone(), (0, "fee"))
        # With the rule switched on (the old behaviour) it never reaches the trade checks.
        from dataclasses import replace
        memory.db.execute("DELETE FROM signals")
        bot.profile = replace(bot.profile, use_reliable=True)
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0] + 60, trade=True)
        self.assertEqual(bot.account["positions"], [])
        self.assertEqual(memory.db.execute("SELECT reliable, skip_reason FROM signals").fetchone(), (0, None))

    async def test_owner_closes_one_or_all_positions(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        bot.account["lossStreak"] = 3
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 99.5, 99.5)]     # a small loss now
        pid = bot.account["positions"][0]["id"]
        self.assertTrue(await bot.close_position(pid))
        trade = bot.account["closed"][-1]
        self.assertEqual((trade["exitReason"], trade["exitPrice"]), ("manual", 99.5))
        self.assertEqual(bot.account["lossStreak"], 3)                 # the owner's close does not count
        self.assertFalse(await bot.close_position(pid))                 # already closed
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100)]
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.assertEqual(await bot.close_all_and_stop(), 1)
        self.assertEqual((bot.account["positions"], bot.account["status"]), ([], "stopped"))

    async def test_one_coin_failing_does_not_stop_checking_the_others(self):
        bot = self.bot
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.recent_rows["B/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100)]
        await bot._open(cand("B", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.assertEqual([p["base"] for p in bot.account["positions"]], ["A", "B"])
        recent = bot.recent

        async def flaky(symbol, tf):
            if symbol.startswith("A/"):
                raise TimeoutError("RequestTimeout")
            return await recent(symbol, tf)
        bot.recent = flaky
        # B reaches its target; A's timeout must not stop that check.
        self.recent_rows["B/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100), bar(1_000_020, 100, 102.5, 99.5, 102)]
        self.clock[0] = 1_000_090
        with self.assertLogs("trading_bot", level="WARNING"):
            await bot._watch_positions(self.clock[0])
        self.assertEqual([p["base"] for p in bot.account["positions"]], ["A"])
        self.assertEqual(bot.account["closed"][-1]["base"], "B")

    async def test_owner_moves_stop_and_target(self):
        bot = self.bot
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1h", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0.5})
        p = bot.account["positions"][0]
        pid, liq = p["id"], p["liquidation"]
        self.assertEqual(bot.set_levels(99, stop=98), "missing")
        self.assertEqual(bot.set_levels(pid, stop=100.5), "stop_side")          # above the price now (long)
        self.assertEqual(bot.set_levels(pid, stop=liq - 0.1), "stop_liquidation")
        self.assertEqual(bot.set_levels(pid, target=99.8), "target_side")
        self.assertEqual(p["stop"], 99)                                          # nothing changed
        old_risk = p["risk"]
        self.assertIsNone(bot.set_levels(pid, stop=98))                          # wider: more risk, same size
        self.assertEqual(p["stop"], 98)
        self.assertAlmostEqual(p["risk"], old_risk * (0.02 + 0.0012) / (0.01 + 0.0012))
        self.assertTrue(p["edited"])
        self.assertEqual(bot.account["events"][-1]["kind"], "levels")
        self.assertIsNone(bot.set_levels(pid, target=104))
        self.assertEqual(p["takeProfit"], 104)
        # Break-even follows the new target: half way is now 102, a candle to 101.5 does not move it.
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100), bar(1_000_000, 100, 101.5, 99.9, 101)]
        self.clock[0] = 1_000_000 + 3600 + 10
        await bot._watch_positions(self.clock[0])
        self.assertEqual((p["stop"], p["breakevenAt"]), (98, None))
        # Target moved close to the price: past the new trigger, so break-even moves the stop at once.
        self.assertIsNone(bot.set_levels(pid, target=101.6))
        self.assertEqual(p["stop"], p["breakevenPrice"])
        self.assertIsNotNone(p["breakevenAt"])
        # The owner moves the stop away again: it is the owner's stop, the exit is a plain stop.
        self.assertIsNone(bot.set_levels(pid, stop=99.5))
        self.assertIsNone(p["breakevenAt"])
        # A stop that locks profit is never pulled back to break-even.
        self.assertIsNone(bot.set_levels(pid, stop=100.8))
        pp._maybe_breakeven(p, 101.5, 1)
        self.assertEqual(p["stop"], 100.8)

    async def test_profit_cap_takes_the_small_profit(self):
        bot = self.bot
        bot.reset(100)
        bot.set_profit_cap(0.1)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100.05)]   # not enough after fees yet
        await bot._watch_positions(self.clock[0])
        self.assertEqual(len(bot.account["positions"]), 1)
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.3, 100, 100.3)]
        await bot._watch_positions(self.clock[0])
        trade = bot.account["closed"][-1]
        self.assertEqual(trade["exitReason"], "cap")
        self.assertGreaterEqual(trade["pnl"], 0.1)
        bot.reset(50)
        self.assertEqual(bot.account["profitCap"], 0.1)                  # a setting survives "start again"

    def test_slow_charts_use_the_normal_rule_now(self):
        # Owner 2026-11-01: the extra rule for 15m / 1h is off (too strict with the other filters).
        self.assertTrue(pp.strict_ok(cand("A", 1.3, 12), "1h"))
        self.assertEqual(pp.BOT_STRATEGIES, tuple(pp.STRATEGIES))
        self.assertTrue(all(pp.BOT_STRATEGIES_BY_TF[tf] == tuple(pp.STRATEGIES) for tf in pp.TIMEFRAMES))

    async def test_owner_consults_about_an_open_position(self):
        from unittest import mock
        bot = self.bot
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        p = bot.account["positions"][0]
        bot.prices[p["id"]] = 101.0
        seen = {}

        async def fake_consult(data, position, price, keys):
            seen.update(data=data, price=price)
            return {"action": "move_stop", "newStop": 100.2, "confidence": 65, "reason": "حمایت در ۱۰۰.۲", "levels": "", "note": ""}
        bot.ai_consult = fake_consult
        bot.ai_keys = lambda: ["k"]
        overview = {"marketState": "trend_up", "rows": []}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            answer = await bot.consult(p["id"])
        self.assertEqual(answer["ai"]["action"], "move_stop")
        self.assertEqual((answer["bot"]["suggest"], answer["bot"]["progress"]), ("hold", 50.0))   # 101 of 100 -> 102
        d = seen["data"]["position"]
        self.assertEqual((d["entry"], d["stopLoss"], d["takeProfit"], d["priceNow"]), (100, 99, 102, 101.0))
        self.assertIn("supportResistance", seen["data"])
        self.assertEqual(p["stop"], 99)                          # nothing done automatically
        self.assertEqual(p["consults"][-1]["ai"]["newStop"], 100.2)
        bot.ai_keys = lambda: []
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            self.assertEqual((await bot.consult(p["id"]))["error"], "noKeys")
        self.assertIsNone(await bot.consult(999))

    async def test_half_way_advice_is_off_now(self):
        bot = self.bot
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 101.2)]   # past half way
        await bot._watch_positions(self.clock[0])
        self.assertIsNone(bot.account["positions"][0].get("advice"))      # owner 2026-11-05: removed

    async def test_half_way_advice_and_the_owners_answer(self):
        from dataclasses import replace
        from unittest import mock
        bot = self.bot
        bot.profile = replace(bot.profile, advice=True)   # the feature itself still works if switched on
        bot.reset(100)
        await bot._open(cand("A", 2.0, 20), "1m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0})
        p = bot.account["positions"][0]
        opposite = cand("A", 2.0, 20, side=SHORT)
        overview = {"marketState": "trend_up", "rows": [{"strategy": "supertrend", "stats": opposite["stats"],
                                                          "signal": opposite["signal"]}]}
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100, 100, 100.5)]          # not yet half way (101)
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._watch_positions(self.clock[0])
            self.assertIsNone(p.get("advice"))
            self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 101.2, 100, 101.2)]
            await bot._watch_positions(self.clock[0])
        self.assertEqual((p["advice"]["suggest"], p["advice"]["reason"]), ("close", "opposite"))
        self.assertEqual(bot.account["events"][-1]["kind"], "advice")
        self.assertTrue(bot.answer_advice(p["id"], "hold"))
        self.assertEqual(p["advice"]["answer"], "hold")
        self.assertEqual(len(bot.account["positions"]), 1)                              # it goes on

    async def test_only_ticked_timeframes_are_scanned_while_trading(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        bot.set_timeframes(["5m", "1m"])
        self.assertEqual(bot.chosen_timeframes(), ["1m", "5m"])
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append((tf, trade))
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual(scanned, [("1m", True), ("5m", True)])
        self.assertEqual(set(bot.public()["scanSeconds"]), {"1m", "5m"})
        bot.reset(50)
        self.assertEqual(bot.public()["chosenTimeframes"], ["1m", "5m"])     # kept after start again

    async def test_a_new_1m_candle_jumps_ahead_of_slower_scans(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        bot.set_timeframes(["1m", "15m"])
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append(tf)
            if tf == "1m" and len(scanned) == 1:
                self.clock[0] += 60            # the 1m scan took a whole minute
        bot._scan_and_open = fake_scan
        await bot.step()
        self.assertEqual(scanned, ["1m"])        # 15m waits, a fresh 1m candle comes first
        await bot.step()
        self.assertEqual(scanned, ["1m", "1m", "15m"])

    async def test_slow_scans_do_not_starve_the_slower_timeframes(self):
        bot = self.bot
        bot.reset(100)
        bot.start()
        bot.set_timeframes(["1m", "5m", "15m"])
        scanned = []

        async def fake_scan(tf, now, trade=True):
            scanned.append(tf)
            self.clock[0] += 70                 # every scan is slower than a 1m candle
        bot._scan_and_open = fake_scan
        for _ in range(3):
            await bot.step()
        self.assertIn("5m", scanned)
        self.assertIn("15m", scanned)

    async def test_main_bot_counts_why_signals_were_not_traded(self):
        from unittest import mock
        bot = self.bot
        bot.reset(100)
        weak, good = cand("A", 0.5, 20), cand("A", 2.0, 20)
        overview = {"marketState": "trend_up", "adx": 30, "atrRatio": 1,
                    "rows": [{"strategy": "ema_cross", "stats": weak["stats"], "signal": weak["signal"]},
                             {"strategy": "supertrend", "stats": good["stats"], "signal": good["signal"]}]}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=False)
        flow = bot.public()["flow"]
        self.assertEqual((flow["seen"], flow["skipped"]), (2, {"full": 2}))   # no "reliable" rule (owner 2026-11-06)
        from dataclasses import replace
        bot.flow = []   # the counter of the last 10 minutes, from zero
        bot.profile = replace(bot.profile, use_reliable=True)
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=False)
        flow = bot.public()["flow"]
        self.assertEqual((flow["seen"], flow["skipped"]), (2, {"unreliable": 1, "full": 1}))

    async def test_brain_learning_round_writes_the_diary(self):
        class Quick:
            def train(self):
                return {"result": "promoted", "version": 3}

        self.bot.brain = Quick()
        outcome = await self.bot.learn()
        self.assertEqual(outcome["result"], "promoted")
        self.assertEqual(self.bot.account["events"][-1], {"time": self.clock[0], "kind": "brain",
                                                          "reason": "promoted", "version": 3})

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



class BotSettingsTest(unittest.TestCase):
    def test_break_even_only_on_the_hour_chart(self):
        self.assertEqual({tf: pp.all_settings(tf)["donchian"]["breakeven"] for tf in pp.TIMEFRAMES},
                         {"1m": 0.0, "3m": 0.0, "5m": 0.0, "15m": 0.0, "30m": 0.0, "1h": 0.5, "4h": 0.5})

    def test_main_bot_fee_limit_per_timeframe(self):
        for tf in pp.TIMEFRAMES:
            self.assertEqual({p["fee_ratio"] for p in pp.bot_settings(tf).values()}, {pp.FEE_RATIO_BY_TF[tf]})
        self.assertEqual(pp.FEE_RATIO_BY_TF["3m"], 0.10)
        self.assertEqual(pp.FEE_RATIO_BY_TF["15m"], 0.05)
        # The strategies' own limit stays for the screens outside the bot.
        self.assertEqual({p["fee_ratio"] for p in pp.all_settings("1m").values()}, {0.33})

    def test_fee_limit_rejects_a_near_stop(self):
        fees = pp.Fees(maker=0.02, taker=0.06)
        # Round trip 0.12%: a 2% stop gives a 6% share (over 5%), a 3% stop gives 4%.
        self.assertFalse(pp.fee_ok(100, 98, fees, pp.FEE_RATIO_BY_TF["15m"]))
        self.assertTrue(pp.fee_ok(100, 97, fees, pp.FEE_RATIO_BY_TF["15m"]))
        self.assertTrue(pp.fee_ok(100, 98, fees, pp.FEE_RATIO_BY_TF["3m"]))


class BotListTest(unittest.IsolatedAsyncioTestCase):
    """The bot's own strategy list per timeframe (chosen from the history test)."""

    def test_list_only_has_known_strategies(self):
        for tf, kinds in pp.BOT_STRATEGIES_BY_TF.items():
            self.assertIn(tf, pp.TIMEFRAMES)
            self.assertTrue(set(kinds) <= set(pp.STRATEGIES))
            self.assertEqual(set(pp.bot_settings(tf)), set(kinds))
        self.assertEqual(len(pp.all_settings("5m")), len(pp.STRATEGIES))

    async def test_timeframe_without_strategies_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as folder:
            bot = pp.PaperBot(pp.Store(Path(folder) / "paper.json"), None, None, None, now=lambda: 1_000_000.0)
            bot.reset(100)
            bot.start()
            scanned = []

            async def fake_scan(tf, now, trade=True):
                scanned.append(tf)
            bot._scan_and_open = fake_scan
            await bot.step()
        expected = [tf for tf in pp.TIMEFRAMES if pp.BOT_STRATEGIES_BY_TF[tf]]
        self.assertEqual(sorted(scanned), sorted(expected))

    def test_old_choice_keeps_only_known_strategies(self):
        with tempfile.TemporaryDirectory() as folder:
            store = pp.Store(Path(folder) / "paper.json")
            first = pp.PaperBot(store, None, None, None)
            first.account["mode"] = "manual"
            first.account["strategies"] = ["gone_strategy", pp.BOT_STRATEGIES[0]]
            first.save()
            again = pp.PaperBot(store, None, None, None)
            self.assertEqual(again.account["strategies"], [pp.BOT_STRATEGIES[0]])
            again.set_mode("manual", ["gone_strategy"])            # nothing left: back to the whole list
            self.assertEqual(again.account["strategies"], list(pp.BOT_STRATEGIES))


if __name__ == "__main__":
    unittest.main()


class LoopSurvivesTest(unittest.IsolatedAsyncioTestCase):
    """A cancel from inside a request (e.g. the exchange connection closed on a proxy change)
    must not end the bot's loop; only cancelling the loop itself does."""

    async def test_stray_cancel_does_not_stop_the_loop(self):
        calls = []

        async def coins():
            calls.append(1)
            if len(calls) == 1:
                raise asyncio.CancelledError()
            return []

        async def nothing(*args):
            return []

        with tempfile.TemporaryDirectory() as folder:
            clock = [1_000_000.0]
            bot = pp.PaperBot(pp.Store(Path(folder) / "paper.json"), coins, nothing, nothing,
                              now=lambda: clock[0], fees=FEES)
            bot.reset(100)
            bot.start()
            old_poll = pp.POLL_SECONDS
            pp.POLL_SECONDS = 0
            try:
                task = asyncio.create_task(bot.run_forever())
                for _ in range(200):
                    await asyncio.sleep(0.01)
                    clock[0] += 61   # next 1-minute candle: a new scan is due
                    if len(calls) >= 2:
                        break
                self.assertFalse(task.done())
                self.assertGreaterEqual(len(calls), 2)
                self.assertTrue(any(e["kind"] == "error" for e in bot.account["events"]))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                pp.POLL_SECONDS = old_poll


class LimitEntryTest(unittest.IsolatedAsyncioTestCase):
    """Limit entry (owner's switch): orders fill only when the price goes beyond them, maker fee in."""
    T = 1_000_000.0            # now; the 15m candle forming now started at 999_900, the minute at 999_960

    def setUp(self):
        from unittest import mock
        every = tuple(pp.STRATEGIES)
        for name, value in (("BOT_STRATEGIES_BY_TF", {tf: every for tf in pp.TIMEFRAMES}), ("BOT_STRATEGIES", every)):
            patcher = mock.patch.object(pp, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "paper.json"
        self.clock = [self.T]
        self.rows = {}   # (symbol, timeframe) -> candles

        async def recent(symbol, tf):
            return self.rows.get((symbol, tf), [])
        self.recent = recent
        self.bot = self.new_bot()
        self.bot.reset(100)
        self.bot.set_limit_entry(True)
        for base in "ABCDEFGHIJ":
            self.rows[(f"{base}/USDT:USDT", "15m")] = [bar(999_900, 100, 100, 100, 100)]

    def new_bot(self):
        async def coins():
            return [("A/USDT:USDT", "A")]

        async def history(symbol, tf):
            return []
        return pp.PaperBot(pp.Store(self.path), coins, history, self.recent, now=lambda: self.clock[0], fees=FEES)

    def minutes(self, *bars, last=None):
        rows = list(bars)
        if last is not None:   # the minute forming now (live price)
            t = int(self.clock[0] // 60 * 60)
            rows.append(bar(t, last, last, last, last))
        self.rows[("A/USDT:USDT", "1m")] = rows

    async def place(self, base="A", side=LONG):
        await self.bot._open(cand(base, 2.0, 20, side), "15m", self.clock[0], {"fee_ratio": 0.33, "breakeven": 0.5})

    async def test_switch_off_opens_at_the_market_as_before(self):
        self.bot.set_limit_entry(False)
        await self.place()
        p = self.bot.account["positions"][0]
        self.assertEqual((p["entryType"], p["entryPrice"], self.bot.account["orders"]), ("market", 100, []))
        self.assertAlmostEqual(p["entryFee"], p["notional"] * 0.06 / 100)
        self.assertAlmostEqual(p["breakevenPrice"], pp.breakeven_price(LONG, 100, FEES))
        self.assertAlmostEqual(p["breakevenPrice"], 100 * 1.0006 / 0.9994)     # the old formula

    async def test_order_price_and_fill_only_beyond_it_with_maker_fee(self):
        await self.place()
        o = self.bot.account["orders"][0]
        self.assertAlmostEqual(o["price"], 99.9)                               # 0.1 of the stop distance (1) below
        self.assertEqual(self.bot.account["positions"], [])
        self.clock[0] = 1_000_150
        self.minutes(bar(1_000_020, 100, 100.1, 99.9, 100), last=100)            # touched 99.9: not filled
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(len(self.bot.account["orders"]), 1)
        self.minutes(bar(1_000_020, 100, 100.1, 99.9, 100), bar(1_000_080, 100, 100, 99.85, 99.95), last=100)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(self.bot.account["orders"], [])
        p = self.bot.account["positions"][0]
        self.assertEqual((p["entryType"], p["entryPrice"], p["stop"]), ("limit", 99.9, 99))
        self.assertAlmostEqual(p["takeProfit"], 101.7)   # 2R from the real entry, not from the signal's price
        self.assertAlmostEqual(p["entryFee"], p["notional"] * 0.02 / 100)       # maker
        self.assertAlmostEqual(p["breakevenPrice"], 99.9 * 1.0002 / 0.9994)     # maker in, taker out
        self.assertLess(p["breakevenPrice"], pp.breakeven_price(LONG, 99.9, FEES))
        self.assertEqual(p["entryCandle"], 999_900)                              # the 15m candle of the fill
        self.assertEqual(self.bot.account["limitStats"]["filled"], 1)

    async def test_live_price_beyond_the_order_fills(self):
        await self.place(side=pp.SHORT if hasattr(pp, "SHORT") else SHORT)
        o = self.bot.account["orders"][0]
        self.assertAlmostEqual(o["price"], 100.1)                              # a sell: above the price
        self.minutes(last=100.1)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(len(self.bot.account["orders"]), 1)                    # touching is not enough
        self.minutes(last=100.12)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(self.bot.account["positions"][0]["entryPrice"], o["price"])

    async def test_expires_after_one_candle(self):
        await self.place()
        self.clock[0] = self.T + 899
        self.minutes(bar(1_000_020, 100, 100.3, 99.95, 100.2), last=100.2)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(len(self.bot.account["orders"]), 1)
        self.clock[0] = self.T + 900
        await self.bot._watch_orders(self.clock[0])
        a = self.bot.account
        self.assertEqual((a["orders"], a["positions"], a["limitStats"]["expired"]), ([], [], 1))
        self.assertEqual((a["events"][-1]["kind"], a["events"][-1]["reason"]), ("orderCancel", "limit_expired"))
        self.assertEqual(self.bot.flow_summary()["skipped"].get("limit_expired"), 1)
        self.assertEqual(self.bot.public()["entryStats"]["limit"]["fillRate"], 0)

    async def test_target_or_stop_first_cancels(self):
        await self.place()
        self.clock[0] = 1_000_150
        self.minutes(bar(1_000_020, 100, 102.1, 99.95, 101.5), last=101.5)       # reached the target, never crossed
        await self.bot._watch_orders(self.clock[0])
        a = self.bot.account
        self.assertEqual((a["orders"], a["positions"], a["limitStats"]["cancelled"]), ([], [], 1))
        self.assertEqual(a["events"][-1]["detail"], "target")
        # Target and crossing in the same minute: the order inside it is unknown, so no fill (no optimism).
        await self.place()                                                      # at 1_000_150: minutes from 1_000_200
        self.clock[0] = 1_000_300
        self.minutes(bar(1_000_200, 100, 102.1, 99.5, 101.5), last=101.5)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual((a["orders"], a["positions"]), ([], []))
        # Live price at the target before a fill.
        await self.place()
        self.minutes(last=102)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual((a["orders"], a["positions"]), ([], []))

    async def test_fill_and_stop_in_the_same_minute_is_a_loss(self):
        await self.place()
        self.clock[0] = 1_000_150
        self.minutes(bar(1_000_020, 100, 100, 98.8, 99.0), last=99.2)
        await self.bot._watch_orders(self.clock[0])
        a = self.bot.account
        self.assertEqual(a["positions"], [])
        t = a["closed"][-1]
        self.assertEqual((t["entryType"], t["entryPrice"], t["exitReason"], t["exitPrice"]), ("limit", 99.9, "stop", 99))
        # A fill noticed late: the minutes after it are checked too.
        await self.place()                                                      # at 1_000_150: minutes from 1_000_200
        self.clock[0] = 1_000_400
        self.minutes(bar(1_000_200, 100, 100, 99.8, 99.9), bar(1_000_260, 99.9, 102.3, 99.9, 102.2), last=102)
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(a["closed"][-1]["exitReason"], "target")
        self.assertAlmostEqual(a["closed"][-1]["exitPrice"], 101.7)

    async def test_waiting_orders_survive_closing_the_app(self):
        await self.place()
        self.bot.save()   # the bot's loop saves after each scan
        again = self.new_bot()
        self.assertTrue(again.account["limitEntry"])
        self.assertEqual(len(again.account["orders"]), 1)
        self.minutes(last=99.8)
        await again._watch_orders(self.clock[0])
        self.assertEqual(again.account["positions"][0]["entryPrice"], 99.9)

    async def test_old_paper_file_opens(self):
        import json
        old = {k: v for k, v in pp.new_account(80, self.T).items() if k not in ("limitEntry", "orders", "limitStats")}
        old["closed"] = [{"pnl": 1.0, "fees": 0.1, "risk": 1.0, "notional": 50, "exitReason": "target"}]
        self.path.write_text(json.dumps(old))
        bot = self.new_bot()
        self.assertEqual((bot.account["limitEntry"], bot.account["orders"]), (False, []))
        stats = bot.public()["entryStats"]
        self.assertEqual((stats["market"]["trades"], stats["market"]["avgR"], stats["limit"]["fillRate"]), (1, 1.0, None))

    async def test_margin_of_many_waiting_orders_never_exceeds_the_money(self):
        for base in "ABCDEFGHIJ":
            await self.place(base)
        a = self.bot.account
        margins = [o["margin"] for o in a["orders"]]
        self.assertLessEqual(sum(margins), self.bot.equity() + 1e-9)
        self.assertLess(len(margins), 10)                                        # money ran out: the rest skipped
        self.assertEqual(a["events"][-1]["reason"], "full")
        # One per coin: a second signal for a coin with a waiting order is skipped.
        before = len(a["orders"])
        await self.place("A")
        self.assertEqual(len(a["orders"]), before)

    async def test_switching_off_or_stopping_cancels_waiting_orders(self):
        await self.place()
        self.bot.set_limit_entry(False)
        self.assertEqual((self.bot.account["orders"], self.bot.account["limitStats"]["cancelled"]), ([], 1))
        self.bot.set_limit_entry(True)
        await self.place()
        self.bot.start()
        self.bot.stop()
        self.assertEqual(self.bot.account["orders"], [])
        await self.place()
        self.bot.reset(100)
        self.assertEqual((self.bot.account["orders"], self.bot.account["limitEntry"]), ([], True))

    async def test_cancelled_order_is_marked_in_memory(self):
        from app.memory import Memory
        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)
        self.bot.memory = memory
        c = cand("A", 2.0, 20)
        c["memoryKey"] = memory.record(c, "15m", {}, now=self.T)
        await self.bot._open(c, "15m", self.T, {"fee_ratio": 0.33})
        self.clock[0] = self.T + 900
        await self.bot._watch_orders(self.clock[0])
        self.assertEqual(memory.db.execute("SELECT skip_reason, taken FROM signals").fetchone(), ("limit_expired", 0))

    async def test_order_cancelled_while_being_checked_does_not_open(self):
        await self.place()
        o = self.bot.account["orders"][0]
        self.bot.set_limit_entry(False)          # the owner's switch, while the check waited for candles
        self.assertIsNone(self.bot._fill(o, 999_900, self.T, None))
        self.assertEqual(self.bot.account["positions"], [])

    async def test_order_price_is_rounded_to_the_coins_price_step(self):
        self.assertEqual(pp.price_step([bar(0, 0.03241, 0.03245, 0.0323, 0.0324)]), 0.00001)
        self.assertAlmostEqual(pp.to_step(0.0323920384, 0.00001, down=True), 0.03239)
        self.assertAlmostEqual(pp.to_step(0.0323920384, 0.00001, down=False), 0.03240)
        self.rows[("A/USDT:USDT", "15m")] = [bar(999_900, 100.03, 100.07, 99.98, 100.05)]
        await self.place()              # long, price 100.05, stop 99: 0.1 x 1.05 below = 99.945 -> 99.94
        self.assertEqual(self.bot.account["orders"][0]["price"], 99.94)
        await self.place("B", SHORT)    # whole-number candles (step 1): rounding would reach the stop, kept as is
        self.assertAlmostEqual(self.bot.account["orders"][1]["price"], 100.1)

    async def test_profit_lock_setting_reaches_open_positions(self):
        self.bot.set_limit_entry(False)
        await self.place()
        p = self.bot.account["positions"][0]
        self.rows[("A/USDT:USDT", "15m")] = [bar(999_900, 100, 100, 100, 100)]
        await self.bot._watch_positions(self.T)
        self.assertNotIn("lock", p)                                     # off by default
        self.bot.set_lock(True, 80, 40)
        await self.bot._watch_positions(self.T)
        self.assertEqual(p["lock"], {"trigger": 0.8, "at": 0.4})
        self.rows[("A/USDT:USDT", "15m")] = [bar(999_900, 100, 100, 100, 101.7)]   # 85% of the way (target 102)
        await self.bot._watch_positions(self.T)
        self.assertAlmostEqual(p["stop"], 100.8)
        self.assertEqual(self.bot.public()["rules"]["lock"], {"enabled": True, "trigger": 80, "at": 40})
        self.assertIsNone(self.bot.set_levels(p["id"], stop=100.5))     # the owner moves it: his stop again
        self.assertIsNone(p["lockedAt"])
        self.bot.reset(100)
        self.assertTrue(self.bot.account["lockEnabled"])                # a setting: kept on "start again"


class MissedCandlesTest(unittest.IsolatedAsyncioTestCase):
    """The CLANKER case (2026-11-05): the bot did not watch for hours; on waking it saw only the last 60
    candles, all below the stop, and closed at the first one's open (-8.2 USDT instead of about -2.6)."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.history_rows, self.recent_rows = [], []

        async def history(symbol, tf):
            return self.history_rows

        async def recent(symbol, tf):
            return self.recent_rows

        async def coins():
            return []
        self.bot = pp.PaperBot(pp.Store(Path(self.dir.name) / "paper.json"), coins, history, recent,
                               now=lambda: 0, fees=FEES)
        self.bot.reset(100)
        # Long at 25.38 in the 3m candle at 0, stop moved to 22.54, target 28.21.
        self.p = position(id=1, symbol="CLANKER/USDT:USDT", base="CLANKER", timeframe="3m", entryPrice=25.38,
                          stop=22.54, stopLoss=24.22, takeProfit=28.21, breakevenPart=0, quantity=0.906,
                          entryFee=0.0046, notional=23, margin=11.5, risk=2.6, entryCandle=0, checkedFrom=180)
        self.bot.account["positions"].append(self.p)
        # Falling candles every 3 minutes: crosses 22.54 at t=1080 (opens 22.96), then far below.
        prices = [25.3, 25.0, 24.7, 24.2, 23.9, 23.4, 22.96, 21.0, 19.5, 18.0]
        self.all = [bar(180 * (i + 1), o, o + 0.05, o - 1.6 if o == 22.96 else o - 0.3, o - 0.2)
                    for i, o in enumerate(prices)]
        self.all += [bar(180 * (11 + i), 17.0, 17.1, 16.6, 16.9) for i in range(70)]

    async def test_missed_hours_are_read_from_history_and_the_stop_fills_at_its_price(self):
        self.recent_rows = self.all[-60:]          # the bot woke up: only the last 60 candles
        self.history_rows = self.all
        now = self.all[-1]["time"] + 200
        self.bot.now = lambda: now
        await self.bot._watch_positions(now)
        t = self.bot.account["closed"][-1]
        self.assertEqual((t["exitPrice"], t["exitReason"]), (22.54, "stop"))   # not 17.0
        self.assertGreater(t["pnl"], -2.7)
        blind = [e for e in self.bot.account["events"] if e["kind"] == "blind"][-1]
        self.assertEqual((blind["filled"], blind["start"]), (True, 180))

    async def test_without_the_missing_candles_the_stop_still_fills_at_its_own_price(self):
        self.recent_rows = self.all[-60:]
        self.history_rows = []                      # the exchange did not give them
        now = self.all[-1]["time"] + 200
        self.bot.now = lambda: now
        await self.bot._watch_positions(now)
        t = self.bot.account["closed"][-1]
        self.assertEqual((t["exitPrice"], t["exitReason"]), (22.54, "stop"))
        self.assertFalse([e for e in self.bot.account["events"] if e["kind"] == "blind"][-1]["filled"])

    async def test_watching_normally_nothing_changes(self):
        self.recent_rows = self.all[:6]             # every candle seen, none past the stop yet
        await self.bot._watch_positions(self.all[5]["time"] + 200)
        self.assertEqual(self.bot.account["positions"], [self.p])
        self.assertFalse([e for e in self.bot.account["events"] if e["kind"] == "blind"])


class OwnersDesignTest(unittest.IsolatedAsyncioTestCase):
    """The owner's design of 2026-11-07: trend from the higher timeframe, Bitcoin link, 6 trades, time break-even."""
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.hist = {}

        async def history(symbol, tf):
            return self.hist.get((symbol, tf), [])

        async def recent(symbol, tf):
            return [bar(999_960, 100, 100, 100, 100)]

        async def coins():
            return []
        self.bot = pp.PaperBot(pp.Store(Path(self.dir.name) / "p.json"), coins, history, recent,
                               now=lambda: 1_000_000, fees=FEES)
        self.bot.reset(100)

    @staticmethod
    def series(start, step, n=40, tf=3600, wiggle=0.0, t0=800_000):
        """Closed 1h candles going up (step > 0), down, or sideways (step 0 with a wiggle)."""
        out, p = [], start
        for i in range(n):
            p = p + step + (wiggle if i % 2 else -wiggle)
            out.append(bar(t0 + i * tf, p, p, p, p))
        return out

    def test_trend_from_the_efficiency_ratio(self):
        self.assertEqual(pp.trend_of(self.series(100, 1)), "up")
        self.assertEqual(pp.trend_of(self.series(100, -1)), "down")
        self.assertEqual(pp.trend_of(self.series(100, 0, wiggle=2)), "range")   # back and forth
        self.assertIsNone(pp.trend_of(self.series(100, 1, n=10)))               # too few candles

    def test_bitcoin_correlation(self):
        import random
        rnd = random.Random(1)
        btc, same, own, p, q, r = [], [], [], 100.0, 50.0, 10.0
        for i in range(400):
            m = rnd.gauss(0, 0.01)
            p *= 1 + m
            q *= 1 + m + rnd.gauss(0, 0.002)
            r *= 1 + rnd.gauss(0, 0.01)
            btc.append(bar(i * 3600, p, p, p, p))
            same.append(bar(i * 3600, q, q, q, q))
            own.append(bar(i * 3600, r, r, r, r))
        self.assertGreater(pp.btc_correlation(same, btc), 0.9)
        self.assertLess(abs(pp.btc_correlation(own, btc)), 0.2)
        self.assertIsNone(pp.btc_correlation(own[:50], btc))

    async def test_only_with_the_higher_trend_and_with_bitcoin_for_followers(self):
        bot, c = self.bot, cand("A", 2.0, 20)                       # a long on 15m: the trend comes from 1h
        self.hist[("A/USDT:USDT", "1h")] = self.series(100, 0, wiggle=2)
        self.assertFalse(await bot._direction_ok(c, "15m", 1_000_000))
        self.assertEqual(bot.account["events"][-1]["reason"], "range")
        self.hist[("A/USDT:USDT", "1h")] = self.series(100, -1)
        self.assertFalse(await bot._direction_ok(cand("A", 2.0, 20), "15m", 1_000_000))
        self.assertEqual(bot.account["events"][-1]["reason"], "against")
        self.hist[("A/USDT:USDT", "1h")] = self.series(100, 1)
        bot.btc_links["A/USDT:USDT"] = (1_000_000, 0.05)            # independent: its own trend is enough
        self.assertTrue(await bot._direction_ok(cand("A", 2.0, 20), "15m", 1_000_000))
        bot.btc_links["A/USDT:USDT"] = (1_000_000, 0.7)             # follows Bitcoin
        self.hist[("BTC/USDT:USDT", "1h")] = self.series(80_000, 0, wiggle=200)
        self.assertFalse(await bot._direction_ok(cand("A", 2.0, 20), "15m", 1_000_000))
        self.assertEqual(bot.account["events"][-1]["reason"], "btcFlat")
        self.hist[("BTC/USDT:USDT", "1h")] = self.series(80_000, -100)
        self.assertFalse(await bot._direction_ok(cand("A", 2.0, 20), "15m", 1_000_000))
        self.assertEqual(bot.account["events"][-1]["reason"], "btcAgainst")
        self.hist[("BTC/USDT:USDT", "1h")] = self.series(80_000, 100)
        c = cand("A", 2.0, 20)
        self.assertTrue(await bot._direction_ok(c, "15m", 1_000_000))
        self.assertEqual((c["trend"], c["btcLink"], c["btcTrend"]), ("up", 0.7, "up"))
        # 1h trades read the 4h chart
        self.hist[("A/USDT:USDT", "4h")] = self.series(100, -1, tf=14400, t0=1_000_000 - 41 * 14400)
        self.assertFalse(await bot._direction_ok(cand("A", 2.0, 20), "1h", 1_000_000))

    async def test_at_most_six_open_trades(self):
        bot = self.bot
        for n in range(6):
            bot.account["positions"].append(position(id=100 + n, symbol=f"X{n}/USDT:USDT", quantity=0.1,
                                                     notional=10, margin=2, entryFee=0.006))
        await bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        self.assertEqual(len(bot.account["positions"]), 6)
        self.assertEqual(bot.account["events"][-1]["reason"], "full")
        self.assertEqual(bot.public()["rules"]["maxOpen"], 6)

    def test_break_even_after_twelve_candles(self):
        # 5m long at 100, stop 99, target 102, break-even price about 100.12
        p = position(timeframe="5m", entryCandle=0, checkedFrom=0, breakevenPart=0, breakevenPrice=100.12)
        flat = [bar(0, 100, 100, 100, 100)] + [bar(300 * i, 99.8, 100.05, 99.6, 99.8) for i in range(1, 13)]
        self.assertIsNone(pp.check_exit(p, flat, 99.8, 300, now=300 * 13 + 1))
        self.assertEqual((p["beExit"], p["stop"]), (100.12, 99))           # in loss after 12: aims at break-even
        flat.append(bar(300 * 13, 99.8, 100.2, 99.7, 100.1))               # comes back to the entry
        self.assertEqual(pp.check_exit(p, flat, 100.1, 300, now=300 * 14 + 1), (100.12, "timeBe"))
        q = position(timeframe="5m", entryCandle=0, checkedFrom=0, breakevenPart=0, breakevenPrice=100.12)
        up = [bar(0, 100, 100, 100, 100)] + [bar(300 * i, 100.5, 100.9, 100.4, 100.6) for i in range(1, 13)]
        self.assertIsNone(pp.check_exit(q, up, 100.6, 300, now=300 * 13 + 1))
        self.assertEqual((q["stop"], q.get("beExit")), (100.12, None))     # in profit: the stop to break-even
        self.assertEqual(pp.trade_outcome({"exitReason": "timeBe", "pnl": -0.001, "notional": 50}), "even")
        h = position(timeframe="1h", entryCandle=0, checkedFrom=0, breakevenPart=0, breakevenPrice=100.12)
        hours = [bar(0, 100, 100, 100, 100)] + [bar(3600 * i, 99.8, 100.05, 99.6, 99.8) for i in range(1, 14)]
        pp.check_exit(h, hours, 99.8, 3600, now=3600 * 14 + 1)
        self.assertNotIn("beExit", h)                                      # not on 1h (no effect there)


class LockPointAndWhyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

        async def recent(symbol, tf):
            return [bar(999_960, 100, 100, 100, 100)]

        async def empty(*a):
            return []
        self.bot = pp.PaperBot(pp.Store(Path(self.dir.name) / "p.json"), empty, empty, recent,
                               now=lambda: 1_000_000, fees=FEES)
        self.bot.reset(100)

    async def test_entry_reason_is_kept(self):
        c = cand("A", 2.0, 20)
        c.update(marketState="trend_up", trend="up", btcLink=0.1)
        await self.bot._open(c, "15m", 1_000_000, {"fee_ratio": 0.33})
        p = self.bot.account["positions"][0]
        w = p["why"]
        self.assertEqual((w["signalPrice"], w["marketState"], w["higherTf"]), (100, "trend_up", "1h"))
        self.assertAlmostEqual(w["reward"], 2.0)                       # entry 100, stop 99, target 102
        self.assertAlmostEqual(w["feeShare"], 0.0012 * 100 / 1)
        self.assertEqual((p["trend"], p["btcLink"]), ("up", 0.1))

    async def test_lock_point_of_one_position(self):
        bot = self.bot
        await bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        p = bot.account["positions"][0]
        self.assertEqual(bot.set_lock_point(p["id"], 101.2), "lock_off")
        bot.set_lock(True, 80, 40)
        self.assertEqual(bot.set_lock_point(p["id"], 103), "lock_side")    # past the target (102)
        self.assertIsNone(bot.set_lock_point(p["id"], 101.2))               # 60% of the way
        self.assertAlmostEqual(p["lockOwn"]["trigger"], 0.6)
        self.assertAlmostEqual(p["lockOwn"]["at"], 0.3)                      # same ratio as 80 -> 40
        await bot._watch_positions(1_000_000)                                # kept, not overwritten by the panel's
        self.assertAlmostEqual(p["lock"]["trigger"], 0.6)
        p["lockedAt"] = 1
        self.assertEqual(bot.set_lock_point(p["id"], 101.4), "lock_done")
        self.assertEqual(bot.set_lock_point(999, 101), "missing")


class TelegramTest(unittest.IsolatedAsyncioTestCase):
    """Owner 2026-11-09: a Telegram message for every closed position; the token never goes to the screen."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.sent: list[tuple[str, dict]] = []

        async def post(url, body):
            self.sent.append((url, body))
            if url.endswith("/getUpdates"):
                return 200, json.dumps({"ok": True, "result": [{"message": {"chat": {"id": 42}, "text": "/start"}}]})
            return 200, json.dumps({"ok": True, "result": {}})
        self.post = post

        async def recent(symbol, tf):
            return [bar(999_960, 100, 100, 100, 100)]

        async def empty(*a):
            return []
        self.bot = pp.PaperBot(pp.Store(Path(self.dir.name) / "p.json"), empty, empty, recent,
                               now=lambda: 1_000_000, fees=FEES)
        self.bot.tg_post = post
        self.bot.reset(100)
        tg.save(token="", chatId=None, enabled=True)

    async def test_test_finds_chat_and_close_sends_message(self):
        tg.save(token="123:ABC-secret", chatId=None)
        shown = tg.public()
        self.assertEqual((shown["token"], shown["chat"]), (True, False))
        self.assertNotIn("ABC-secret", json.dumps(self.bot.public()))      # the token is never shown
        await tg.test(self.post)
        self.assertEqual(tg.load()["chatId"], 42)
        self.assertEqual(self.sent[-1][1]["chat_id"], 42)
        await self.bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        p = self.bot.account["positions"][0]
        self.bot._close(p, 102, "target", 1_000_100)
        await asyncio.gather(*list(self.bot._tg_tasks))
        text = self.sent[-1][1]["text"]
        self.assertIn("حد سود", text)
        self.assertIn("🟢", text)
        self.assertIn("R)", text)

    async def test_nothing_sent_without_chat_or_when_off(self):
        tg.save(token="123:ABC", chatId=None)
        self.bot.notify("x")
        tg.save(chatId=42, enabled=False)
        self.bot.notify("x")
        self.assertFalse(self.bot._tg_tasks)
        self.assertEqual(self.sent, [])

    async def test_test_without_start_says_so(self):
        tg.save(token="123:ABC", chatId=None)

        async def no_updates(url, body):
            return 200, json.dumps({"ok": True, "result": []})
        with self.assertRaises(tg.TelegramError):
            await tg.test(no_updates)

    def test_closed_text_loss(self):
        text = tg.closed_text({"pnl": -1.5, "risk": 1.0, "side": "short", "exitReason": "stop", "base": "SOL",
                               "timeframe": "1h", "strategy": "x", "entryPrice": 10, "exitPrice": 10.2}, 98.5)
        self.assertIn("🔴", text)
        self.assertIn("−1.50$", text)
        self.assertIn("-1.50R", text)
        self.assertIn("شورت", text)


class ReviewTest(TelegramTest):
    """Owner 2026-11-09: long positions looked at again (per timeframe); trend turned -> in profit closed,
    in a loss the owner decides on Telegram (close / go on); the open message is short."""
    # only the set-up of TelegramTest, not its tests
    test_test_finds_chat_and_close_sends_message = test_nothing_sent_without_chat_or_when_off = None
    test_test_without_start_says_so = test_closed_text_loss = None

    async def asyncSetUp(self):
        tg.save(token="123:ABC", chatId=42, enabled=True)
        self.trend = "down"
        self.state = None

        async def trend(symbol, tf, now):
            return self.trend

        async def opinion(p, now):
            return "hold", "fine", "", self.state
        self.bot._trend = trend
        self.bot._bot_opinion = opinion
        self.bot.ai_keys = lambda: []
        await self.bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        await asyncio.gather(*list(self.bot._tg_tasks))
        self.p = self.bot.account["positions"][0]

    async def flush(self):
        await asyncio.gather(*list(self.bot._tg_tasks))

    async def test_open_message_is_short(self):
        text = self.sent[-1][1]["text"]
        self.assertIn("باز شد", text)
        self.assertIn(str(self.p["entryPrice"]), text)
        self.assertNotIn("سود:", text)

    def test_due_after_20_candles_then_every_15_minutes(self):
        start = self.p["entryTime"]
        self.assertFalse(self.bot._review_due(self.p, start + 19 * 900))
        self.assertTrue(self.bot._review_due(self.p, start + 20 * 900))
        self.p["review"] = {"time": start + 20 * 900}
        self.assertFalse(self.bot._review_due(self.p, start + 20 * 900 + 14 * 60))
        self.assertTrue(self.bot._review_due(self.p, start + 20 * 900 + 15 * 60))
        self.bot.set_review(enabled=False)
        self.assertFalse(self.bot._review_due(self.p, start + 99 * 900))
        self.bot.set_review(enabled=True, after=5, every={"15m": 30, "1d": 9, "4h": 0})
        self.assertEqual(self.bot.public()["review"]["every"]["15m"], 30)
        self.assertEqual(self.bot.public()["review"]["every"]["4h"], 1)     # at least one minute
        self.assertNotIn("1d", self.bot.public()["review"]["every"])
        self.assertEqual(self.bot.public()["review"]["after"], 5)

    async def test_trend_turned_in_profit_closes(self):
        await self.bot._review(self.p, self.p["entryPrice"] * 1.01, 2_000_000)
        await self.flush()
        self.assertFalse(self.bot.account["positions"])
        self.assertEqual(self.bot.account["closed"][-1]["exitReason"], "review")
        self.assertIn("بررسی دوره‌ای", self.sent[-1][1]["text"])

    async def test_trend_same_way_goes_on(self):
        self.trend = "up"
        await self.bot._review(self.p, self.p["entryPrice"] * 1.01, 2_000_000)
        self.assertEqual(len(self.bot.account["positions"]), 1)
        self.assertFalse(self.p["review"]["against"])

    async def test_ai_says_hold_goes_on(self):
        self.bot.ai_keys = lambda: ["k"]

        async def consult(position_id):
            return {"ai": {"action": "hold"}}
        self.bot.consult = consult
        await self.bot._review(self.p, self.p["entryPrice"] * 1.01, 2_000_000)
        self.assertEqual(len(self.bot.account["positions"]), 1)
        self.assertEqual(self.p["review"]["ai"], "hold")

    async def test_loss_asks_on_telegram_then_buttons(self):
        await self.bot._review(self.p, self.p["entryPrice"] * 0.995, 2_000_000)
        await self.flush()
        self.assertEqual(len(self.bot.account["positions"]), 1)
        body = self.sent[-1][1]
        self.assertIn("ببندم یا ادامه", body["text"])
        datas = [b["callback_data"] for b in body["reply_markup"]["inline_keyboard"][0]]
        self.assertEqual(datas, [f"close:{self.p['id']}", f"hold:{self.p['id']}"])

        taps = [{"update_id": 7, "callback_query": {"id": "q1", "data": f"hold:{self.p['id']}", "message": {"chat": {"id": 42}}}},
                {"update_id": 8, "callback_query": {"id": "q2", "data": f"close:{self.p['id']}", "message": {"chat": {"id": 99}}}}]

        async def post(url, body):
            self.sent.append((url, body))
            if url.endswith("/getUpdates"):
                return 200, json.dumps({"ok": True, "result": taps if "offset" not in body else []})
            return 200, json.dumps({"ok": True, "result": True})
        self.bot.tg_post = post
        tg._offset.clear()
        await self.bot._telegram_answers(3_000_000)
        self.assertEqual(len(self.bot.account["positions"]), 1)        # hold; the other chat's tap is ignored
        self.assertEqual(self.p["reviewAsk"]["answer"], "hold")
        taps[:] = [{"update_id": 9, "callback_query": {"id": "q3", "data": f"close:{self.p['id']}", "message": {"chat": {"id": 42}}}}]
        tg._offset.clear()
        await self.bot._telegram_answers(3_000_010)
        self.assertFalse(self.bot.account["positions"])
        self.assertEqual(self.bot.account["closed"][-1]["exitReason"], "review")



class TelegramAskTest(TelegramTest):
    """Owner 2026-11-09: the fixed buttons «وضعیت ربات» / «پوزیشن‌های باز» (or /status, /positions) answer,
    also while the bot is stopped; only the owner's chat."""
    test_test_finds_chat_and_close_sends_message = test_nothing_sent_without_chat_or_when_off = None
    test_test_without_start_says_so = test_closed_text_loss = None

    async def ask(self, text, chat=42):
        updates = [{"update_id": 50, "message": {"chat": {"id": chat}, "text": text}}]

        async def post(url, body):
            self.sent.append((url, body))
            if url.endswith("/getUpdates"):
                return 200, json.dumps({"ok": True, "result": updates if "offset" not in body else []})
            return 200, json.dumps({"ok": True, "result": True})
        self.bot.tg_post = post
        tg._offset.clear()
        self.sent.clear()
        await self.bot._telegram_answers(1_000_600)
        return [b for u, b in self.sent if u.endswith("/sendMessage")]

    async def test_status_and_positions(self):
        tg.save(token="123:ABC", chatId=42, enabled=True)
        await self.bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        self.bot.prices[self.bot.account["positions"][0]["id"]] = 101
        sent = await self.ask(tg.STATUS_BUTTON)
        self.assertIn("موجودی", sent[0]["text"])
        self.assertIn("پوزیشن باز: 1", sent[0]["text"])
        self.assertEqual(sent[0]["reply_markup"], tg.KEYBOARD)
        sent = await self.ask("/positions")
        self.assertIn("A 15m لانگ", sent[0]["text"])
        self.assertIn("R)", sent[0]["text"])
        self.assertIn("باز از 10 دقیقه", sent[0]["text"])
        self.assertEqual(await self.ask("/status", chat=99), [])   # someone else's chat: no answer
        sent = await self.ask("سلام")
        self.assertIn("دو دکمه", sent[0]["text"])

    def test_no_positions(self):
        self.assertEqual(tg.positions_text([], 0), "هیچ پوزیشن بازی نیست.")



class MinuteExitTest(unittest.TestCase):
    """Audit 2026-11-09: inside the forming candle the stop fills at the stop (minute by minute), like an
    exchange stop order, not at the price the bot happened to see later."""

    def pos(self, **kw):
        p = {"side": "short", "entryPrice": 1.1434, "entryTime": 1000.0, "entryCandle": 900, "checkedFrom": 1800,
             "stop": 1.1, "takeProfit": 0.948, "lockedAt": 900}
        p.update(kw)
        return p

    def m(self, t, o, h, low, c):
        return {"time": t, "open": o, "high": h, "low": low, "close": c}

    def test_stop_inside_a_minute_fills_at_the_stop(self):
        minutes = [self.m(1800, 1.09, 1.095, 1.08, 1.09), self.m(1860, 1.0915, 1.125, 1.09, 1.121)]
        self.assertEqual(pp.check_minutes(self.pos(), minutes, 1925), (1.1, "lock"))   # not 1.121

    def test_gap_fills_at_the_minute_open(self):
        minutes = [self.m(1800, 1.12, 1.13, 1.11, 1.12)]
        self.assertEqual(pp.check_minutes(self.pos(), minutes, 1830), (1.12, "lock"))

    def test_entry_minute_and_checked_minutes_left_out(self):
        p = self.pos(entryTime=1810.0, checkedFrom=1800)
        minutes = [self.m(1800, 1.09, 1.2, 1.08, 1.09), self.m(1860, 1.09, 1.095, 1.08, 1.09)]
        self.assertIsNone(pp.check_minutes(p, minutes, 1930))     # 1800 holds the entry: not counted
        self.assertEqual(p["checkedMinute"], 1920)
        minutes.append(self.m(1920, 1.09, 1.0, 1.0, 1.0))
        self.assertIsNone(pp.check_minutes(p, [self.m(1860, 1.2, 1.3, 1.2, 1.2)], 1990))   # already checked

    def test_target_and_lock_from_minutes(self):
        p = self.pos(stop=1.2, lockedAt=None, lock={"trigger": 0.8, "at": 0.4})
        way = p["takeProfit"] - p["entryPrice"]
        low = p["entryPrice"] + way * 0.85
        self.assertIsNone(pp.check_minutes(p, [self.m(1800, 1.1, 1.1, low, 1.1)], 1900))
        self.assertAlmostEqual(p["stop"], p["entryPrice"] + way * 0.4)
        self.assertEqual(pp.check_minutes(p, [self.m(1860, 1.0, 1.0, 0.94, 0.95)], 1950), (0.948, "target"))


class EvenTradesTest(unittest.TestCase):
    """Owner 2026-11-09: break-even trades are neither won nor lost."""

    def test_outcome(self):
        base = {"notional": 10.0, "pnl": 8e-16, "exitReason": "breakeven"}
        self.assertEqual(pp.trade_outcome(base), "even")
        self.assertEqual(pp.trade_outcome({**base, "exitReason": "timeBe", "pnl": -1e-15}), "even")
        self.assertEqual(pp.trade_outcome({**base, "exitReason": "stop", "pnl": -1.0}), "loss")


class TelegramManageTest(TelegramAskTest):
    """Owner 2026-11-09: each open position managed from Telegram."""
    test_status_and_positions = test_no_positions = None

    async def tap(self, data, chat=42):
        return await self.ask_update({"update_id": 60, "callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat}}}})

    async def ask_update(self, update):
        async def post(url, body):
            self.sent.append((url, body))
            if url.endswith("/getUpdates"):
                return 200, json.dumps({"ok": True, "result": [update] if "offset" not in body else []})
            return 200, json.dumps({"ok": True, "result": True})
        self.bot.tg_post = post
        tg._offset.clear()
        self.sent.clear()
        await self.bot._telegram_answers(1_000_600)
        return [b for u, b in self.sent if u.endswith("/sendMessage")]

    async def test_list_edit_breakeven_close(self):
        tg.save(token="123:ABC", chatId=42, enabled=True)
        await self.bot._open(cand("A", 2.0, 20), "15m", 1_000_000, {"fee_ratio": 0.33})
        p = self.bot.account["positions"][0]
        self.bot.prices[p["id"]] = p["entryPrice"] * 1.005
        sent = await self.ask("/positions")
        self.assertEqual(sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], f"pos:{p['id']}")
        sent = await self.tap(f"pos:{p['id']}")
        datas = [b["callback_data"] for row in sent[0]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn(f"est:{p['id']}", datas)
        # new stop: the price comes as the next message (wrong side first)
        await self.tap(f"est:{p['id']}")
        sent = await self.ask_update({"update_id": 61, "message": {"chat": {"id": 42}, "text": str(p["entryPrice"] * 1.01)}})
        self.assertIn("سمت ضرر", sent[0]["text"])
        new = round(p["entryPrice"] * 0.995, 6)
        sent = await self.ask_update({"update_id": 62, "message": {"chat": {"id": 42}, "text": str(new)}})
        self.assertIn("✅", sent[0]["text"])
        self.assertAlmostEqual(p["stop"], new)
        self.assertEqual(p["edits"][-1]["what"], "stop")
        # break-even (in profit)
        await self.tap(f"pbe:{p['id']}")
        self.assertAlmostEqual(p["stop"], p["breakevenPrice"])
        # close: asked again first
        sent = await self.tap(f"pcl:{p['id']}")
        self.assertEqual(len(self.bot.account["positions"]), 1)
        self.assertEqual(sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], f"pcy:{p['id']}")

        async def recent(symbol, tf):
            return [bar(1_000_500, 100.5, 100.5, 100.5, 100.5)]
        self.bot.recent = recent
        await self.tap(f"pcy:{p['id']}")
        self.assertFalse(self.bot.account["positions"])
        self.assertEqual(self.bot.account["closed"][-1]["exitReason"], "manual")
        # someone else's chat cannot touch anything
        self.assertEqual(await self.tap("pos:1", chat=99), [])



class AnchorTargetTest(unittest.TestCase):
    """Owner 2026-11-10: the target is counted from the real entry (the strategy's own reward:risk)."""

    def test_better_entry_brings_the_target_closer(self):
        self.assertAlmostEqual(pp.anchor_target("long", 100, 99.5, 99, 102), 100.5)     # 2R of 0.5
        self.assertAlmostEqual(pp.anchor_target("short", 100, 100.5, 101, 98), 99.5)

    def test_never_further_than_the_signal_target_and_capped(self):
        self.assertAlmostEqual(pp.anchor_target("long", 100, 100.05, 99, 102), 102)     # worse entry: not further
        self.assertAlmostEqual(pp.anchor_target("long", 100, 100, 99, 110), 104)        # at most 4R

    def test_levels_that_make_no_sense(self):
        self.assertIsNone(pp.anchor_target("short", 0.0026, 0.0026, 0.0043, -0.0012))   # target below zero
        self.assertIsNone(pp.anchor_target("long", 100, 98.9, 99, 102))                 # entry past the stop
