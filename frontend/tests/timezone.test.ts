import assert from "node:assert/strict";
import { test } from "node:test";
import { formatClock, formatLocalDateTime, formatLocalTick, formatSince } from "../src/format.ts";
import { DEFAULT_ZONE, ZONES, formatOffset, isKnownZone, loadZone, offsetMinutes, saveZone, zoneParts } from "../src/timezone.ts";

const SUMMER = Date.UTC(2026, 6, 15, 12, 0); // 15 July 2026, 12:00 UTC
const WINTER = Date.UTC(2026, 0, 15, 12, 0); // 15 January 2026, 12:00 UTC

test("every listed zone is known to this computer", () => {
  for (const z of ZONES) assert.ok(isKnownZone(z.id), z.id);
});

test("fixed-offset zones", () => {
  assert.equal(offsetMinutes(SUMMER, "UTC"), 0);
  assert.equal(offsetMinutes(SUMMER, "Asia/Tehran"), 210); // Iran has no daylight saving time
  assert.equal(offsetMinutes(SUMMER, "Asia/Tokyo"), 540);
  assert.equal(offsetMinutes(SUMMER, "Europe/Moscow"), 180);
});

test("daylight saving time moves London and New York", () => {
  assert.equal(offsetMinutes(SUMMER, "Europe/London"), 60);
  assert.equal(offsetMinutes(WINTER, "Europe/London"), 0);
  assert.equal(offsetMinutes(SUMMER, "America/New_York"), -240);
  assert.equal(offsetMinutes(WINTER, "America/New_York"), -300);
  assert.equal(offsetMinutes(SUMMER, "Australia/Sydney"), 600); // southern winter
  assert.equal(offsetMinutes(WINTER, "Australia/Sydney"), 660);
});

test("same moment, different clock in each zone", () => {
  const t = SUMMER / 1000;
  assert.equal(formatLocalDateTime(t, "UTC"), "2026-07-15 12:00");
  assert.equal(formatLocalDateTime(t, "Asia/Tehran"), "2026-07-15 15:30");
  assert.equal(formatLocalDateTime(t, "America/New_York"), "2026-07-15 08:00");
  assert.equal(formatLocalDateTime(t, "Asia/Tokyo"), "2026-07-15 21:00");
  // Tests run with TZ=Europe/Moscow, so "local" is Moscow.
  assert.equal(formatLocalDateTime(t, "local"), "2026-07-15 15:00");
});

test("date changes across midnight in the zone", () => {
  const t = Date.UTC(2026, 6, 15, 22, 30) / 1000;
  assert.equal(formatLocalTick(t, 2, "UTC"), "15");
  assert.equal(formatLocalTick(t, 2, "Asia/Tokyo"), "16");
  assert.equal(formatLocalTick(t, 3, "Asia/Tokyo"), "07:30");
});

test("clock and 'since' in a zone", () => {
  assert.equal(formatClock(SUMMER + 7_000, "Asia/Tehran"), "15:30:07");
  const since = Date.UTC(2026, 6, 15, 9, 0) / 1000;
  assert.equal(formatSince(since, SUMMER, "Europe/London"), "10:00");
  assert.equal(formatSince(since, SUMMER + 86_400_000, "Europe/London"), "2026-07-15 10:00");
});

test("offset text", () => {
  assert.equal(formatOffset(0), "UTC");
  assert.equal(formatOffset(210), "UTC+3:30");
  assert.equal(formatOffset(-300), "UTC-5");
  assert.equal(formatOffset(330), "UTC+5:30");
});

test("parts in UTC", () => {
  assert.deepEqual(zoneParts(SUMMER, "UTC"), { year: 2026, month: 7, day: 15, hour: 12, minute: 0, second: 0 });
});

test("choice is remembered; unknown or broken values fall back to local", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  assert.equal(loadZone(storage), DEFAULT_ZONE);
  saveZone("Europe/London", storage);
  assert.equal(loadZone(storage), "Europe/London");
  saveZone("Mars/Olympus", storage);
  assert.equal(loadZone(storage), "local");
  assert.equal(loadZone({ getItem: () => { throw new Error("blocked"); } }), "local");
});
