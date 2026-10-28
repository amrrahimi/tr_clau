import json
import math
import unittest

from app import indicators as ind
from app import strategies as st
from app.analysis import run_strategy, strategy_overview
from app import history
from app.catalog import Candles, parse_instances
from app.strategies import LONG, SHORT, Signal


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def wave(n=800):
    """Real-looking data: waves with a slow drift, so every strategy finds signals."""
    out = []
    prev = 100.0
    for i in range(n):
        close = 100 + 12 * math.sin(i / 25) + 4 * math.sin(i / 6) + 3 * math.sin(i / 80) * (i / 200)
        out.append(bar(i * 60, prev, max(prev, close) + 0.6, min(prev, close) - 0.6, close))
        prev = close
    return out


def as_candles(rows):
    return Candles([r["open"] for r in rows], [r["high"] for r in rows], [r["low"] for r in rows],
                   [r["close"] for r in rows], [1.0] * len(rows))


class EngineTest(unittest.TestCase):
    """The common rules, checked by hand."""

    def setUp(self):
        self.signal = bar(0, 100, 100, 100, 100)

    def test_long_win(self):
        rows = [self.signal, bar(60, 100, 101, 99.5, 100.5), bar(120, 100.5, 102.5, 100, 102)]
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_distance=1, reward=2)])
        t = trades[0]
        self.assertEqual((t["entryTime"], t["entryPrice"], t["stopLoss"], t["takeProfit"]), (60, 100, 99, 102))
        self.assertEqual((t["result"], t["exitTime"], t["exitPrice"]), ("win", 120, 102))
        self.assertAlmostEqual(t["pnlPercent"], 2.0)
        self.assertAlmostEqual(t["r"], 2.0)

    def test_stop_and_target_in_one_candle_is_a_loss(self):
        rows = [self.signal, bar(60, 100, 102.5, 98.5, 101)]
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_distance=1, reward=2)])
        self.assertEqual((trades[0]["result"], trades[0]["exitPrice"]), ("loss", 99))
        self.assertAlmostEqual(trades[0]["r"], -1.0)

    def test_gap_past_the_stop_fills_at_the_open(self):
        rows = [self.signal, bar(60, 100, 100.5, 99.5, 100), bar(120, 98, 98.5, 97, 98)]
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_distance=1, reward=2)])
        self.assertEqual(trades[0]["exitPrice"], 98)
        self.assertAlmostEqual(trades[0]["r"], -2.0)

    def test_short_trade_with_stop_price(self):
        rows = [self.signal, bar(60, 100, 100.5, 99.5, 99.8), bar(120, 99.8, 99.9, 98.9, 99)]
        trades, _ = st.simulate(rows, [Signal(0, SHORT, stop_price=101, reward=1)])
        t = trades[0]
        self.assertEqual((t["stopLoss"], t["takeProfit"], t["result"], t["exitPrice"]), (101, 99, "win", 99))
        self.assertAlmostEqual(t["pnlPercent"], 1.0)

    def test_one_position_at_a_time(self):
        rows = [self.signal, bar(60, 100, 100.5, 99.5, 100), bar(120, 100, 100.5, 99.5, 100), bar(180, 100, 102, 100, 102)]
        signals = [Signal(0, LONG, stop_distance=1, reward=2), Signal(1, LONG, stop_distance=1, reward=2)]
        trades, _ = st.simulate(rows, signals)
        self.assertEqual(len(trades), 1)

    def test_new_trade_after_the_previous_one_closes(self):
        rows = [self.signal, bar(60, 100, 100, 98, 98.5), bar(120, 98.5, 99, 98, 98.8), bar(180, 99, 99, 99, 99)]
        signals = [Signal(0, LONG, stop_distance=1, reward=2), Signal(1, SHORT, stop_distance=1, reward=1)]
        trades, _ = st.simulate(rows, signals)
        self.assertEqual([t["side"] for t in trades], [LONG, SHORT])
        self.assertEqual(trades[1]["entryTime"], 120)

    def test_stop_on_wrong_side_is_skipped(self):
        rows = [self.signal, bar(60, 100, 100, 100, 100)]
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_price=100.5, reward=2)])
        self.assertEqual(trades, [])
        # A fixed target that is not beyond the entry is skipped too.
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_price=99, target_price=99.5)])
        self.assertEqual(trades, [])

    def test_fixed_target_price(self):
        rows = [self.signal, bar(60, 100, 100.8, 99.5, 100.6)]
        trades, _ = st.simulate(rows, [Signal(0, LONG, stop_price=99, target_price=100.7)])
        self.assertEqual((trades[0]["result"], trades[0]["exitPrice"]), ("win", 100.7))

    def test_run_describes_a_signal_on_the_last_candle(self):
        rows = [bar(i * 60, 100, 101, 99, 100) for i in range(25)] + [bar(1500, 100, 103.5, 100, 103)]
        params = st.parse_params("donchian", {"state_filter": 0})
        result = st.run(rows, "donchian", params)
        s = result["signal"]
        self.assertEqual((s["side"], s["time"], s["entry"]), (LONG, 1500, 103))
        atr = (2 * 13 + 3.5) / 14
        self.assertAlmostEqual(s["stopLoss"], 103 - 2 * atr)
        self.assertAlmostEqual(s["takeProfit"], 103 + 2 * 2 * atr)
        self.assertIsNone(st.run(rows[:-1], "donchian", params)["signal"])

    def test_open_trade_and_signal_on_last_candle(self):
        rows = [self.signal, bar(60, 100, 100.5, 99.5, 100)]
        trades, pending = st.simulate(rows, [Signal(0, LONG, stop_distance=1, reward=2)])
        self.assertEqual(trades[0]["result"], "open")
        self.assertIsNone(pending)
        _, pending = st.simulate(rows, [Signal(1, SHORT, stop_distance=1, reward=2)])
        self.assertEqual(pending, SHORT)

    def test_stats_by_hand(self):
        trades = [{"result": "win", "pnlPercent": 2.0}, {"result": "win", "pnlPercent": 1.0},
                  {"result": "loss", "pnlPercent": -1.0}, {"result": "open", "pnlPercent": None}]
        s = st.stats(trades)
        self.assertEqual((s["trades"], s["wins"], s["losses"], s["open"]), (3, 2, 1, 1))
        self.assertAlmostEqual(s["winRate"], 200 / 3)
        self.assertAlmostEqual(s["profitFactor"], 3.0)
        self.assertAlmostEqual(s["netPercent"], 2.0)
        self.assertFalse(s["feesIncluded"])
        self.assertIsNone(st.stats(trades[:2])["profitFactor"])  # no loss yet
        self.assertIsNone(st.stats([])["winRate"])


