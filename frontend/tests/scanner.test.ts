import assert from "node:assert/strict";
import { test } from "node:test";
import { loadSwitches } from "../src/scannerPanel.ts";

test("scanner starts stopped; saved switches come back; bad data is ignored", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null };
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false });
  store.set("trading-bot.scanner", JSON.stringify({ history: true, signals: false }));
  assert.deepEqual(loadSwitches(storage), { history: true, signals: false });
  store.set("trading-bot.scanner", JSON.stringify({ history: "yes", signals: 1 }));
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false });
  store.set("trading-bot.scanner", "{broken");
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false });
});
