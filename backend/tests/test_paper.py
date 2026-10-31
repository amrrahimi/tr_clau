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
    def test_fast_and_slow_places_are_separate(self):
        positions = [{"timeframe": "1m", "side": LONG}, {"timeframe": "5m", "side": LONG}, {"timeframe": "3m", "side": SHORT}]
        self.assertEqual(pp.free_slots(positions, "1m"), 0)       # fast places full
        self.assertEqual(pp.free_slots(positions, "1h"), 3)       # slow places still free
        self.assertEqual(pp.side_room(positions), {"long": 2, "short": 3})

    def test_at_most_four_in_one_direction(self):
        cs = [cand(c, 3.0 - i * 0.1, 20) for i, c in enumerate("ABCDEF")]
        chosen = pp.pick(cs, set(), 6, {"long": 4, "short": 4})
        self.assertEqual([c["base"] for c in chosen], ["A", "B", "C", "D"])
        mixed = cs[:3] + [cand("S", 1.1, 20, SHORT)]
        self.assertEqual([c["base"] for c in pp.pick(mixed, set(), 3, {"long": 1, "short": 4})], ["A", "S"])


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
        self.assertEqual([tf for tf, _ in scanned], ["1h", "15m", "5m", "3m", "1m"])   # biggest first
        self.assertTrue(all(trade for _, trade in scanned))
        await bot.step()
        self.assertEqual(len(scanned), 5)                             # same candles: no new scan
        self.clock[0] += 60
        await bot.step()
        self.assertIn(("1m", True), scanned[5:])

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
        memory.db.execute("INSERT INTO signals (key, strategy, status, exit_time, pnl_percent) VALUES"
                          " ('a', 'donchian', 'loss', ?, -1.5), ('b', 'supertrend', 'win', ?, 2.0)",
                          (self.clock[0] - 100, self.clock[0] - 100))
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
        self.assertEqual(len(scanned), 5)
        self.assertFalse(any(trade for _, trade in scanned))

    async def test_brain_skips_weak_signals_and_remembers_why(self):
        from unittest import mock
        from app.memory import Memory

        memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(memory.close)

        class Picky:   # a brain that thinks every signal is weak
            def chance(self, feats, strategy, tf, side):
                return 0.1

            def allows(self, chance):
                return chance is None or chance >= 0.5

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
        self.assertEqual(bot.pretrain_progress, {"done": 5, "total": 5, "running": False})
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

    async def test_fast_account_follows_every_signal_and_takes_tiny_profits(self):
        async def coins():
            return [("A/USDT:USDT", "A")]

        async def history(symbol, tf):
            return []

        async def recent(symbol, tf):
            return self.recent_rows.get(symbol, [])
        fast = pp.PaperBot(pp.Store(Path(self.dir.name) / "fast.json"), coins, history, recent,
                           now=lambda: self.clock[0], fees=FEES, profile=pp.FAST)
        self.assertEqual(fast.account["profitCap"], 0.05)
        weak = {**cand("A", 0.5, 20), "reliable": False}                 # not reliable: fine for this account
        await fast.follow("1m", [weak], self.clock[0])
        self.assertEqual(fast.account["positions"], [])                   # switched off: nothing
        fast.start()
        await fast.follow("15m", [weak], self.clock[0])
        self.assertEqual(fast.account["positions"], [])                   # not one of its charts
        await fast.follow("1m", [weak], self.clock[0])
        self.assertEqual(len(fast.account["positions"]), 1)
        self.recent_rows["A/USDT:USDT"] = [bar(999_960, 100, 100.2, 100, 100.2)]
        await fast.step()
        self.assertEqual(fast.account["closed"][-1]["exitReason"], "cap")
        self.assertEqual(fast.public()["rules"]["maxOpen"], 10)

    async def test_main_bot_hands_its_signals_to_followers(self):
        from unittest import mock
        got = []

        class Follower:
            async def follow(self, tf, entries, now):
                got.append((tf, [e["reliable"] for e in entries]))
        bot = self.bot
        bot.followers.append(Follower())
        bot.reset(100)
        weak = cand("A", 0.5, 20)
        overview = {"marketState": "trend_up", "adx": 30, "atrRatio": 1,
                    "rows": [{"strategy": "ema_cross", "stats": weak["stats"], "signal": weak["signal"]}]}
        with mock.patch.object(pp, "strategy_overview", return_value=overview):
            await bot._scan_and_open("1m", self.clock[0], trade=False)
        self.assertEqual(got, [("1m", [False])])

    def test_slow_charts_need_a_much_better_record(self):
        good = cand("A", 2.0, 25)
        self.assertTrue(pp.strict_ok(good, "1h"))
        self.assertFalse(pp.strict_ok(cand("A", 1.3, 25), "1h"))      # profit factor too low for 1h
        self.assertFalse(pp.strict_ok(cand("A", 2.0, 12), "15m"))     # too few trades for 15m
        self.assertTrue(pp.strict_ok(cand("A", 1.3, 12), "5m"))       # the fast charts keep the normal rule

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
        self.assertEqual({tf: pp.bot_settings(tf)["donchian"]["breakeven"] for tf in pp.TIMEFRAMES},
                         {"1m": 0.0, "3m": 0.0, "5m": 0.0, "15m": 0.0, "1h": 0.5})


if __name__ == "__main__":
    unittest.main()