class ExtraRulesTest(unittest.TestCase):
    """Break-even, time limit and market state, checked by hand."""

    def setUp(self):
        self.signal = bar(0, 100, 100, 100, 100)
        self.long = [Signal(0, LONG, stop_distance=1, reward=2)]  # entry 100, stop 99, target 102

    def test_stop_moves_to_entry_at_half_way(self):
        rows = [self.signal,
                bar(60, 100, 101.2, 99.5, 101),    # reaches 101 = half way to 102: stop moves (from next candle)
                bar(120, 101, 101.1, 99.9, 100.2)]  # back to the entry: closed at 100, no loss
        trades, _ = st.simulate(rows, self.long, breakeven=0.5)
        t = trades[0]
        self.assertEqual((t["result"], t["exitReason"], t["exitPrice"], t["breakevenTime"]), ("breakeven", "breakeven", 100, 60))
        self.assertEqual(t["stopLoss"], 99)  # the box keeps the original stop
        self.assertEqual(t["pnlPercent"], 0)
        # Without the rule the same trade is still open.
        self.assertEqual(st.simulate(rows, self.long)[0][0]["result"], "open")

    def test_break_even_does_not_count_in_the_same_candle(self):
        rows = [self.signal, bar(60, 100, 101.5, 99.95, 100)]  # half way and back in one candle
        trades, _ = st.simulate(rows, self.long, breakeven=0.5)
        self.assertEqual(trades[0]["result"], "open")

    def test_time_limit_closes_only_in_profit(self):
        flat_loss = [bar(60 * k, 99.6, 99.8, 99.5, 99.7) for k in range(1, 5)]   # below the entry
        rows = [self.signal] + flat_loss + [bar(300, 99.7, 100.6, 99.6, 100.5)]  # 5th candle closes in profit
        rows[1] = bar(60, 100, 100.2, 99.5, 99.7)
        trades, _ = st.simulate(rows, self.long, max_candles=3)
        t = trades[0]
        self.assertEqual((t["result"], t["exitReason"], t["exitTime"], t["exitPrice"]), ("win", "time", 300, 100.5))
        # Still in loss after the limit: the trade stays open.
        trades, _ = st.simulate(rows[:-1], self.long, max_candles=3)
        self.assertEqual(trades[0]["result"], "open")

    def test_stats_count_break_even_separately(self):
        s = st.stats([{"result": "win", "pnlPercent": 1.0}, {"result": "breakeven", "pnlPercent": 0.0},
                      {"result": "loss", "pnlPercent": -1.0}])
        self.assertEqual((s["trades"], s["wins"], s["losses"], s["breakevens"]), (3, 1, 1, 1))

    def test_market_state_rule(self):
        trend = ("trend_up", "trend_down")
        self.assertTrue(st.allowed_by_state(Signal(0, LONG), "trend_up", trend))
        self.assertFalse(st.allowed_by_state(Signal(0, SHORT), "trend_up", trend))
        self.assertTrue(st.allowed_by_state(Signal(0, SHORT), "trend_down", trend))
        self.assertFalse(st.allowed_by_state(Signal(0, LONG), "range", trend))
        self.assertTrue(st.allowed_by_state(Signal(0, SHORT), "range", ("range",)))
        self.assertFalse(st.allowed_by_state(Signal(0, LONG), "unknown", ("range", "volatile")))

    def test_run_uses_the_state_of_each_signal_candle(self):
        rows = wave(800)
        params = st.parse_params("ema_cross", {"max_candles": 0, "breakeven": 0}, "scalping")
        everything = st.run(rows, "ema_cross", {**params, "state_filter": 0})
        all_range = st.run(rows, "ema_cross", params, ["range"] * len(rows))
        all_up = st.run(rows, "ema_cross", params, ["trend_up"] * len(rows))
        self.assertTrue(everything["trades"])
        self.assertEqual(all_range["trades"], [])          # a trend strategy never trades in a range
        self.assertTrue(all(t["side"] == LONG for t in all_up["trades"]))
        self.assertTrue(all_up["trades"])


