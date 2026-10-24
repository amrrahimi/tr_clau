import unittest

from app import config


class TimeframeConfigTest(unittest.TestCase):
    def test_every_timeframe_has_a_length(self):
        # Loading older candles needs each timeframe's length in seconds.
        self.assertEqual(set(config.ALL_TIMEFRAMES), set(config.TIMEFRAME_SECONDS))

    def test_no_duplicates_in_all_timeframes(self):
        self.assertEqual(len(config.ALL_TIMEFRAMES), len(set(config.ALL_TIMEFRAMES)))

    def test_agreed_timeframes(self):
        self.assertEqual(config.TIMEFRAME_GROUPS["scalping"], ["1m", "3m", "5m", "15m"])
        self.assertEqual(config.TIMEFRAME_GROUPS["daily"], ["15m", "30m", "1h", "2h", "4h", "6h", "1d"])


if __name__ == "__main__":
    unittest.main()
