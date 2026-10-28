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
  fees: Record<MarketType, { maker: number; taker: number }>; // default fee rates, percent
}

// ---------- strategies (match backend/app/strategies.py) ----------

/** One strategy card from the backend. */
export interface StrategyCard {
  type: string; // e.g. "ema_cross"
  name: string; // e.g. "EMA Cross"
  states: MarketState[]; // market states it suits
  uses: string[]; // indicators it reads, e.g. ["EMA", "ATR"]
  params: ParamSpec[];
  modeDefaults: Record<string, Record<Mode, number>>; // e.g. trend EMA: scalping 50, daily 200
}

export type Side = "long" | "short";

/** One past (or still open) trade of a strategy. */
export interface Trade {
  side: Side;
  signalTime: number;
  entryTime: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  exitTime: number | null; // null while open
  exitPrice: number | null;
  exitReason: "target" | "stop" | "breakeven" | "time" | null;
  breakevenTime: number | null; // when the stop moved to the entry price
  result: "win" | "loss" | "breakeven" | "open";
  pnlPercent: number | null; // after fees
  grossPercent: number | null; // before fees
  feePercent: number | null; // both fees, in percent of the entry value
  r: number | null;
}

export interface StrategyStats {
  trades: number; // closed trades
  wins: number;
  losses: number;
  breakevens: number; // closed at the entry price (no profit, no loss)
  open: number;
  winRate: number | null;
  profitFactor: number | null; // null when there is no loss yet
  netPercent: number; // sum of trade results after fees, %
  feePercent: number; // sum of all fees, %
  feesIncluded: boolean;
}

export interface StrategyRow {
  strategy: string;
  name: string;
  params: Record<string, number>;
  stats: StrategyStats;
  nextSignal: Side | null;
}

export interface StrategyOverview {
  rows: StrategyRow[];
  active: { strategy: string; trades: Trade[] } | null;
  marketState: MarketState; // now, for dimming strategies that do not suit it
  autoRule: "cautious" | "max_profit" | null; // set when the bot picked the strategy
  choice: { strategy: string; profitFactor: number | null; trades: number; netPercent: number } | null;
  candles: number; // how many candles the results are based on
  fees: { maker: number; taker: number }; // rates used, percent
  firstTime: number | null;
  lastClosedTime: number | null;
}

// ---------- scanner (match backend/app/scanner.py) ----------

export interface ScanEntry {
  symbol: string;
  base: string;
  strategy: string;
  marketState: MarketState; // the coin's state now
  stats: Pick<StrategyStats, "netPercent" | "trades" | "profitFactor">;
}

export interface ScanResult {
  running: boolean;
  done: number;
  total: number;
  failed: string[]; // coins that could not be scanned
  error: string | null;
  finishedAt: number | null; // seconds; time of the tables shown
  maxProfit: ScanEntry[];
  cautious: ScanEntry[];
}
