import tempfile
import unittest
from pathlib import Path

from app.memory import Memory, features
from app.strategies import LONG, Fees


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def entry(signal_time=60, side=LONG, stop=99, target=102):
    return {"symbol": "A/USDT:USDT", "base": "A", "strategy": "ema_cross", "marketState": "trend_up",
            "stats": {"trades": 20, "winRate": 45, "profitFactor": 1.6, "netPercent": 4},
            "signal": {"side": side, "time": signal_time, "entry": 100, "stopLoss": stop, "takeProfit": target,
                       "confirmedAt": signal_time + 60}}


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(self.memory.close)

    def test_signal_recorded_once_and_marked(self):
        e = entry()
        k = self.memory.record(e, "1m", {"x": 1}, now=0)
        self.assertEqual(self.memory.record(e, "1m", {"x": 1}, now=5), k)     # same signal again: once
        self.memory.mark(k, skip_reason="full")
        self.memory.mark(k, taken=True)
        self.memory.mark(k, skip_reason="stale")                               # a taken signal keeps "taken"
        row = self.memory.db.execute("SELECT taken, skip_reason FROM signals WHERE key = ?", (k,)).fetchone()
        self.assertEqual(row, (1, None))
        self.assertEqual(self.memory.summary()["signals"], 1)

    def test_shadow_trade_result_with_the_history_engine(self):
        k = self.memory.record(entry(), "1m", {}, now=0)
        candles = [bar(0, 100, 100, 100, 100), bar(60, 100, 100, 100, 100)]       # signal candle at 60
        self.assertEqual(self.memory.resolve("A/USDT:USDT", "1m", candles, {}, Fees(0.02, 0.06), now=1), 0)
        candles.append(bar(120, 100, 102.5, 99.5, 102))                           # entry candle reaches the target
        self.assertEqual(self.memory.resolve("A/USDT:USDT", "1m", candles, {}, Fees(0.02, 0.06), now=2), 1)
        status, reason, pnl = self.memory.db.execute(
            "SELECT status, exit_reason, pnl_percent FROM signals WHERE key = ?", (k,)).fetchone()
        self.assertEqual((status, reason), ("win", "target"))
        self.assertAlmostEqual(pnl, 2 - 0.06 - 0.02 * 1.02)
        self.assertEqual(self.memory.strategy_results(0), {"ema_cross": pnl})

    def test_live_signal_enters_where_and_when_the_bot_saw_it(self):
        # 15m signal on the candle at 900; the bot saw it 2 minutes into the next candle, at 100.3.
        k = self.memory.record(entry(signal_time=900), "15m", {}, now=1800 + 120, seen_price=100.3)
        candles = [bar(900, 100, 100, 100, 100), bar(1800, 100, 100.5, 99.8, 100.4)]
        # The candle it was seen in has closed, but nothing after it: still open.
        self.assertEqual(self.memory.resolve("A/USDT:USDT", "15m", candles, {}, Fees(0.02, 0.06), now=1), 0)
        candles.append(bar(2700, 100.4, 102.2, 100.1, 102))       # reaches the target
        self.assertEqual(self.memory.resolve("A/USDT:USDT", "15m", candles, {}, Fees(0.02, 0.06), now=2), 1)
        status, pnl, r = self.memory.db.execute("SELECT status, pnl_percent, r FROM signals WHERE key = ?", (k,)).fetchone()
        self.assertEqual(status, "win")
        # Entered at 100.3 (not at the open, 100): less gain, more risk (1.3 instead of 1).
        self.assertAlmostEqual(pnl, (102 / 100.3 - 1) * 100 - 0.06 - 0.02 * 102 / 100.3, places=6)
        self.assertLess(r, 1.3)

    def test_live_signal_seen_past_the_stop_is_not_a_trade(self):
        k = self.memory.record(entry(signal_time=900), "15m", {}, now=1800 + 60, seen_price=98.5)
        candles = [bar(900, 100, 100, 100, 100), bar(1800, 100, 100, 98, 98.6), bar(2700, 98.6, 99, 98, 98.5)]
        self.memory.resolve("A/USDT:USDT", "15m", candles, {}, Fees(0.02, 0.06), now=1)
        self.assertEqual(self.memory.db.execute("SELECT status FROM signals WHERE key = ?", (k,)).fetchone()[0], "expired")

    def test_older_signals_without_a_seen_price_keep_the_old_way(self):
        k = self.memory.record(entry(signal_time=900), "15m", {}, now=1800 + 120)
        candles = [bar(900, 100, 100, 100, 100), bar(1800, 100, 102.5, 99.5, 102)]
        self.memory.resolve("A/USDT:USDT", "15m", candles, {}, Fees(0.02, 0.06), now=1)
        self.assertEqual(self.memory.db.execute("SELECT status FROM signals WHERE key = ?", (k,)).fetchone()[0], "win")

    def test_signal_older_than_the_history_expires(self):
        self.memory.record(entry(signal_time=60), "1m", {}, now=0)
        self.memory.resolve("A/USDT:USDT", "1m", [bar(600, 1, 1, 1, 1)], {}, now=1)
        self.assertEqual(self.memory.db.execute("SELECT status FROM signals").fetchone()[0], "expired")

    def test_survives_reopening(self):
        self.memory.record(entry(), "1m", {}, now=0)
        self.memory.save_trade({"pnl": 1}, now=0)
        again = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(again.close)
        self.assertEqual((again.summary()["signals"], again.summary()["trades"]), (1, 1))

    def test_features(self):
        f = features(entry(), {"adx": 31.0, "atrRatio": 1.2}, Fees(0.02, 0.06))
        self.assertAlmostEqual(f["stopPercent"], 1.0)
        self.assertAlmostEqual(f["rewardRatio"], 2.0)
        self.assertAlmostEqual(f["feeShare"], 0.12)
        self.assertEqual((f["hourUtc"], f["adx"], f["histTrades"]), (0, 31.0, 20))


