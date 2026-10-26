import assert from "node:assert/strict";
import { test } from "node:test";
import { formatSince } from "../src/format.ts";
import {
  DEFAULT_SETTINGS, analysisParams, clearManual, invalidFields, legendItems, loadManual, saveManual,
} from "../src/indicatorSettings.ts";
import type { Analysis } from "../src/types.ts";

function memoryStorage() {
  const store = new Map<string, string>();
  return {
    store,
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

test("valid default settings, and out-of-range fields are named", () => {
  assert.deepEqual(invalidFields(DEFAULT_SETTINGS), []);
  const bad = { ...DEFAULT_SETTINGS, rsi_period: 1, ema_fast: 2.5, bb_mult: 9 };
  assert.deepEqual(invalidFields(bad).sort(), ["bb_mult", "ema_fast", "rsi_period"]);
});

test("automatic sends only auto=true; manual sends every field", () => {
  assert.deepEqual(analysisParams(null), { auto: "true" });
  const params = analysisParams({ ...DEFAULT_SETTINGS, rsi_on: false, bb_mult: 2.5 });
  assert.equal(params.auto, "false");
  assert.equal(params.rsi_on, "false");
  assert.equal(params.bb_mult, "2.5");
  assert.equal(params.ema_fast, "20");
});

test("manual settings are remembered, cleared, and broken data is ignored", () => {
  const storage = memoryStorage();
  assert.equal(loadManual(storage), null);
  const manual = { ...DEFAULT_SETTINGS, ema_fast: 12 };
  saveManual(manual, storage);
  assert.deepEqual(loadManual(storage), manual);
  clearManual(storage);
  assert.equal(loadManual(storage), null);
  storage.setItem("trading-bot.manualSettings", "{not json");
  assert.equal(loadManual(storage), null);
  storage.setItem("trading-bot.manualSettings", JSON.stringify({ ...manual, rsi_period: 0 }));
  assert.equal(loadManual(storage), null);
  const blocked = { getItem: () => { throw new Error("blocked"); } };
  assert.equal(loadManual(blocked), null);
});

test("legend follows the settings and shows the latest values", () => {
  const analysis: Analysis = {
    auto: true,
    tradingMode: "scalping",
    settings: { ...DEFAULT_SETTINGS, ema_fast: 9, ema_slow: 21, bb_on: false },
    state: { current: "trend_up", since: 60, adx: 30, atrRatio: 1 },
    atr: 2,
    lastClosedTime: 120,
    lines: {
      emaFast: [{ time: 60, value: 1 }, { time: 120, value: 2 }],
      emaSlow: [{ time: 120, value: 3 }],
      rsi: [{ time: 120, value: 55.5 }],
    },
    stateChanges: [],
  };
  const items = legendItems(analysis);
  assert.deepEqual(items.map((i) => i.label), ["EMA 9", "EMA 21", "RSI 14"]);
  assert.deepEqual(items[0].values, [2]);
  assert.deepEqual(items[2].values, [55.5]);
});

test("'since' shows only the time for today", () => {
  // TZ=Europe/Moscow in tests: 14:30 UTC = 17:30 local.
  const now = Date.UTC(2026, 9, 26, 18, 0);
  assert.equal(formatSince(Date.UTC(2026, 9, 26, 14, 30) / 1000, now), "17:30");
  assert.equal(formatSince(Date.UTC(2026, 9, 25, 14, 30) / 1000, now), "2026-10-25 17:30");
});