class FeesTest(unittest.TestCase):
    """Fees by hand: entry 100, stop 99, take-profit 102, both rates 0.1%."""

    def setUp(self):
        self.fees = st.Fees(maker=0.1, taker=0.1)
        self.signal = bar(0, 100, 100, 100, 100)
        self.long = [Signal(0, LONG, stop_distance=1, reward=2)]

    def test_win_pays_entry_fee_and_maker_exit_fee(self):
        rows = [self.signal, bar(60, 100, 102.5, 99.5, 102)]
        t = st.simulate(rows, self.long, fees=self.fees)[0][0]
        # 2% move - 0.1% entry fee - 0.1% of 102 (exit value) = 2 - 0.1 - 0.102
        self.assertAlmostEqual(t["pnlPercent"], 1.798)
        self.assertAlmostEqual(t["grossPercent"], 2.0)
        self.assertAlmostEqual(t["feePercent"], 0.202)

    def test_loss_pays_taker_on_both_sides(self):
        rows = [self.signal, bar(60, 100, 100.5, 98.5, 99)]
        t = st.simulate(rows, self.long, fees=self.fees)[0][0]
        self.assertAlmostEqual(t["pnlPercent"], -1.0 - 0.1 - 0.099)

    def test_break_even_price_covers_both_fees(self):
        level = st.breakeven_price(LONG, 100, self.fees)
        self.assertAlmostEqual(level, 100 * 1.001 / 0.999)
        self.assertAlmostEqual(st.net_percent(LONG, 100, level, 0.1, self.fees), 0)
        short = st.breakeven_price(SHORT, 100, self.fees)
        self.assertAlmostEqual(st.net_percent(SHORT, 100, short, 0.1, self.fees), 0)
        rows = [self.signal, bar(60, 100, 101.2, 99.5, 101), bar(120, 101, 101.1, 99.9, 100.2)]
        t = st.simulate(rows, self.long, breakeven=0.5, fees=self.fees)[0][0]
        self.assertEqual((t["result"], t["exitReason"]), ("breakeven", "breakeven"))
        self.assertAlmostEqual(t["exitPrice"], level)
        self.assertEqual(t["pnlPercent"], 0)

    def test_time_limit_needs_profit_after_fees(self):
        rows = [self.signal, bar(60, 100, 100.3, 99.5, 100.15), bar(120, 100.15, 100.3, 99.9, 100.15)]
        trades, _ = st.simulate(rows, self.long, max_candles=1, fees=self.fees)
        self.assertEqual(trades[0]["result"], "open")   # +0.15% is less than the 0.2% of fees
        rows.append(bar(180, 100.15, 100.6, 100.1, 100.5))
        trades, _ = st.simulate(rows, self.long, max_candles=1, fees=self.fees)
        self.assertEqual((trades[0]["result"], trades[0]["exitReason"]), ("win", "time"))

    def test_stats_sum_fees(self):
        rows = [self.signal, bar(60, 100, 102.5, 99.5, 102)]
        trades, _ = st.simulate(rows, self.long, fees=self.fees)
        s = st.stats(trades)
        self.assertTrue(s["feesIncluded"])
        self.assertAlmostEqual(s["feePercent"], 0.202)
        self.assertFalse(st.stats(st.simulate(rows, self.long)[0])["feesIncluded"])


