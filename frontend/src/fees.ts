// Trading fee rates (percent of an order's value), per market type. The
// defaults come from the backend; the user's own rates are remembered here.
// No screen code, so it can be tested.

import type { MarketType } from "./types.ts";

export interface FeeRates {
  maker: number; // waiting limit order (our take-profit)
  taker: number; // market order (entry, stop-loss, time exit)
}

export type FeeOverrides = Partial<Record<MarketType, FeeRates>>;

const STORAGE_KEY = "trading-bot.fees";
export const MAX_FEE = 1; // percent, same limit as the backend

export function validFee(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= MAX_FEE;
}

export function loadFees(storage: Pick<Storage, "getItem"> | null = safeStorage()): FeeOverrides {
  try {
    const data = JSON.parse(storage?.getItem(STORAGE_KEY) ?? "{}") as Record<string, Partial<FeeRates>>;
    const out: FeeOverrides = {};
    for (const market of ["spot", "futures"] as MarketType[]) {
      const r = data?.[market];
      if (r && typeof r.maker === "number" && typeof r.taker === "number" && validFee(r.maker) && validFee(r.taker)) {
        out[market] = { maker: r.maker, taker: r.taker };
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveFees(fees: FeeOverrides, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(fees));
  } catch {
    // not remembered; the defaults are used next time
  }
}

/** The user's rates for this market, or the defaults. */
export function effectiveFees(defaults: Record<MarketType, FeeRates> | undefined, mine: FeeOverrides, market: MarketType): FeeRates | null {
  return mine[market] ?? defaults?.[market] ?? null;
}

/** Store the user's rates; rates equal to the defaults are not stored. */
export function setFees(mine: FeeOverrides, market: MarketType, rates: FeeRates, defaults?: FeeRates): FeeOverrides {
  const out = { ...mine };
  if (defaults && rates.maker === defaults.maker && rates.taker === defaults.taker) delete out[market];
  else out[market] = rates;
  return out;
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}
