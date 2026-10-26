import json
import math
import unittest

from app import catalog, presets
from app.analysis import analyze


def candles(n=300, step=60):
    out = []
    for i in range(n):
        c = 100 + 10 * math.sin(i / 15) + i * 0.05
        out.append({"time": i * step, "open": c - 0.3 * (1 if i % 2 else -1), "high": c + 1,
                    "low": c - 1, "close": c, "volume": 10 + i % 7})
    return out


class CatalogTest(unittest.TestCase):
    def test_twelve_indicators_with_valid_defaults(self):
        self.assertEqual(len(catalog.SPECS), 12)
        for spec in catalog.SPECS.values():
            for p in spec.params:
                self.assertTrue(p.min <= p.default <= p.max, (spec.type, p.name))
            self.assertIn(spec.pane, ("price", "own"))

    def test_public_catalog_is_json_and_has_no_formulas(self):
        text = json.dumps(catalog.public_catalog())
        self.assertNotIn("compute", text)
        self.assertIn('"rsi"', text)

    def test_every_indicator_computes_on_real_looking_data(self):
        data = candles()
        instances = catalog.parse_instances([{"type": t} for t in catalog.SPECS])
        result = catalog.compute_instances(data, instances, keep_last=200)
        self.assertEqual(len(result), 12)
        for item in result:
            for output in item["outputs"]:
                self.assertTrue(output["points"], (item["type"], output["key"]))
                self.assertLessEqual(len(output["points"]), 200)
                self.assertTrue(all(math.isfinite(p["value"]) for p in output["points"]))

    def test_volume_bars_take_candle_colours(self):
        data = candles(30)
        result = catalog.compute_instances(data, catalog.parse_instances([{"type": "volume"}]), keep_last=30)
        points = result[0]["outputs"][0]["points"]
        up = [p for p, c in zip(points, data) if c["close"] >= c["open"]]
        self.assertTrue(all(p["color"] == catalog.UP for p in up))

    def test_same_indicator_three_times_gets_three_colours(self):
        instances = catalog.parse_instances([
            {"id": "a", "type": "ema", "params": {"length": 9}},
            {"id": "b", "type": "ema", "params": {"length": 21}},
            {"id": "c", "type": "ema", "params": {"length": 50}},
        ])
        result = catalog.compute_instances(candles(), instances, keep_last=10)
        self.assertEqual([r["label"] for r in result], ["EMA 9", "EMA 21", "EMA 50"])
        self.assertEqual(len({r["outputs"][0]["color"] for r in result}), 3)

    def test_labels(self):
        inst = catalog.parse_instances([{"type": "bb"}, {"type": "macd"}, {"type": "volume"}])
        self.assertEqual([catalog.label(i) for i in inst], ["BB 20 2", "MACD 12 26 9", "Vol"])

    def test_defaults_are_filled_in(self):
        inst = catalog.parse_instances([{"type": "stochrsi", "params": {"k": 5}}])[0]
        self.assertEqual(inst.params, {"k": 5, "d": 3, "rsi_length": 14, "stoch_length": 14})

    def test_bad_requests_are_refused(self):
        bad = [
            "not a list",
            [{"type": "nope"}],
            [{"type": "rsi", "params": {"length": 1}}],
            [{"type": "rsi", "params": {"length": 14.5}}],
            [{"type": "rsi", "params": {"colour": 3}}],
            [{"type": "rsi", "params": {"length": "14"}}],
            [{"id": "x", "type": "rsi"}, {"id": "x", "type": "ema"}],
            [{"type": "ema"}] * 21,
        ]
        for raw in bad:
            with self.assertRaises(ValueError, msg=str(raw)[:60]):
                catalog.parse_instances(raw)

    def test_decimal_settings_allowed_where_they_make_sense(self):
        inst = catalog.parse_instances([{"type": "bb", "params": {"mult": 2.5}}])[0]
        self.assertEqual(inst.params["mult"], 2.5)


class AutoListsTest(unittest.TestCase):
    def test_trend_shows_three_emas(self):
        for mode, lengths in (("scalping", [9, 21, 50]), ("daily", [20, 50, 200])):
            items = presets.auto_instances("trend_up", mode)
            self.assertEqual([i["params"]["length"] for i in items if i["type"] == "ema"], lengths)

    def test_every_state_list_is_valid(self):
        for state in presets.STATES:
            for mode in presets.MODE_EMAS:
                catalog.parse_instances(presets.auto_instances(state, mode))


class AnalysisWithListsTest(unittest.TestCase):
    def test_auto_adds_indicator_list_and_keeps_old_fields(self):
        data = [{"time": i * 60, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 1}
                for i in range(400)]
        result = analyze(data, "1m", "daily", now=10**9)
        self.assertEqual(result["state"]["current"], "trend_up")
        self.assertEqual([i["label"] for i in result["indicators"]], ["EMA 20", "EMA 50", "EMA 200", "RSI 14"])
        self.assertIn("lines", result)      # old screen still works
        self.assertIn("settings", result)

    def test_given_list_is_used(self):
        inst = catalog.parse_instances([{"id": "m", "type": "macd"}])
        result = analyze(candles(), "1m", "daily", now=10**9, instances=inst)
        self.assertFalse(result["auto"])
        self.assertEqual([i["id"] for i in result["indicators"]], ["m"])


if __name__ == "__main__":
    unittest.main()
