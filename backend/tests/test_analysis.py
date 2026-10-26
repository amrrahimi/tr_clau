import unittest

from app import indicators as ind
from app.analysis import analyze, closed_only
from app.presets import IndicatorSettings


def rising(n, step=60, start=0):
    return [
        {"time": start + i * step, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i + 0.5, "volume": 1}
        for i in range(n)
    ]


class ClosedOnlyTest(unittest.TestCase):
    def test_forming_candle_is_dropped(self):
        candles = rising(3)  # times 0, 60, 120 on a 1m chart
        self.assertEqual([c["time"] for c in closed_only(candles, "1m", now=179)], [0, 60])
        self.assertEqual([c["time"] for c in closed_only(candles, "1m", now=180)], [0, 60, 120])


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.candles = rising(301)
        self.now = 300 * 60 + 30  # last candle (t=18000) still forming

    def test_auto_uses_preset_for_detected_state(self):
        result = analyze(self.candles, "1m", "scalping", now=self.now, returned_points=100)
        self.assertTrue(result["auto"])
        self.assertEqual(result["state"]["current"], "trend_up")
        self.assertEqual(result["settings"]["ema_fast"], 9)
        self.assertFalse(result["settings"]["bb_on"])          # trend preset hides the bands
        self.assertNotIn("bbUpper", result["lines"])
        self.assertEqual(result["lastClosedTime"], 299 * 60)
        self.assertEqual(len(result["lines"]["emaFast"]), 100)
        self.assertEqual(result["lines"]["emaFast"][-1]["time"], 299 * 60)

    def test_lines_match_the_formulas_on_closed_candles(self):
        result = analyze(self.candles, "1m", "daily", now=self.now, returned_points=50)
        closes = [c["close"] for c in self.candles[:-1]]
        self.assertAlmostEqual(result["lines"]["rsi"][-1]["value"], ind.rsi(closes, 14)[-1])
        self.assertAlmostEqual(result["lines"]["emaSlow"][-1]["value"], ind.ema(closes, 50)[-1])

    def test_manual_settings_are_used_as_given(self):
        manual = IndicatorSettings(ema_fast_on=False, ema_slow=30, bb_on=True, rsi_on=False)
        result = analyze(self.candles, "1m", "daily", manual=manual, now=self.now)
        self.assertFalse(result["auto"])
        self.assertEqual(set(result["lines"]), {"emaSlow", "bbUpper", "bbMiddle", "bbLower"})
        # The state label is still detected, independent of manual chart settings.
        self.assertEqual(result["state"]["current"], "trend_up")

    def test_state_changes_list(self):
        result = analyze(self.candles, "1m", "daily", now=self.now, returned_points=300)
        changes = result["stateChanges"]
        self.assertEqual(changes[0]["state"], "unknown")
        self.assertEqual(changes[-1]["state"], "trend_up")

    def test_empty_input(self):
        result = analyze([], "1m", "daily", now=0)
        self.assertEqual(result["state"]["current"], "unknown")
        self.assertIsNone(result["lastClosedTime"])


if __name__ == "__main__":
    unittest.main()
