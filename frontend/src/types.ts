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

export interface Options {
  exchange: string;
  marketTypes: MarketType[];
  timeframes: Record<Mode, string[]>;
}
