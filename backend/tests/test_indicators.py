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


class NewFormulasTest(unittest.TestCase):
    def test_wma_weights_newest_most(self):
        # (1*1 + 2*2 + 3*3) / (1 + 2 + 3) = 14 / 6
        self.assertAlmostEqual(ind.wma([1, 2, 3], 3)[-1], 14 / 6)
        self.assertEqual(ind.wma([1, 2], 3), [None, None])

    def test_macd_parts_fit_together(self):
        closes = [100 + 5 * math.sin(i / 7) + i * 0.1 for i in range(120)]
        line, signal, hist = ind.macd(closes, 12, 26, 9)
        fast, slow = ind.ema(closes, 12), ind.ema(closes, 26)
        self.assertIsNone(line[24])
        self.assertAlmostEqual(line[25], fast[25] - slow[25])
        first_signal = 25 + 9 - 1  # signal needs 9 MACD values
        self.assertIsNone(signal[first_signal - 1])
        self.assertAlmostEqual(signal[first_signal], sum(line[25:34]) / 9)
        self.assertAlmostEqual(hist[-1], line[-1] - signal[-1])

    def test_stochastic_by_hand(self):
        highs, lows = [10, 12, 11, 13], [8, 9, 9, 10]
        closes = [9, 11, 10, 12]
        k, d = ind.stochastic(highs, lows, closes, 3, 1, 2)
        # Last 3 candles: highest 13, lowest 9, close 12 -> 75.
        self.assertAlmostEqual(k[-1], 75.0)
        # Previous: highest 12, lowest 8, close 10 -> 50; %D = average of 50 and 75.
        self.assertAlmostEqual(k[-2], 50.0)
        self.assertAlmostEqual(d[-1], 62.5)

    def test_flat_range_gives_no_stochastic(self):
        k, _ = ind.stochastic([5] * 5, [5] * 5, [5] * 5, 3, 1, 1)
        self.assertEqual(k, [None] * 5)

    def test_stoch_rsi_stays_between_0_and_100(self):
        closes = [100 + 10 * math.sin(i / 4) + (i % 3) for i in range(200)]
        k, d = ind.stoch_rsi(closes)
        values = [v for v in k + d if v is not None]
        self.assertTrue(values)
        self.assertTrue(all(0 <= v <= 100 for v in values))

    def test_dmi_rising_market(self):
        highs = [100 + i + 1 for i in range(80)]
        lows = [100 + i - 1 for i in range(80)]
        closes = [100 + i + 0.5 for i in range(80)]
        plus_di, minus_di, adx_line = ind.dmi(highs, lows, closes)
        self.assertGreater(plus_di[-1], minus_di[-1])
        self.assertEqual(adx_line, ind.adx(highs, lows, closes))

    def test_supertrend_follows_the_trend(self):
        up = [100 + i for i in range(60)]
        down = [159 - i for i in range(60)]
        closes = up + down
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        line, direction = ind.supertrend(highs, lows, closes, 10, 3.0)
        self.assertIsNone(line[8])            # needs 10 candles of ATR
        self.assertEqual(direction[55], -1)   # uptrend: line below price
        self.assertLess(line[55], lows[55])
        self.assertEqual(direction[-1], 1)    # downtrend: line above price
        self.assertGreater(line[-1], highs[-1])
        # In an uptrend the line never moves down.
        ups = [line[i] for i in range(20, 60) if direction[i] == -1]
        self.assertEqual(ups, sorted(ups))
