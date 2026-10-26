// Shapes of the data the backend sends. They match backend/app/server.py.

export type MarketType = "spot" | "futures";
export type Mode = "scalping" | "daily";

export interface Candle {
  time: number; // seconds since 1970, UTC
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketInfo {
  symbol: string; // e.g. "BTC/USDT" (spot) or "BTC/USDT:USDT" (futures)
  base: string; // e.g. "BTC"
  quote: string; // e.g. "USDT"
  volume24h: number;
  lastPrice: number | null;
}

// ---------- phase 2: analysis (matches backend/app/analysis.py) ----------

export type MarketState = "trend_up" | "trend_down" | "range" | "volatile" | "unknown";

/** Field names match the backend so they can be sent as they are. */
export interface IndicatorSettings {
  ema_fast_on: boolean;
  ema_fast: number;
  ema_slow_on: boolean;
  ema_slow: number;
  bb_on: boolean;
  bb_period: number;
  bb_mult: number;
  rsi_on: boolean;
  rsi_period: number;
  atr_period: number;
}

export interface LinePoint {
  time: number;
  value: number;
}

export type LineName = "emaFast" | "emaSlow" | "bbUpper" | "bbMiddle" | "bbLower" | "rsi";

export interface Analysis {
  auto: boolean;
  tradingMode: Mode;
  settings: IndicatorSettings;
  state: {
    current: MarketState;
    since: number | null;
    adx: number | null;
    atrRatio: number | null;
  };
  atr: number | null;
  lastClosedTime: number | null;
  lines: Partial<Record<LineName, LinePoint[]>>;
  stateChanges: { time: number; state: MarketState }[];
}

export interface Options {
  exchange: string;
  marketTypes: MarketType[];
  timeframes: Record<Mode, string[]>;
}