class HandExamplesTest(unittest.TestCase):
    def test_channel_breakout(self):
        rows = [bar(i * 60, 100, 101, 99, 100) for i in range(25)] + [bar(1500, 100, 103.5, 100, 103)]
        p = st.parse_params("donchian", {})
        signals = st.STRATEGIES["donchian"].signals(as_candles(rows), p)
        self.assertEqual([(s.index, s.side) for s in signals], [(25, LONG)])
        # Every flat candle is 2 wide; the breakout candle's true range is 3.5.
        atr = (2 * 13 + 3.5) / 14
        self.assertAlmostEqual(signals[0].stop_distance, 2 * atr)
        self.assertEqual(signals[0].reward, 2)

    def test_bollinger_back_inside(self):
        rows = [bar(i * 60, 100.5, 101.2, 99.8, 100 if i % 2 else 101) for i in range(30)]
        rows += [bar(1800, 100, 100.2, 94.5, 95), bar(1860, 95, 100.8, 94.8, 100.5)]
        signals = st.STRATEGIES["bb_reversion"].signals(as_candles(rows), st.parse_params("bb_reversion", {}))
        self.assertEqual([(s.index, s.side) for s in signals], [(31, LONG)])
        self.assertEqual(signals[0].stop_price, 94.5)  # lowest of the two candles
        _, basis, _ = ind.bollinger([r["close"] for r in rows], 20, 2)
        self.assertAlmostEqual(signals[0].target_price, basis[31])


