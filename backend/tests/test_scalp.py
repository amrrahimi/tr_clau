import unittest

from app import scalp
from app.strategies import LONG, STRATEGIES, parse_params


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


class ScalpTest(unittest.TestCase):
    def test_bollinger_poke_and_close_back_inside_is_a_long(self):
        rows = [bar(i * 60, 100, 100.2, 99.8, 100 + (0.1 if i % 2 else -0.1)) for i in range(80)]
        rows.append(bar(80 * 60, 100, 100.1, 99.0, 99.95))     # pokes far below the lower band, closes inside
        kinds = {(k, s.side) for k, s in scalp.scalp_signals(rows)}
        self.assertIn(("scalp_bb", LONG), kinds)
        for _, s in scalp.scalp_signals(rows):
            self.assertEqual(s.index, len(rows) - 1)               # only the newest closed candle
            self.assertGreater(s.stop_distance, 0)

    def test_too_few_candles(self):
        self.assertEqual(scalp.scalp_signals([bar(i, 1, 1, 1, 1) for i in range(30)]), [])

    def test_loose_signals_only_from_the_last_candles(self):
        rows = [bar(i * 60, 100 + i * 0.05, 100.2 + i * 0.05, 99.8 + i * 0.05, 100 + i * 0.05) for i in range(300)]
        settings = {k: parse_params(k, {}, "scalping") for k in STRATEGIES}
        for _, s in scalp.loose_signals(rows, settings, "scalping"):
            self.assertGreaterEqual(s.index, len(rows) - scalp.LOOSE_CANDLES)


if __name__ == "__main__":
    unittest.main()
