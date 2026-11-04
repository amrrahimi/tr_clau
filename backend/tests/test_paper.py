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
        # Signal at 100 with the stop at 99: 100.3 is more than a quarter of the stop distance away.
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.3, 100, 100.3)]
        await bot._open(cand("A", 2.0, 20), "15m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(bot.account["positions"], [])
        self.assertEqual((bot.account["events"][-1]["kind"], bot.account["events"][-1]["reason"]), ("skip", "stale"))
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.2, 100, 100.2)]   # within a quarter: taken
        await bot._open(cand("A", 2.0, 20), "15m", self.clock[0], {"fee_ratio": 0.33})
        self.assertEqual(len(bot.account["positions"]), 1)
        self.assertTrue(pp.is_stale(100, 99.7, 99))
        self.assertFalse(pp.is_stale(100, 99.8, 99))

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

    async def test_every_signal_is_remembered_but_only_reliable_ones_traded(self):
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

    async def test_half_way_advice_and_the_owners_answer(self):
        from unittest import mock
        bot = self.bot
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