class RulesOnWaveDataTest(unittest.TestCase):
    """Every signal must satisfy its strategy's rule (checked independently)."""

    def setUp(self):
        self.rows = wave()
        self.c = as_candles(self.rows)
        self.closes = self.c.closes

    def signals(self, kind, **given):
        return st.STRATEGIES[kind].signals(self.c, st.parse_params(kind, given)), st.parse_params(kind, given)

    def test_ema_cross_finds_exactly_the_crossings(self):
        signals, p = self.signals("ema_cross", trend=50)
        fast, slow, trend = ind.ema(self.closes, 9), ind.ema(self.closes, 21), ind.ema(self.closes, 50)
        expected = []
        for i in range(50, len(self.closes)):
            up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i] and self.closes[i] > trend[i]
            down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i] and self.closes[i] < trend[i]
            if up or down:
                expected.append((i, LONG if up else SHORT))
        self.assertTrue(expected)
        self.assertEqual([(s.index, s.side) for s in signals], expected)

    def test_rsi_pullback_rule(self):
        signals, p = self.signals("rsi_pullback", trend=50)
        rsi, trend = ind.rsi(self.closes, 14), ind.ema(self.closes, 50)
        self.assertTrue(signals)
        for s in signals:
            i = s.index
            if s.side == LONG:
                self.assertTrue(self.closes[i] > trend[i] and rsi[i - 1] < 40 <= rsi[i])
            else:
                self.assertTrue(self.closes[i] < trend[i] and rsi[i - 1] > 60 >= rsi[i])

    def test_macd_rule(self):
        signals, p = self.signals("macd_ema", trend=50)
        line, signal, _ = ind.macd(self.closes)
        self.assertTrue(signals)
        for s in signals:
            i = s.index
            if s.side == LONG:
                self.assertTrue(line[i - 1] <= signal[i - 1] and line[i] > signal[i] and line[i] < 0)
                self.assertEqual(s.stop_price, min(self.c.lows[i - 9 : i + 1]))
            else:
                self.assertTrue(line[i - 1] >= signal[i - 1] and line[i] < signal[i] and line[i] > 0)
                self.assertEqual(s.stop_price, max(self.c.highs[i - 9 : i + 1]))

    def test_supertrend_rule(self):
        signals, p = self.signals("supertrend", trend=50)
        line, direction = ind.supertrend(self.c.highs, self.c.lows, self.closes, 10, 3.0)
        self.assertTrue(signals)
        for s in signals:
            i = s.index
            self.assertNotEqual(direction[i - 1], direction[i])
            self.assertEqual(s.side, LONG if direction[i] == -1 else SHORT)
            self.assertEqual(s.stop_price, line[i])

    def test_every_strategy_makes_sensible_trades(self):
        for kind in st.STRATEGIES:
            result = st.run(self.rows, kind, st.parse_params(kind, {}, "scalping"))
            closed = [t for t in result["trades"] if t["result"] != "open"]
            self.assertTrue(closed, kind)
            for t in result["trades"]:
                direction = 1 if t["side"] == LONG else -1
                self.assertGreater((t["entryPrice"] - t["stopLoss"]) * direction, 0, kind)
                self.assertGreater((t["takeProfit"] - t["entryPrice"]) * direction, 0, kind)
                self.assertGreater(t["entryTime"], t["signalTime"])
            # Trades never overlap: each one starts after the previous one ended.
            for a, b in zip(closed, closed[1:]):
                self.assertGreater(b["entryTime"], a["exitTime"] - 1)
            self.assertEqual(result["stats"]["trades"], len(closed))
            json.dumps(result)  # the answer can be sent as JSON


