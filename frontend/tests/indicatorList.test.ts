import assert from "node:assert/strict";
import { test } from "node:test";
import { analysisParams } from "../src/api.ts";
import { formatSince } from "../src/format.ts";
import {
  MAX_INDICATORS, addIndicator, cleanList, convertOldSettings, fromResults, instanceLabel, invalidParams,
  latestValues, loadManualState, removeIndicator, saveManualState, updateParams,
} from "../src/indicatorList.ts";
import type { CatalogSpec, IndicatorInstance, IndicatorResult } from "../src/types.ts";

const EMA: CatalogSpec = {
  type: "ema", name: "EMA", pane: "price",
  params: [{ name: "length", default: 9, min: 1, max: 500, step: 1 }],
  outputs: [{ key: "value", color: "#fff", style: "line" }], levels: [], scale: null, candle_colors: false,
};
const BB: CatalogSpec = {
  type: "bb", name: "BB", pane: "price",
  params: [{ name: "length", default: 20, min: 1, max: 500, step: 1 }, { name: "mult", default: 2, min: 0.1, max: 10, step: 0.1 }],
  outputs: [], levels: [], scale: null, candle_colors: false,
};

function memoryStorage() {
  const store = new Map<string, string>();
  return {
    store,
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

test("add the same indicator three times, each with its own id and default settings", () => {
  let list = addIndicator([], EMA);
  list = addIndicator(list, EMA);
  list = addIndicator(list, EMA);
  assert.equal(list.length, 3);
  assert.equal(new Set(list.map((i) => i.id)).size, 3);
  assert.deepEqual(list[0].params, { length: 9 });
});

test("edit and remove one instance without touching the others", () => {
  let list = addIndicator(addIndicator([], EMA), EMA);
  const [a, b] = list;
  list = updateParams(list, b.id, { length: 50 });
  assert.equal(list[1].params.length, 50);
  assert.equal(list[0].params.length, 9);
  list = removeIndicator(list, a.id);
  assert.deepEqual(list.map((i) => i.id), [b.id]);
});

test("at most 20 indicators", () => {
  let list: IndicatorInstance[] = [];
  for (let n = 0; n < 25; n++) list = addIndicator(list, EMA);
  assert.equal(list.length, MAX_INDICATORS);
});

test("settings checks follow the catalog", () => {
  assert.deepEqual(invalidParams(BB, { length: 20, mult: 2.5 }), []);
  assert.deepEqual(invalidParams(BB, { length: 0, mult: 2 }), ["length"]);
  assert.deepEqual(invalidParams(BB, { length: 20.5, mult: 99 }), ["length", "mult"]);
  assert.deepEqual(invalidParams(EMA, {}), ["length"]);
});

test("labels look like TradingView's", () => {
  assert.equal(instanceLabel(BB, { id: "x", type: "bb", params: { length: 20, mult: 2.5 } }), "BB 20 2.5");
  assert.equal(instanceLabel(undefined, { id: "x", type: "gone", params: {} }), "gone");
});

test("the bot's list becomes the starting point for the user's list", () => {
  const results = [{ id: "auto-ema-9", type: "ema", params: { length: 9 } }] as unknown as IndicatorResult[];
  const list = fromResults(results);
  assert.equal(list[0].type, "ema");
  assert.deepEqual(list[0].params, { length: 9 });
  assert.notEqual(list[0].id, "auto-ema-9");
});

test("unknown or invalid instances are dropped", () => {
  const list: IndicatorInstance[] = [
    { id: "a", type: "ema", params: { length: 9 } },
    { id: "b", type: "removed-indicator", params: {} },
    { id: "c", type: "ema", params: { length: 0 } },
  ];
  assert.deepEqual(cleanList(list, [EMA]).map((i) => i.id), ["a"]);
});

test("latest values per output", () => {
  const result = { outputs: [{ points: [{ time: 1, value: 2 }, { time: 2, value: 3 }] }, { points: [] }] } as unknown as IndicatorResult;
  assert.deepEqual(latestValues(result), [3, null]);
});

test("mode and list are remembered; Auto forgets the list", () => {
  const storage = memoryStorage();
  assert.deepEqual(loadManualState(storage), { mode: "auto", list: [] });
  const list = addIndicator([], EMA);
  saveManualState({ mode: "manual-running", list }, storage);
  assert.deepEqual(loadManualState(storage), { mode: "manual-running", list });
  saveManualState({ mode: "auto", list: [] }, storage);
  assert.deepEqual(loadManualState(storage), { mode: "auto", list: [] });
});

test("old fixed settings are converted once into a stopped manual list", () => {
  const storage = memoryStorage();
  storage.setItem("trading-bot.manualSettings", JSON.stringify({
    ema_fast_on: false, ema_fast: 9, ema_slow_on: true, ema_slow: 30, bb_on: true, bb_period: 20, bb_mult: 2.5, rsi_on: false, rsi_period: 14,
  }));
  const state = loadManualState(storage);
  assert.equal(state.mode, "manual-stopped");
  assert.deepEqual(state.list.map((i) => [i.type, i.params]), [["ema", { length: 30 }], ["bb", { length: 20, mult: 2.5 }]]);
  saveManualState(state, storage);
  assert.equal(storage.store.has("trading-bot.manualSettings"), false);
  assert.equal(convertOldSettings({}).length, 4);
});

test("broken storage starts in automatic mode", () => {
  assert.deepEqual(loadManualState({ getItem: () => { throw new Error("blocked"); } }), { mode: "auto", list: [] });
  const storage = memoryStorage();
  storage.setItem("trading-bot.manual", "{not json");
  assert.equal(loadManualState(storage).mode, "auto");
});

test("request parameters", () => {
  assert.deepEqual(analysisParams(null), { auto: "true" });
  const params = analysisParams([{ id: "a", type: "ema", params: { length: 21 } }]);
  assert.equal(params.auto, "false");
  assert.deepEqual(JSON.parse(params.indicators), [{ id: "a", type: "ema", params: { length: 21 } }]);
  assert.deepEqual(JSON.parse(analysisParams([]).indicators), []);
});

test("'since' shows only the time for today", () => {
  const now = Date.UTC(2026, 9, 26, 18, 0);
  assert.equal(formatSince(Date.UTC(2026, 9, 26, 14, 30) / 1000, now), "17:30");
});

test("pane layout: price indicators share pane 0, others get their own pane in order", async () => {
  const { paneLayout } = await import("../src/chart.ts").catch(() => ({ paneLayout: null }));
  if (!paneLayout) return; // chart.ts needs the chart library; checked in the browser test instead
  const panes = paneLayout([
    { id: "a", pane: "price" }, { id: "b", pane: "own" }, { id: "c", pane: "price" }, { id: "d", pane: "own" },
  ]);
  assert.deepEqual([...panes], [["a", 0], ["b", 1], ["c", 0], ["d", 2]]);
});
