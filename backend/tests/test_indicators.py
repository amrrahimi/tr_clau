import math
import unittest

from app import indicators as ind

# A worked RSI example, checked by hand below.
EXAMPLE_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
    45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64,
]


def close_enough(a, b, tolerance=1e-9):
    return a is not None and b is not None and abs(a - b) <= tolerance


class MovingAverageTest(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_starts_from_sma_then_smooths(self):
        out = ind.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(out[:2], [None, None])
        self.assertEqual(out[2], 2.0)              # SMA of 1, 2, 3
        self.assertEqual(out[3], 0.5 * 4 + 0.5 * 2.0)  # alpha = 2 / (3 + 1)
        self.assertEqual(out[4], 0.5 * 5 + 0.5 * 3.0)

    def test_rma_uses_one_over_length(self):
        out = ind.rma([2, 4, 6, 8], 2)
        self.assertEqual(out, [None, 3.0, 4.5, 6.25])

    def test_leading_gaps_are_skipped(self):
        self.assertEqual(ind.rma([None, 2, 4, 6], 2), [None, None, 3.0, 4.5])

    def test_short_input_stays_empty(self):
        self.assertEqual(ind.ema([1, 2], 3), [None, None])


class RsiTest(unittest.TestCase):
    def test_worked_example_by_hand(self):
        out = ind.rsi(EXAMPLE_CLOSES, 14)
        self.assertTrue(all(v is None for v in out[:14]))
        # First 14 changes: gains add up to 3.34, losses to 1.40.
        avg_gain, avg_loss = 3.34 / 14, 1.40 / 14
        self.assertAlmostEqual(out[14], 100 - 100 / (1 + avg_gain / avg_loss), places=9)  # 70.46
        # Next change is 46.00 - 46.28 = -0.28: Wilder smoothing (13 * old + new) / 14.
        avg_gain = (avg_gain * 13 + 0) / 14
        avg_loss = (avg_loss * 13 + 0.28) / 14
        self.assertAlmostEqual(out[15], 100 - 100 / (1 + avg_gain / avg_loss), places=9)  # 66.25

    def test_only_rises_is_100_only_falls_is_0(self):
        self.assertEqual(ind.rsi(list(range(1, 20)), 14)[-1], 100.0)
        self.assertEqual(ind.rsi(list(range(20, 1, -1)), 14)[-1], 0.0)

    def test_stays_between_0_and_100(self):
        closes = [100 + 10 * math.sin(i / 3) for i in range(200)]
        values = [v for v in ind.rsi(closes, 14) if v is not None]
        self.assertTrue(all(0 <= v <= 100 for v in values))


class BollingerTest(unittest.TestCase):
    def test_population_standard_deviation(self):
        upper, middle, lower = ind.bollinger([2, 4, 4, 4, 5, 5, 7, 9], 8, 2.0)
        # Mean 5, population standard deviation exactly 2.
        self.assertEqual(middle[-1], 5.0)
        self.assertEqual(upper[-1], 9.0)
        self.assertEqual(lower[-1], 1.0)


class AtrAdxTest(unittest.TestCase):
    def test_true_range_includes_gaps(self):
        highs, lows, closes = [10, 12, 11], [9, 11, 8], [9.5, 11.5, 9]
        self.assertEqual(ind.true_range(highs, lows, closes), [1, 2.5, 3.5])
        self.assertEqual(ind.true_range(highs, lows, closes, first_is_high_low=False)[0], None)

    def test_atr_of_constant_candles(self):
        n = 30
        out = ind.atr([11] * n, [9] * n, [10] * n, 14)
        self.assertTrue(close_enough(out[-1], 2.0))
        self.assertEqual(out[12], None)
        self.assertTrue(close_enough(out[13], 2.0))  # first value after 14 candles

    def test_adx_strong_steady_trend_is_high(self):
        highs = [100 + i + 1 for i in range(80)]
        lows = [100 + i - 1 for i in range(80)]
        closes = [100 + i + 0.5 for i in range(80)]
        out = ind.adx(highs, lows, closes, 14, 14)
        self.assertGreater(out[-1], 90)
        # First value: 14 candles for the averages + 14 more for ADX's own smoothing.
        self.assertIsNone(out[26])
        self.assertIsNotNone(out[27])

    def test_adx_sideways_market_is_low(self):
        highs = [101 + (i % 2) for i in range(120)]
        lows = [99 - (i % 2) for i in range(120)]
        closes = [100.0] * 120
        out = ind.adx(highs, lows, closes, 14, 14)
        self.assertLess(out[-1], 20)


if __name__ == "__main__":
    unittest.main()