class CardsAndSettingsTest(unittest.TestCase):
    def test_six_strategies_with_valid_defaults(self):
        self.assertEqual(list(st.STRATEGIES), ["ema_cross", "macd_ema", "rsi_pullback", "bb_reversion",
                                               "supertrend", "donchian"])
        for s in st.STRATEGIES.values():
            for p in s.params:
                self.assertTrue(p.min <= p.default <= p.max, (s.type, p.name))

    def test_public_cards_are_json_without_formulas(self):
        text = json.dumps(st.public_strategies())
        self.assertNotIn("signals", text)
        cards = {c["type"]: c for c in st.public_strategies()}
        self.assertEqual(cards["ema_cross"]["modeDefaults"], {"trend": {"scalping": 50, "daily": 200}})
        self.assertEqual(list(cards["bb_reversion"]["states"]), ["range"])

    def test_trend_default_follows_trading_mode(self):
        self.assertEqual(st.parse_params("ema_cross", {}, "scalping")["trend"], 50)
        self.assertEqual(st.parse_params("ema_cross", {}, "daily")["trend"], 200)
        self.assertEqual(st.parse_params("ema_cross", {"trend": 100}, "scalping")["trend"], 100)

    def test_bad_settings_are_refused(self):
        for kind, given, words in [("nope", {}, "unknown strategy"), ("ema_cross", {"x": 1}, "unknown setting"),
                                   ("ema_cross", {"fast": 2.5}, "whole number"),
                                   ("ema_cross", {"reward": 50}, "between"),
                                   ("ema_cross", {"fast": "9"}, "must be a number")]:
            with self.assertRaises(ValueError) as error:
                st.parse_params(kind, given)
            self.assertIn(words, str(error.exception))

    def test_lines_are_valid_indicator_lists(self):
        for kind, s in st.STRATEGIES.items():
            parse_instances(s.lines(st.parse_params(kind, {})))

    def test_run_on_chart_drops_the_forming_candle_and_adds_lines(self):
        rows = wave(400)
        now = rows[-1]["time"] + 30   # last candle still forming
        result = run_strategy(rows, "1m", "ema_cross", st.parse_params("ema_cross", {}, "scalping"), "scalping", now=now)
        self.assertEqual(result["lastClosedTime"], rows[-2]["time"])
        self.assertEqual([i["label"] for i in result["indicators"]], ["EMA 9", "EMA 21", "EMA 50"])

    def test_preview_copy_matches_backend(self):
        """frontend/src/mockStrategies.ts (sample-data preview only) must match the real cards."""
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "mockStrategies.ts")
        if not os.path.exists(path):
            self.skipTest("frontend folder not present")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        copy = json.loads(text[text.index("= [") + 2 : text.rindex("]") + 1])
        self.assertEqual(copy, json.loads(json.dumps(st.public_strategies())))


class HistoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.all = [bar(i * 60, 1, 1, 1, 1) for i in range(2500)]
        self.calls = []

    async def fetch(self, limit, before):
        self.calls.append(before)
        older = [c for c in self.all if before is None or c["time"] < before]
        return [dict(c) for c in older[-limit:]]

    async def test_pages_back_until_enough_or_no_more(self):
        got = await history.fetch_history(self.fetch, 2200)
        self.assertEqual([c["time"] for c in got], [c["time"] for c in self.all[-2200:]])
        self.assertEqual(len(self.calls), 3)
        got = await history.fetch_history(self.fetch, 5000)   # only 2500 exist
        self.assertEqual(len(got), 2500)

    async def test_cache_fetches_only_the_newest_page_later(self):
        cache = history.HistoryCache(total=2200)
        await cache.get(("spot", "X", "1m"), self.fetch)
        self.calls.clear()
        self.all.append(bar(2500 * 60, 2, 2, 2, 2))   # a new candle closed
        got = await cache.get(("spot", "X", "1m"), self.fetch)
        self.assertEqual(self.calls, [None])          # one request
        self.assertEqual(len(got), 2200)
        self.assertEqual(got[-1]["close"], 2)

    def test_merge_prefers_the_newer_copy(self):
        merged = history.merge([bar(0, 1, 1, 1, 1), bar(60, 1, 1, 1, 1)], [bar(60, 5, 5, 5, 5), bar(120, 6, 6, 6, 6)], 2)
        self.assertEqual([(c["time"], c["close"]) for c in merged], [(60, 5), (120, 6)])


