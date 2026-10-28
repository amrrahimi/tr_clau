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
  signal?: TradeSignal | null; // details of nextSignal
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
  stats: Pick<StrategyStats, "netPercent" | "trades" | "profitFactor"> & Partial<Pick<StrategyStats, "winRate">>;
}

/** A strategy's signal on the last closed candle: the trade it would open at the next candle. */
export interface TradeSignal {
  side: Side;
  time: number; // the signal candle
  entry: number; // about the next candle's open
  stopLoss: number;
  takeProfit: number;
  confirmedAt: number; // when the signal candle closed; the trade opens then
}

export interface ScanSignal extends ScanEntry {
  signal: TradeSignal;
  reliable: boolean; // meets the cautious conditions
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
  signals: ScanSignal[]; // latest 20, newest first
}

// ---------- paper trading bot (match backend/app/paper.py) ----------

export interface PaperPosition {
  id: number;
  symbol: string;
  base: string;
  timeframe: string;
  strategy: string;
  side: Side;
  entryTime: number; // seconds
  entryPrice: number;
  entryCandle: number; // start time of the candle the trade opened in
  stopLoss: number; // the original stop (for the red box)
  stop: number; // the current stop (moves to break-even)
  takeProfit: number;
  quantity: number;
  notional: number; // position value, USDT
  leverage: number;
  margin: number; // USDT set aside
  risk: number; // USDT lost at the stop, fees included
  liquidation: number;
  breakevenAt: number | null;
  history: { trades: number; winRate: number | null; profitFactor: number | null };
  lastPrice?: number | null; // open positions
  openPnl?: number | null;
}

export interface PaperTrade extends PaperPosition {
  exitPrice: number;
  exitTime: number;
  exitReason: "target" | "stop" | "breakeven";
  pnl: number; // USDT after fees
  fees: number;
  pnlPercent: number; // of the margin
}

export interface PaperEvent {
  time: number;
  kind: "start" | "stop" | "reset" | "open" | "close" | "halted" | "error" | "skip";
  count?: number; // skip "full": how many signals had no room
  symbol?: string;
  side?: Side;
  timeframe?: string;
  strategy?: string;
  leverage?: number;
  reason?: string;
  pnl?: number;
  capital?: number;
  message?: string;
}

export interface PaperState {
  capital: number;
  balance: number;
  equity: number;
  status: "stopped" | "running" | "halted";
  pausedToday: boolean;
  mode: "auto" | "manual";
  strategies: string[];
  positions: PaperPosition[];
  closed: PaperTrade[]; // newest first
  events: PaperEvent[]; // newest first
  stats: {
    trades: number;
    wins: number;
    winRate: number | null;
    netPnl: number;
    netPercent: number;
    todayPnl: number;
    fees: number;
    maxDrawdown: number; // percent
  };
  scanning: string | null; // timeframe being scanned now
  lastScan: Record<string, { period: number; time: number }>;
  timeframes: string[];
  rules: { risk: number; maxOpen: number; maxFast?: number; maxSlow?: number; maxSameSide?: number;
    maxLeverage: number; dailyStop: number; totalStop: number;
    fees: { maker: number; taker: number } };
}
