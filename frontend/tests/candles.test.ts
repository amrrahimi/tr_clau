import assert from "node:assert/strict";
import { test } from "node:test";
import { applyLiveCandle, prependOlder, pricePrecision } from "../src/candles.ts";
import type { Candle } from "../src/types.ts";

const c = (time: number, close = 1): Candle => ({ time, open: close, high: close, low: close, close, volume: 1 });

test("live candle with the same time updates the last candle", () => {
  const list = [c(60), c(120, 1)];
  assert.equal(applyLiveCandle(list, c(120, 5)), "update");
  assert.equal(list.length, 2);
  assert.equal(list[1].close, 5);
});

test("live candle with a later time is appended", () => {
  const list = [c(60)];
  assert.equal(applyLiveCandle(list, c(120)), "append");
  assert.deepEqual(list.map((x) => x.time), [60, 120]);
});

test("live candle older than the last one is ignored", () => {
  const list = [c(60), c(120)];
  assert.equal(applyLiveCandle(list, c(60, 9)), "ignore");
  assert.equal(list[0].close, 1);
});

test("first live candle into an empty list is appended", () => {
  const list: Candle[] = [];
  assert.equal(applyLiveCandle(list, c(60)), "append");
});

test("older candles go in front, sorted, without duplicates or overlap", () => {
  const existing = [c(180), c(240)];
  const older = [c(120), c(60), c(180), c(120)];
  const { candles, added } = prependOlder(older, existing);
  assert.deepEqual(candles.map((x) => x.time), [60, 120, 180, 240]);
  assert.equal(added, 2);
});

test("no older candles means nothing added", () => {
  const { added } = prependOlder([c(240)], [c(180), c(240)]);
  assert.equal(added, 0);
});

test("price precision follows the size of the price", () => {
  assert.equal(pricePrecision(65000), 2);
  assert.equal(pricePrecision(3.5), 4);
  assert.equal(pricePrecision(0.12), 4); // 0.1234
  assert.equal(pricePrecision(0.00001234), 8); // 0.00001234
  assert.equal(pricePrecision(0), 2);
});