def row(kind, trades, net, pf, wins=1):
    return {"strategy": kind, "stats": {"trades": trades, "netPercent": net, "profitFactor": pf, "wins": wins}}


class ChooseTest(unittest.TestCase):
    def test_cautious_needs_state_trades_and_profit_factor(self):
        rows = [row("ema_cross", 20, 5.0, 1.8),        # trend strategy
                row("supertrend", 12, 3.0, 2.5),       # trend, better profit factor
                row("bb_reversion", 30, 9.0, 3.0),     # range only
                row("donchian", 5, 20.0, 9.0)]         # too few trades
        self.assertEqual(st.choose(rows, "trend_up", "cautious")["strategy"], "supertrend")
        self.assertEqual(st.choose(rows, "range", "cautious")["strategy"], "bb_reversion")
        self.assertIsNone(st.choose([row("ema_cross", 20, 1.0, 0.9)], "trend_up", "cautious"))  # PF below 1
        self.assertIsNone(st.choose(rows, "unknown", "cautious"))
        # No loss at all counts as the best profit factor.
        no_loss = [row("ema_cross", 11, 2.0, None, wins=11), row("supertrend", 12, 3.0, 2.5)]
        self.assertEqual(st.choose(no_loss, "trend_down", "cautious")["strategy"], "ema_cross")

    def test_max_profit_ignores_conditions_but_not_losses(self):
        rows = [row("ema_cross", 20, 5.0, 1.8), row("donchian", 3, 20.0, 9.0)]
        self.assertEqual(st.choose(rows, "unknown", "max_profit")["strategy"], "donchian")
        self.assertIsNone(st.choose([row("ema_cross", 20, -1.0, 0.8)], "range", "max_profit"))
        with self.assertRaises(ValueError):
            st.choose(rows, "range", "best")


class OverviewTest(unittest.TestCase):
    def test_table_of_all_and_trades_of_the_active_one(self):
        rows = wave(500)
        settings = {k: st.parse_params(k, {}, "scalping") for k in st.STRATEGIES}
        result = strategy_overview(rows, "1m", settings, "supertrend", "scalping", now=10**9)
        self.assertEqual([r["strategy"] for r in result["rows"]], list(st.STRATEGIES))
        self.assertTrue(all("trades" not in r and "stats" in r for r in result["rows"]))
        self.assertEqual(result["active"]["strategy"], "supertrend")
        from app.regime import detect
        direct = st.run(rows, "supertrend", settings["supertrend"], detect(rows, "scalping")[0])
        self.assertEqual(result["active"]["trades"], direct["trades"])
        self.assertIn(result["marketState"], ("trend_up", "trend_down", "range", "volatile", "unknown"))
        self.assertIsNone(strategy_overview(rows, "1m", settings, None, now=10**9)["active"])
        free = {k: st.parse_params(k, {"state_filter": 0}, "scalping") for k in st.STRATEGIES}
        auto = strategy_overview(rows, "1m", free, "supertrend", "scalping", now=10**9, auto_rule="max_profit")
        best = max((r for r in auto["rows"] if r["stats"]["trades"]), key=lambda r: r["stats"]["netPercent"])
        if best["stats"]["netPercent"] > 0:
            self.assertEqual(auto["choice"]["strategy"], best["strategy"])
            self.assertEqual(auto["active"]["strategy"], best["strategy"])   # the user's pick is ignored
        else:
            self.assertIsNone(auto["active"])


if __name__ == "__main__":
    unittest.main()
