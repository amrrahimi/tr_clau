import asyncio
import unittest

from app import scanner as sc
from app import strategies as st

from .test_strategies import wave


def entry(base, kind, net, trades, pf, state="trend_up"):
    return {"symbol": f"{base}/USDT", "base": base, "strategy": kind, "marketState": state,
            "stats": {"netPercent": net, "trades": trades, "profitFactor": pf}}


class TopListsTest(unittest.TestCase):
    def setUp(self):
        self.entries = [
            entry("BTC", "ema_cross", 5.0, 20, 1.5),
            entry("BTC", "donchian", 9.0, 4, 3.0),         # BTC's best result, but few trades
            entry("ETH", "supertrend", 3.0, 15, 2.5),
            entry("ETH", "bb_reversion", 7.0, 30, 4.0),    # range strategy, ETH is in an uptrend
            entry("SOL", "rsi_pullback", -2.0, 12, 0.7),   # losing
        ]

    def test_max_profit_best_per_coin(self):
        top = sc.top_max_profit(self.entries)
        self.assertEqual([(e["base"], e["strategy"]) for e in top], [("BTC", "donchian"), ("ETH", "bb_reversion")])

    def test_cautious_needs_state_trades_and_profit_factor(self):
        top = sc.top_cautious(self.entries)
        self.assertEqual([(e["base"], e["strategy"]) for e in top], [("ETH", "supertrend"), ("BTC", "ema_cross")])

    def test_at_most_ten_rows(self):
        many = [entry(f"C{i}", "ema_cross", 1.0 + i, 20, 2.0) for i in range(15)]
        self.assertEqual(len(sc.top_max_profit(many)), 10)
        self.assertEqual(sc.top_max_profit(many)[0]["base"], "C14")


def sig(base, kind, t, rel, side="long"):
    return {"symbol": f"{base}/USDT", "base": base, "strategy": kind, "reliable": rel,
            "signal": {"side": side, "time": t, "entry": 1, "stopLoss": 0.9, "takeProfit": 1.2}}


class SignalLogTest(unittest.TestCase):
    def test_newest_first_once_each_and_at_most_twenty(self):
        old = [sig("BTC", "ema_cross", 60, False), sig("ETH", "donchian", 60, True)]
        new = [sig("BTC", "ema_cross", 60, False),             # same signal again: listed once
               sig("SOL", "supertrend", 120, False), sig("XRP", "macd_ema", 120, True)]
        log = sc.merge_log(old, new)
        self.assertEqual([(e["base"], e["signal"]["time"]) for e in log],
                         [("XRP", 120), ("SOL", 120), ("ETH", 60), ("BTC", 60)])   # reliable first within a candle
        many = [sig(f"C{i}", "ema_cross", i, False) for i in range(30)]
        self.assertEqual(len(sc.merge_log([], many)), 20)
        self.assertEqual(sc.merge_log([], many)[0]["signal"]["time"], 29)

    def test_reliable_means_the_cautious_conditions(self):
        self.assertTrue(sc.reliable(entry("A", "ema_cross", 2.0, 12, 1.5, "trend_up")))
        self.assertFalse(sc.reliable(entry("A", "ema_cross", 2.0, 12, 1.5, "range")))
        self.assertFalse(sc.reliable(entry("A", "ema_cross", 2.0, 5, 1.5)))
        self.assertFalse(sc.reliable(entry("A", "ema_cross", 2.0, 12, 0.9)))


class RunScanTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_coins_scanned_and_a_failing_coin_skipped(self):
        rows = wave(600)

        async def coins():
            return [("A/USDT", "A"), ("B/USDT", "B"), ("BAD/USDT", "BAD")]

        async def candles(symbol):
            if symbol.startswith("BAD"):
                raise RuntimeError("exchange said no")
            return rows

        settings = {k: st.parse_params(k, {"state_filter": 0}, "scalping") for k in st.STRATEGIES}
        job = sc.Scan(key="k", period=0)
        await sc.run_scan(job, coins, candles, "1m", "scalping", settings, st.Fees(0.075, 0.1), now=lambda: 10**9)
        self.assertFalse(job.running)
        self.assertEqual((job.done, job.total, job.failed), (3, 3, ["BAD"]))
        self.assertEqual(len(job.entries), 2 * len(st.STRATEGIES))
        public = job.public()
        self.assertIn("maxProfit", public)
        self.assertTrue(all(e["base"] in ("A", "B") for e in public["maxProfit"]))

    async def test_new_scan_only_after_a_candle_closed(self):
        clock = [60 * 100 + 5]
        scanner = sc.Scanner(now=lambda: clock[0])
        started = []

        async def start(job):
            started.append(job)
            job.running = False
            job.finished = clock[0]

        first = scanner.get_or_start("k", "1m", start)
        await asyncio.sleep(0)
        self.assertIs(scanner.get_or_start("k", "1m", start), first)    # same minute: same scan
        clock[0] += 60                                                 # next candle
        second = scanner.get_or_start("k", "1m", start)
        self.assertIsNot(second, first)
        self.assertIsNotNone(second.previous)                          # old tables shown meanwhile
        await asyncio.sleep(0)
        self.assertEqual(len(started), 2)


if __name__ == "__main__":
    unittest.main()
