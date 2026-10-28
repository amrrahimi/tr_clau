import assert from "node:assert/strict";
import { test } from "node:test";
import { loadSwitches, shownSignals } from "../src/scannerPanel.ts";
import type { ScanSignal } from "../src/types.ts";

test("scanner starts stopped; saved switches come back; bad data is ignored", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null };
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false, reliableOnly: true });
  store.set("trading-bot.scanner", JSON.stringify({ history: true, signals: false }));
  assert.deepEqual(loadSwitches(storage), { history: true, signals: false, reliableOnly: true });
  store.set("trading-bot.scanner", JSON.stringify({ history: true, signals: true, reliableOnly: false }));
  assert.equal(loadSwitches(storage).reliableOnly, false);
  store.set("trading-bot.scanner", JSON.stringify({ history: "yes", signals: 1 }));
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false, reliableOnly: true });
  store.set("trading-bot.scanner", "{broken");
  assert.deepEqual(loadSwitches(storage), { history: false, signals: false, reliableOnly: true });
});

test("signals filter: reliable only, at most 20, order kept", () => {
  const make = (i: number, reliable: boolean) => ({ base: `C${i}`, reliable } as unknown as ScanSignal);
  const all = Array.from({ length: 30 }, (_, i) => make(i, i % 3 === 0));
  assert.equal(shownSignals(all, false).length, 20);
  const good = shownSignals(all, true);
  assert.deepEqual(good.map((s) => s.base), ["C0", "C3", "C6", "C9", "C12", "C15", "C18", "C21", "C24", "C27"]);
});
