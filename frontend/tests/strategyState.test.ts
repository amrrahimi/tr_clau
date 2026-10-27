import assert from "node:assert/strict";
import { test } from "node:test";
import { MOCK_STRATEGIES } from "../src/mockStrategies.ts";
import {
  COLORS,
  cleanStrategyState,
  effectiveParams,
  formatPercent,
  loadStrategyState,
  saveStrategyState,
  setParams,
  toggleActive,
  tradeBoxes,
  tradeMarkers,
  type StrategyState,
} from "../src/strategyState.ts";
import type { Trade } from "../src/types.ts";

const emaCross = MOCK_STRATEGIES.find((c) => c.type === "ema_cross")!;
const empty: StrategyState = { active: null, settings: {} };

function trade(over: Partial<Trade>): Trade {
  return {
    side: "long", signalTime: 0, entryTime: 60, entryPrice: 100, stopLoss: 99, takeProfit: 102,
    exitTime: 180, exitPrice: 102, exitReason: "target", breakevenTime: null, result: "win", pnlPercent: 2, r: 2, ...over,
  };
}

test("only one strategy is active; clicking it again turns it off", () => {
  const a = toggleActive(empty, "ema_cross");
  assert.equal(a.active, "ema_cross");
  assert.equal(toggleActive(a, "supertrend").active, "supertrend");
  assert.equal(toggleActive(a, "ema_cross").active, null);
});

test("trend EMA default follows the trading mode; only changes are saved", () => {
  assert.equal(effectiveParams(emaCross, empty, "scalping").trend, 50);
  assert.equal(effectiveParams(emaCross, empty, "daily").trend, 200);
  const changed = setParams(empty, emaCross, { ...effectiveParams(emaCross, empty, "scalping"), fast: 12 }, "scalping");
  assert.deepEqual(changed.settings, { ema_cross: { fast: 12 } });
  // Switching to daily still uses daily's own trend default.
  assert.equal(effectiveParams(emaCross, changed, "daily").trend, 200);
  assert.equal(effectiveParams(emaCross, changed, "daily").fast, 12);
  // Back to all defaults: nothing saved.
  assert.deepEqual(setParams(changed, emaCross, effectiveParams(emaCross, empty, "scalping"), "scalping").settings, {});
});

test("saved state survives a restart and bad data is ignored", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  saveStrategyState({ active: "donchian", settings: { donchian: { length: 30 } } }, storage);
  assert.deepEqual(loadStrategyState(storage), { active: "donchian", settings: { donchian: { length: 30 } } });
  store.set("trading-bot.strategies", "{not json");
  assert.deepEqual(loadStrategyState(storage), empty);
  store.set("trading-bot.strategies", JSON.stringify({ active: 5, settings: { a: { x: "1", y: 2 } } }));
  assert.deepEqual(loadStrategyState(storage), { active: null, settings: { a: { y: 2 } } });
  assert.deepEqual(cleanStrategyState({ active: "gone", settings: { gone: { a: 1 } } }, MOCK_STRATEGIES), empty);
});

test("arrows: entries green up (long) / red down (short), exits yellow with tick or cross", () => {
  const markers = tradeMarkers([
    trade({}),
    trade({ side: "short", entryTime: 300, entryPrice: 100, stopLoss: 101, takeProfit: 98, exitTime: 420, result: "loss" }),
    trade({ entryTime: 600, exitTime: null, exitPrice: null, result: "open" }),
  ]);
  assert.deepEqual(markers.map((m) => [m.time, m.shape, m.position, m.color, m.text]), [
    [60, "arrowUp", "belowBar", COLORS.long, ""],
    [180, "arrowDown", "aboveBar", COLORS.exit, "✓"],
    [300, "arrowDown", "aboveBar", COLORS.short, ""],
    [420, "arrowUp", "belowBar", COLORS.exit, "✗"],
    [600, "arrowUp", "belowBar", COLORS.long, ""],
  ]);
});

test("a trade closed at the entry price gets ＝", () => {
  const [, exit] = tradeMarkers([trade({ result: "breakeven", exitReason: "breakeven", exitPrice: 100, pnlPercent: 0 })]);
  assert.equal(exit.text, "＝");
  assert.equal(exit.color, COLORS.exit);
});

test("boxes: green to take-profit, red to stop-loss; open trades reach the last candle", () => {
  const boxes = tradeBoxes([
    trade({}),
    trade({ side: "short", entryPrice: 100, stopLoss: 101, takeProfit: 98, exitTime: null, result: "open" }),
  ], 900);
  assert.deepEqual(boxes, [
    { from: 60, to: 180, top: 102, bottom: 100, color: COLORS.profitBox },
    { from: 60, to: 180, top: 100, bottom: 99, color: COLORS.lossBox },
    { from: 60, to: 900, top: 100, bottom: 98, color: COLORS.profitBox },
    { from: 60, to: 900, top: 101, bottom: 100, color: COLORS.lossBox },
  ]);
});

test("percent format", () => {
  assert.equal(formatPercent(4.237), "+4.2%");
  assert.equal(formatPercent(-1.06), "−1.1%");
  assert.equal(formatPercent(0.01), "0.0%");
  assert.equal(formatPercent(null), "—");
});
