import assert from "node:assert/strict";
import { test } from "node:test";
import { parseLiveMessage, waitForBackend } from "../src/api.ts";
import { displaySymbol, formatLocalDateTime, formatLocalTick, formatPrice, formatVolume } from "../src/format.ts";
import { DEFAULT_LANGUAGE, direction, loadLanguage, saveLanguage, translate } from "../src/i18n.ts";
import { en } from "../src/locales/en.ts";
import { fa } from "../src/locales/fa.ts";

test("Persian and English have exactly the same keys, none empty", () => {
  assert.deepEqual(Object.keys(fa).sort(), Object.keys(en).sort());
  for (const [key, value] of [...Object.entries(fa), ...Object.entries(en)]) {
    assert.ok(value.trim().length > 0, `empty text for ${key}`);
  }
});

test("placeholders are the same in both languages", () => {
  const holes = (s: string) => (s.match(/\{\w+\}/g) ?? []).sort().join();
  for (const key of Object.keys(en) as (keyof typeof en)[]) {
    assert.equal(holes(fa[key]), holes(en[key]), key);
  }
});

test("translate fills placeholders", () => {
  assert.equal(translate("en", "error.generic", { detail: "boom" }), "Something went wrong: boom");
  assert.ok(translate("fa", "error.generic", { detail: "boom" }).includes("boom"));
});

test("direction follows the language", () => {
  assert.equal(direction("fa"), "rtl");
  assert.equal(direction("en"), "ltr");
});

test("language is remembered, and broken storage falls back to Persian", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  assert.equal(loadLanguage(storage), DEFAULT_LANGUAGE);
  saveLanguage("en", storage);
  assert.equal(loadLanguage(storage), "en");
  const broken = { getItem: () => { throw new Error("blocked"); } };
  assert.equal(loadLanguage(broken), "fa");
  assert.doesNotThrow(() => saveLanguage("en", { setItem: () => { throw new Error("blocked"); } }));
});

test("formatting prices, volumes and symbols", () => {
  assert.equal(formatPrice(65432.1, 2), "65,432.10");
  assert.equal(formatPrice(null, 2), "—");
  assert.equal(formatVolume(1_234_567), "1.23M");
  assert.equal(formatVolume(950), "950");
  assert.equal(formatVolume(0), "—");
  assert.equal(displaySymbol("BTC/USDT:USDT"), "BTC/USDT");
});

test("chart times are shown in local time", () => {
  // Tests run with TZ=Europe/Moscow (UTC+3): 14:20 UTC is 17:20 local.
  const t = Date.UTC(2026, 9, 24, 14, 20) / 1000;
  assert.equal(formatLocalDateTime(t), "2026-10-24 17:20");
  assert.equal(formatLocalTick(t, 3), "17:20");
  assert.equal(formatLocalTick(t, 2), "24");
  assert.equal(formatLocalTick(t, 1), "Oct");
  assert.equal(formatLocalTick(t, 0), "2026");
});

test("waiting for the backend: answers after a few failed tries", async () => {
  let calls = 0;
  const fakeFetch = (async () => {
    calls++;
    if (calls < 3) throw new TypeError("connection refused");
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  assert.equal(await waitForBackend("http://127.0.0.1:8765", 1000, 1, fakeFetch), true);
  assert.equal(calls, 3);
});

test("waiting for the backend: gives up after the timeout", async () => {
  const neverUp = (async () => { throw new TypeError("connection refused"); }) as typeof fetch;
  assert.equal(await waitForBackend("http://127.0.0.1:8765", 30, 5, neverUp), false);
});

test("live messages are read safely", () => {
  const candle = { time: 60, open: 1, high: 2, low: 0.5, close: 1.5, volume: 3 };
  assert.deepEqual(parseLiveMessage(JSON.stringify({ type: "candle", candle })), { type: "candle", candle });
  assert.deepEqual(parseLiveMessage(JSON.stringify({ type: "error", message: "x" })), { type: "error", message: "x" });
  assert.equal(parseLiveMessage("not json").type, "unknown");
  assert.equal(parseLiveMessage(JSON.stringify({ type: "candle", candle: { time: "60" } })).type, "unknown");
});