if __name__ == "__main__":
    unittest.main()


class StrategyPerformanceTest(unittest.TestCase):
    def test_bot_signals_and_brain_per_strategy(self):
        import json
        import tempfile
        from pathlib import Path
        from app.memory import Memory
        with tempfile.TemporaryDirectory() as folder:
            m = Memory(Path(folder) / "memory.db")
            rows = [  # key, strategy, status, r, chance, source, reliable
                ("a", "donchian", "win", 2.0, 0.6, "live", 1),
                ("b", "donchian", "loss", -1.0, 0.2, "live", 1),
                ("c", "donchian", "loss", -1.0, 0.5, "live", 1),
                ("d", "donchian", "loss", -1.0, 0.9, "history", 1),   # rebuilt from history: not counted
                ("e", "donchian", "win", 2.0, 0.9, "live", 0),        # not reliable: not counted
                ("f", "squeeze", "open", None, 0.9, "live", 1),       # not ended: not counted
            ]
            m.db.executemany("INSERT INTO signals (key, strategy, status, r, chance, source, reliable)"
                             " VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            m.db.execute("INSERT INTO trades (closed_at, data) VALUES (1, ?), (2, ?)",
                         (json.dumps({"strategy": "donchian", "pnl": 1.5}), json.dumps({"strategy": "donchian", "pnl": -0.5})))
            m.db.commit()
            perf = m.strategy_performance(brain_threshold=0.5)
            m.close()
        d = perf["donchian"]
        self.assertEqual(d["signals"]["count"], 3)
        self.assertAlmostEqual(d["signals"]["avgR"], 0.0)
        self.assertAlmostEqual(d["signals"]["winRate"], 100 / 3)
        self.assertEqual(d["brain"]["count"], 2)            # chance 0.6 and 0.5
        self.assertAlmostEqual(d["brain"]["avgR"], 0.5)
        self.assertEqual((d["bot"]["count"], d["bot"]["winRate"], d["bot"]["netPnl"]), (2, 50.0, 1.0))
        self.assertNotIn("squeeze", perf)


class LeagueTest(unittest.TestCase):
    def test_league_counts_live_signals_that_ended_lately(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        m = Memory(Path(d.name) / "memory.db")
        self.addCleanup(m.close)
        rows = [("a", "ema_cross", "5m", "live", "win", 1.0, 100), ("b", "ema_cross", "5m", "live", "loss", -1.0, 200),
                ("c", "ema_cross", "5m", "live", "win", 2.0, 300), ("d", "ema_cross", "5m", "history", "win", 5.0, 300),
                ("e", "ema_cross", "15m", "live", "open", None, None), ("f", "donchian", "5m", "live", "win", 1.0, 10)]
        for key, kind, tf, source, status, r, exit_time in rows:
            m.db.execute("INSERT INTO signals (key, symbol, base, timeframe, strategy, side, signal_time, status,"
                         " r, exit_time, source) VALUES (?, 'A/USDT:USDT', 'A', ?, ?, 'long', 0, ?, ?, ?, ?)",
                         (key, tf, kind, status, r, exit_time, source))
        self.assertEqual(m.league(50), {("ema_cross", "5m"): (3, 2.0)})
