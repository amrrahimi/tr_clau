import unittest

from app import presets, regime


def candles_from(closes, spread=1.0, start=0, step=60):
    return [
        {"time": start + i * step, "open": c, "high": c + spread, "low": c - spread, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]


class RawStateTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(regime.raw_state(30, 2, 1, 1, 1), "trend_up")
        self.assertEqual(regime.raw_state(30, 1, 2, 1, 1), "trend_down")
        self.assertEqual(regime.raw_state(15, 1, 2, 1, 1), "range")
        self.assertIsNone(regime.raw_state(22, 1, 2, 1, 1))  # grey zone
        self.assertIsNone(regime.raw_state(None, 1, 2, 1, 1))  # not enough history

    def test_volatile_wins(self):
        self.assertEqual(regime.raw_state(30, 2, 1, 1.5, 1.0), "volatile")
        self.assertEqual(regime.raw_state(30, 2, 1, 1.49, 1.0), "trend_up")


class ConfirmTest(unittest.TestCase):
    def test_needs_three_in_a_row(self):
        raw = ["range", "range", "range", "trend_up", "trend_up", "trend_up"]
        self.assertEqual(regime.confirm(raw, 3),
                         ["unknown", "unknown", "range", "range", "range", "trend_up"])

    def test_short_blips_are_ignored(self):
        raw = ["range"] * 3 + ["trend_up", "trend_up", "range", "trend_up", "trend_up"]
        self.assertEqual(regime.confirm(raw, 3)[-1], "range")

    def test_grey_zone_keeps_state_and_resets_count(self):
        raw = ["range"] * 3 + [None, None, "trend_up", "trend_up", None, "trend_up"]
        self.assertEqual(set(regime.confirm(raw, 3)[3:]), {"range"})


class DetectTest(unittest.TestCase):
    def test_steady_rise_is_trend_up(self):
        closes = [100 + i for i in range(200)]
        states, reading = regime.detect(candles_from(closes), "daily")
        self.assertEqual(reading.state, "trend_up")
        self.assertGreater(reading.adx, 25)
        self.assertEqual(len(states), 200)
        self.assertEqual(states[0], "unknown")

    def test_steady_fall_is_trend_down(self):
        closes = [400 - i for i in range(200)]
        _, reading = regime.detect(candles_from(closes), "scalping")
        self.assertEqual(reading.state, "trend_down")

    def test_sideways_is_range(self):
        closes = [100 + (1 if i % 2 else -1) for i in range(200)]
        _, reading = regime.detect(candles_from(closes, spread=1.5), "daily")
        self.assertEqual(reading.state, "range")

    def test_sudden_big_candles_are_volatile(self):
        closes = [100 + (0.2 if i % 2 else -0.2) for i in range(200)]
        candles = candles_from(closes, spread=0.5)
        for c in candles[-6:]:  # last candles swing ten times wider
            c["high"], c["low"] = c["close"] + 5, c["close"] - 5
        _, reading = regime.detect(candles, "daily")
        self.assertEqual(reading.state, "volatile")
        self.assertGreaterEqual(reading.atr_ratio, regime.VOLATILE_RATIO)

    def test_since_is_when_state_began(self):
        closes = [100 + i for i in range(200)]
        states, reading = regime.detect(candles_from(closes), "daily")
        first = states.index("trend_up")
        self.assertEqual(reading.since, first * 60)

    def test_too_little_history_is_unknown(self):
        _, reading = regime.detect(candles_from([100, 101, 102]), "daily")
        self.assertEqual(reading.state, "unknown")
        self.assertIsNone(reading.since)


class PresetsTest(unittest.TestCase):
    def test_mode_lengths(self):
        self.assertEqual(presets.MODE_EMAS["scalping"], (9, 21))
        self.assertEqual(presets.MODE_EMAS["daily"], (20, 50))

    def test_state_lists(self):
        types = lambda state: [i["type"] for i in presets.auto_instances(state, "daily")]
        self.assertNotIn("bb", types("trend_up"))
        self.assertIn("bb", types("range"))
        volatile_bb = [i for i in presets.auto_instances("volatile", "daily") if i["type"] == "bb"][0]
        self.assertEqual(volatile_bb["params"]["mult"], 2.5)


if __name__ == "__main__":
    unittest.main()
