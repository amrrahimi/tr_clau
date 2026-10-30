import random
import tempfile
import unittest
from pathlib import Path

from app import brain as br
from app.memory import Memory


def add_signals(memory, n, start=0, good=lambda i, adx: adx > 30, seed=1):
    """Fake finished signals: those with strong trend (adx > 30) win 2R, the rest lose 1R."""
    rng = random.Random(seed)
    for i in range(start, start + n):
        adx = rng.uniform(5, 55)
        win = good(i, adx)
        feats = {"marketState": "trend_up", "adx": adx, "atrRatio": rng.uniform(0.5, 2), "stopPercent": 0.8,
                 "rewardRatio": 2, "feeShare": 0.1, "hourUtc": i % 24, "weekday": i % 7,
                 "histTrades": 30, "histWinRate": 40, "histProfitFactor": 1.4, "histNetPercent": 5}
        e = {"symbol": "A/USDT:USDT", "base": "A", "strategy": "ema_cross", "marketState": "trend_up",
             "stats": {}, "signal": {"side": "long", "time": 1000 + i * 60, "entry": 100, "stopLoss": 99,
                                     "takeProfit": 102, "confirmedAt": 1060 + i * 60}}
        key = memory.record(e, "5m", feats, now=0)
        memory._finish(key, "win" if win else "loss", 0, "target" if win else "stop",
                       1.6 if win else -0.9, 2.0 if win else -1.0, 0)
    memory.db.commit()


class BrainTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.memory = Memory(Path(self.dir.name) / "memory.db")
        self.addCleanup(self.memory.close)
        self.clock = [50_000.0]
        self.brain = br.Brain(self.memory, now=lambda: self.clock[0])

    def test_collects_until_enough_signals(self):
        add_signals(self.memory, 50)
        self.assertEqual(self.brain.train()["result"], "few")
        self.assertFalse(self.brain.active())
        self.assertTrue(self.brain.allows(0.0))                 # no model: every signal passes
        self.assertEqual(self.brain.public()["state"], "collecting")

    def test_learns_a_real_pattern_and_filters(self):
        add_signals(self.memory, 400)
        outcome = self.brain.train()
        self.assertEqual(outcome["result"], "promoted")
        self.assertTrue(self.brain.active())
        test = outcome["test"]
        self.assertGreater(test["kept"]["avgR"], test["all"]["avgR"])   # better than taking every signal
        base = {"marketState": "trend_up", "atrRatio": 1, "stopPercent": 0.8, "rewardRatio": 2, "feeShare": 0.1,
                "hourUtc": 3, "weekday": 2, "histTrades": 30, "histWinRate": 40, "histProfitFactor": 1.4,
                "histNetPercent": 5}
        strong = self.brain.chance({**base, "adx": 50}, "ema_cross", "5m", "long")
        weak = self.brain.chance({**base, "adx": 8}, "ema_cross", "5m", "long")
        self.assertTrue(self.brain.allows(strong))
        self.assertFalse(self.brain.allows(weak))

    def test_survives_restart_and_waits_six_hours(self):
        add_signals(self.memory, 400)
        self.brain.train()
        again = br.Brain(self.memory, now=lambda: self.clock[0])
        self.assertTrue(again.active())
        self.assertEqual(again.champion.info["version"], 1)
        self.assertFalse(again.due(self.clock[0] + 3600))
        self.assertTrue(again.due(self.clock[0] + br.RETRAIN_SECONDS))

    def test_no_pattern_no_model(self):
        rng = random.Random(7)
        add_signals(self.memory, 400, good=lambda i, adx: rng.random() < 0.33)   # pure luck
        outcome = self.brain.train()
        if outcome["result"] == "promoted":                     # by chance it may look a bit better
            self.assertGreater(outcome["test"]["kept"]["avgR"], outcome["test"]["all"]["avgR"])
        else:
            self.assertEqual(outcome["result"], "weak")
            self.assertFalse(self.brain.active())

    def test_champion_switched_off_when_the_pattern_turns(self):
        add_signals(self.memory, 400)
        self.assertEqual(self.brain.train()["result"], "promoted")
        # The market changes: now weak trends win and strong ones lose.
        add_signals(self.memory, 1200, start=400, good=lambda i, adx: adx < 30, seed=2)
        self.clock[0] += br.RETRAIN_SECONDS
        outcome = self.brain.train()
        # Either a new model learned the new pattern, or the old one was switched off.
        self.assertIn(outcome["result"], ("promoted", "off"))
        if outcome["result"] == "off":
            self.assertFalse(self.brain.active())
            self.assertEqual(self.brain.public()["state"], "off")


if __name__ == "__main__":
    unittest.main()
