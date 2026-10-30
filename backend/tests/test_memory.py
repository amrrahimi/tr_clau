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
