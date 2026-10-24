// Pure functions for keeping the candle list correct. No screen code here,
// so these can be tested on their own.

import type { Candle } from "./types.ts";

export type LiveAction = "update" | "append" | "ignore";

/**
 * Apply one live candle to the list (the list is changed in place).
 * - same time as the last candle: the current candle's price moved -> update
 * - later time: a new candle started -> append
 * - earlier time: an old, already-closed candle -> ignore (the chart can only
 *   change its latest candle)
 */
export function applyLiveCandle(candles: Candle[], candle: Candle): LiveAction {
  const last = candles[candles.length - 1];
  if (!last || candle.time > last.time) {
    candles.push(candle);
    return "append";
  }
  if (candle.time === last.time) {
    candles[candles.length - 1] = candle;
    return "update";
  }
  return "ignore";
}

/** Put older candles in front of the current list, without duplicates, oldest first. */
export function prependOlder(older: Candle[], existing: Candle[]): { candles: Candle[]; added: number } {
  const firstTime = existing.length ? existing[0].time : Infinity;
  const fresh = older.filter((c) => c.time < firstTime).sort((a, b) => a.time - b.time);
  const unique: Candle[] = [];
  for (const c of fresh) {
    if (!unique.length || unique[unique.length - 1].time !== c.time) unique.push(c);
  }
  return { candles: [...unique, ...existing], added: unique.length };
}

/**
 * How many decimals to show for a price. BTC at 60000 needs 2,
 * a coin at 0.0001234 needs about 8, so it is based on the price size.
 */
export function pricePrecision(price: number): number {
  if (!Number.isFinite(price) || price <= 0) return 2;
  if (price >= 1000) return 2;
  if (price >= 1) return 4;
  // Keep about 4 significant digits for small prices.
  const leadingZeros = Math.floor(-Math.log10(price));
  return Math.min(10, leadingZeros + 4);
}
