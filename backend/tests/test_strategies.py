import json
import math
import unittest

from app import indicators as ind
from app import strategies as st
from app.analysis import run_strategy, strategy_overview
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
        result = run_strategy(rows, "1m", "ema_cross", st.parse_params("ema_cross", {}, "scalping"), now=now)
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


class OverviewTest(unittest.TestCase):
    def test_table_of_all_and_trades_of_the_active_one(self):
        rows = wave(500)
        settings = {k: st.parse_params(k, {}, "scalping") for k in st.STRATEGIES}
        result = strategy_overview(rows, "1m", settings, "supertrend", now=10**9)
        self.assertEqual([r["strategy"] for r in result["rows"]], list(st.STRATEGIES))
        self.assertTrue(all("trades" not in r and "stats" in r for r in result["rows"]))
        self.assertEqual(result["active"]["strategy"], "supertrend")
        direct = st.run(rows, "supertrend", settings["supertrend"])
        self.assertEqual(result["active"]["trades"], direct["trades"])
        self.assertIsNone(strategy_overview(rows, "1m", settings, None, now=10**9)["active"])


if __name__ == "__main__":
    unittest.main()
