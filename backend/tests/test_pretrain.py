import random
import tempfile
import unittest
from pathlib import Path

from app import brain as br
from app import pretrain
from app.memory import Memory
from app.strategies import STRATEGIES, Fees, parse_params, run
from app.regime import series

FEES = Fees(0.02, 0.06)


def walk(n=3000, seed=3):
    """Random candles with trending and calm stretches."""
    rng = random.Random(seed)
    p, rows, drift = 100.0, [], 0.0
    for i in range(n):
        if i % 200 == 0:
            drift = rng.choice([-0.0015, 0, 0.0015])
        o = p
        p *= 1 + drift + rng.gauss(0, 0.004)
        rows.append({"time": i * 300, "open": o, "high": max(o, p) * (1 + abs(rng.gauss(0, 0.002))),
                     "low": min(o, p) * (1 - abs(rng.gauss(0, 0.002))), "close": p, "volume": 1})
    return rows


SETTINGS = {k: parse_params(k, {}, "scalping") for k in STRATEGIES}


class PretrainTest(unittest.TestCase):
    def test_past_signals_with_no_peeking_into_the_future(self):
        candles = walk()
        rows = pretrain.history_signals("A/USDT:USDT", "A", "5m", candles, SETTINGS, "scalping", FEES)
        self.assertGreater(len(rows), 20)
        states, _, _ = series(candles, "scalping")
        for row in rows[:200]:
            s, kind = row["entry"]["signal"], row["entry"]["strategy"]
            self.assertGreaterEqual(s["time"], candles[pretrain.WARMUP]["time"])         # warm-up skipped
            self.assertIn(row["result"], ("win", "loss", "breakeven"))
            # The record counts only trades that had ended before the signal.
            trades = run(candles, kind, SETTINGS[kind], states, FEES)["trades"]
            ended = [t for t in trades if t["result"] != "open" and t["exitTime"] <= s["time"]]
            self.assertEqual(row["features"]["histTrades"], len(ended))
            self.assertEqual(row["features"]["reliable"], row["reliable"])

    def test_too_short_history_gives_nothing(self):
        self.assertEqual(pretrain.history_signals("A", "A", "5m", walk(500), SETTINGS, "scalping", FEES), [])


class MemoryHistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(self.memory.close)

    def test_live_wins_and_history_stays_out_of_the_bench(self):
        rows = pretrain.history_signals("A/USDT:USDT", "A", "5m", walk(), SETTINGS, "scalping", FEES)
        live = rows[0]
        self.memory.record(live["entry"], "5m", {}, now=0)                    # the bot had seen this one live
        added = self.memory.record_history("5m", rows, now=1)
        self.assertEqual(added, len(rows) - 1)
        self.assertEqual(self.memory.record_history("5m", rows, now=2), 0)      # a second round adds nothing
        summary = self.memory.summary()
        self.assertEqual((summary["signals"], summary["history"]), (1, len(rows) - 1))
        self.assertEqual(self.memory.strategy_results(0), {})                   # history never benches a strategy
        self.memory.set_pretrain_time("A/USDT:USDT", "5m", 5)
        self.assertEqual(self.memory.pretrain_time("A/USDT:USDT", "5m"), 5)
        self.assertEqual(self.memory.summary()["charts"], 1)

    def test_unreliable_live_signals_are_remembered_but_do_not_bench(self):
        e = {"symbol": "A/USDT:USDT", "base": "A", "strategy": "ema_cross", "marketState": "range", "stats": {},
             "signal": {"side": "long", "time": 60, "entry": 100, "stopLoss": 99, "takeProfit": 102, "confirmedAt": 120}}
        k = self.memory.record(e, "1m", {"reliable": False}, now=0, reliable=False)
        self.memory._finish(k, "loss", 180, "stop", -1.1, -1.0, 1)
        self.assertEqual(self.memory.strategy_results(0), {})
        self.assertEqual((self.memory.summary()["signals"], self.memory.summary()["reliable"]), (1, 0))


class BrainWithHistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(self.memory.close)

    def test_split_uses_live_signals_once_there_are_enough(self):
        rows = [{"time": i, "history": i < 500, "reliable": True} for i in range(800)]
        train, test, on = br.split(rows)
        self.assertEqual(on, "live")
        self.assertTrue(all(not r["history"] for r in test))
        self.assertLess(max(r["time"] for r in train), min(r["time"] for r in test))
        few = [{"time": i, "history": i < 700, "reliable": True} for i in range(800)]
        self.assertEqual(br.split(few)[2], "history")

    def test_model_made_for_other_strategies_is_made_again(self):
        model = br.Model([0.0], 0.0, [0.0], [1.0], 0.5, {"version": 1, "signature": "old", "on": True})
        self.memory.save_training({"time": 0, "result": "promoted"}, model.to_json())
        self.assertIsNone(br.Brain(self.memory).champion)


if __name__ == "__main__":
    unittest.main()
