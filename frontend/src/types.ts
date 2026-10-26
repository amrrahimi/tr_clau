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

// ---------- analysis and indicators (match backend/app/catalog.py and analysis.py) ----------

export type MarketState = "trend_up" | "trend_down" | "range" | "volatile" | "unknown";

/** One setting of an indicator, from the backend's catalog. */
export interface ParamSpec {
  name: string; // e.g. "length"
  default: number;
  min: number;
  max: number;
  step: number; // 1 = whole numbers only
}

/** One indicator the app can draw (a "spec card"). */
export interface CatalogSpec {
  type: string; // e.g. "ema"
  name: string; // e.g. "EMA"
  pane: "price" | "own";
  params: ParamSpec[];
  outputs: { key: string; color: string; style: "line" | "histogram" }[];
  levels: number[];
  scale: [number, number] | null;
  candle_colors: boolean;
}

/** One indicator placed on the chart with its own settings. */
export interface IndicatorInstance {
  id: string;
  type: string;
  params: Record<string, number>;
}

export interface SeriesPoint {
  time: number;
  value: number;
  color?: string; // volume bars take the candle's colour
}

/** The lines of one indicator instance, as calculated by the backend. */
export interface IndicatorResult {
  id: string;
  type: string;
  name: string;
  label: string; // e.g. "EMA 21"
  pane: "price" | "own";
  params: Record<string, number>;
  levels: number[];
  scale: [number, number] | null;
  outputs: { key: string; color: string; style: "line" | "histogram"; points: SeriesPoint[] }[];
}

export interface Analysis {
  auto: boolean;
  tradingMode: Mode;
  indicators: IndicatorResult[];
  state: {
    current: MarketState;
    since: number | null;
    adx: number | null;
    atrRatio: number | null;
  };
  atr: number | null;
  atrLength: number;
  lastClosedTime: number | null;
  stateChanges: { time: number; state: MarketState }[];
}

export interface Options {
  exchange: string;
  marketTypes: MarketType[];
  timeframes: Record<Mode, string[]>;
}
