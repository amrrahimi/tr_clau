import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import connection
from app.research import compare_exits
from tests.test_pretrain import FEES, SETTINGS, walk


class ConnectionTest(unittest.TestCase):
    def test_typed_proxy_wins_then_system_then_direct(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            with mock.patch.object(connection, "system_proxy", return_value=None):
                self.assertEqual(connection.current(path), (None, "direct"))
            with mock.patch.object(connection, "system_proxy", return_value="http://10.0.0.1:8080"):
                self.assertEqual(connection.current(path), ("http://10.0.0.1:8080", "system"))
                connection.save_proxy(" socks5://127.0.0.1:10808 ", path)
                self.assertEqual(connection.current(path), ("socks5://127.0.0.1:10808", "app"))
                connection.save_proxy("", path)
                self.assertEqual(connection.current(path)[1], "system")

    def test_normalize(self):
        self.assertEqual(connection.normalize("127.0.0.1:10809"), "http://127.0.0.1:10809")
        self.assertIsNone(connection.normalize("  "))


class ExitComparisonTest(unittest.TestCase):
    def test_same_signals_closed_four_ways(self):
        result = compare_exits(walk(3000), SETTINGS, "scalping", FEES)
        self.assertEqual(set(result), {"be0", "be50", "be80", "cap"})
        self.assertGreater(result["be0"]["count"], 10)
        # The small profit cap wins far more often, each win is tiny.
        cap, base = result["cap"], result["be0"]
        self.assertGreater(cap["wins"] / cap["count"], base["wins"] / base["count"])


if __name__ == "__main__":
    unittest.main()
