import assert from "node:assert/strict";
import { test } from "node:test";
import { effectiveFees, loadFees, saveFees, setFees, validFee } from "../src/fees.ts";

const defaults = { spot: { maker: 0.075, taker: 0.1 }, futures: { maker: 0.02, taker: 0.06 } };

test("defaults until the user sets own rates, per market type", () => {
  assert.deepEqual(effectiveFees(defaults, {}, "spot"), { maker: 0.075, taker: 0.1 });
  const mine = setFees({}, "spot", { maker: 0, taker: 0 }, defaults.spot);
  assert.deepEqual(effectiveFees(defaults, mine, "spot"), { maker: 0, taker: 0 });
  assert.deepEqual(effectiveFees(defaults, mine, "futures"), defaults.futures);
  // Setting the defaults again forgets the user's rates.
  assert.deepEqual(setFees(mine, "spot", { ...defaults.spot }, defaults.spot), {});
  assert.equal(effectiveFees(undefined, {}, "spot"), null);
});

test("saved rates survive a restart; bad values are dropped", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  saveFees({ futures: { maker: 0.01, taker: 0.05 } }, storage);
  assert.deepEqual(loadFees(storage), { futures: { maker: 0.01, taker: 0.05 } });
  store.set("trading-bot.fees", JSON.stringify({ spot: { maker: 5, taker: 0.1 }, futures: { maker: "x" } }));
  assert.deepEqual(loadFees(storage), {});
  store.set("trading-bot.fees", "{broken");
  assert.deepEqual(loadFees(storage), {});
});

test("fee range", () => {
  assert.ok(validFee(0) && validFee(1) && validFee(0.075));
  assert.ok(!validFee(-0.1) && !validFee(1.5) && !validFee(Number.NaN));
});
