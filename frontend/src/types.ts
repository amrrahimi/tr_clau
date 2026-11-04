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
  range24h?: number; // 24h high-low range, % of the price
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
  exitReason: "target" | "stop" | "breakeven" | "time" | "manual" | "cap" | "lock" | null;
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
  breakevenPart?: number;   // share of the way to the target that moves the stop to break-even (0 = off)
  breakevenPrice?: number;  // entry price plus both fees: the stop there loses nothing
  edited?: boolean;         // the owner moved the stop or the target on the chart
  entryType?: "market" | "limit";   // how it was entered (older trades: market)
  openRisk?: number;        // USDT lost at the stop when it opened (before the owner moved the stop)
  lockedAt?: number | null; // when the profit lock moved the stop
  /** Half way to the target the bot looks again and advises: hold or close (the owner answers). */
  advice?: { time: number; suggest: "hold" | "close"; reason: "fine" | "opposite" | "state" | "unknown";
    detail: string; pnl: number; answer: "hold" | null } | null;
  history: { trades: number; winRate: number | null; profitFactor: number | null };
  lastPrice?: number | null; // open positions
  openPnl?: number | null;
}

export interface PaperTrade extends PaperPosition {
  exitPrice: number;
  exitTime: number;
  exitReason: "target" | "stop" | "breakeven" | "manual" | "cap" | "lock";
  pnl: number; // USDT after fees
  fees: number;
  pnlPercent: number; // of the margin
}

export interface PaperEvent {
  time: number;
  kind: "start" | "stop" | "reset" | "open" | "close" | "halted" | "error" | "skip" | "pause" | "resume" | "brain" | "pretrain" | "advice"
    | "ai" | "ask" | "askAnswer" | "levels" | "order" | "orderCancel";
  price?: number; // order: the limit price
  entryType?: "market" | "limit"; // open: how it was entered
  what?: "stop" | "target"; // levels: which line the owner moved
  old?: number; // levels: price before
  new?: number; // levels: price after
  approve?: boolean; // ai: Gemini's answer
  confidence?: number | null; // ai
  text?: string; // ai: its one-line reason
  answer?: "open" | "skip" | "auto"; // askAnswer: the owner's answer, or "auto" after 30 s
  suggest?: "hold" | "close"; // advice
  detail?: string; // advice: the strategy or market state behind it
  version?: number; // brain: model number
  until?: number; // pause: until when
  strategies?: string[]; // pause: strategies left out
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

/** Results of a set of signals, in R (multiples of the risk). */
export interface BrainResults {
  count: number;
  sumR: number;
  avgR: number | null;
  winRate: number | null;
}

/** The bot's learning filter (step B). */
export interface BrainState {
  state: "collecting" | "active" | "off";
  samples: number; // finished signals in the memory
  needed: number; // needed before the first model
  model: {
    version: number;
    trainedAt: number;
    threshold: number;
    on: boolean;
    test: { kept: BrainResults; all: BrainResults }; // on signals it had not seen
    testedOn?: "live" | "history";
  } | null;
  pretrain?: { done: number; total: number; running: boolean };
  lastTraining: { time: number; result: string } | null;
  nextTraining: number | null; // seconds
}

/** How the engine reaches the exchange. */
export interface ConnectionState {
  proxy: string | null;
  source: "app" | "system" | "direct";
  typed: string; // what the owner typed ("" = use the computer's setting)
}

/** One strategy's real results (manual mode list). R: result in units of the risk (-1R = the stop). */
export interface StrategyResults {
  bot?: { count: number; winRate: number; netPnl: number }; // the bot's own closed trades
  signals?: { count: number; winRate: number | null; avgR: number | null }; // every reliable signal that ended
  brain?: { count: number; winRate: number | null; avgR: number | null }; // those the brain's filter lets through
}

export interface AiState {
  enabled: boolean;
  timeframes: string[];
  model: string;
  keys: string[]; // only the last 4 characters of each key
  lastError: string | null;
  results: Record<string, { count: number; avgR: number | null; winRate: number | null }>;
}

export interface AiTestResult {
  key: string; // last 4 characters only
  ok: boolean;
  seconds: number | null;
  model?: string | null; // the Gemini model that answered
  error: string | null;
}

export interface PendingAsk {
  id: number; symbol: string; base: string; timeframe: string; strategy: string; side: Side;
  entry: number; stopLoss: number; takeProfit: number; expires: number; error?: string | null;
}

/** A limit order waiting to fill (limit entry, paper only). */
export interface PaperOrder {
  id: number;
  symbol: string;
  base: string;
  timeframe: string;
  strategy: string;
  side: Side;
  price: number;        // the limit price
  placedPrice: number;  // the price when it was placed
  placedAt: number;     // seconds
  expires: number;      // seconds
  stopLoss: number;
  takeProfit: number;
  margin: number;       // USDT set aside for it
}

export interface EntryStats {
  trades: number;
  winRate: number | null;
  avgR: number | null;
  fees: number;
}

export interface PaperState {
  ai?: AiState;
  pendingAsks?: PendingAsk[];
  profile?: "main"; // the bot (the barrage account was removed 2026-11-02)
  scanSeconds?: Record<string, number>; // how long the last scan of each timeframe took
  chosenTimeframes?: string[]; // ticked by the owner: the bot trades only on these
  /** What happened to the signals in the last minutes (skipped: reason -> count). */
  flow?: { minutes: number; seen: number; opened: number; placed?: number; skipped: Record<string, number> };
  limitEntry?: boolean;                 // the owner's switch: enter with limit orders (paper only)
  orders?: PaperOrder[];                // limit orders waiting to fill
  entryStats?: { market: EntryStats; limit: EntryStats & { fillRate: number | null;
    orders: { placed: number; filled: number; expired: number; cancelled: number } } };
  capital: number;
  balance: number;
  equity: number;
  status: "stopped" | "running" | "halted";
  pausedUntil: number | null; // smart pause: no new trades until then (seconds)
  pauseReason: "streak" | "fall" | null;
  benched: Record<string, number>; // strategies left out until (seconds)
  strategyStats?: Record<string, StrategyResults>;
  botStrategies?: Record<string, string[]>; // timeframe -> strategies the bot trades there ([] = not traded)
  memory: {
    signals: number; // live signals the bot saw
    reliable?: number;
    open: number;
    wins: number;
    losses: number;
    ended: number;
    taken: number;
    trades: number;
    history?: number; // past signals rebuilt from the candle history
    finished?: number;
    charts?: number;
  } | null;
  brain?: BrainState | null;
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
  rules: { risk: number; maxOpen: number | null; maxFast?: number; maxSlow?: number; maxSameSide?: number | null; brainThreshold?: number | null; coinMode?: "top" | "volatile" | "manual"; coins?: string[]; volatileCoins?: number;
    maxLeverage: number; pauseLosses?: number; pauseFall?: number; pauseHours?: number; recoverWins?: number; profitCap?: number; totalStop: number;
    smartPause?: boolean; allSignals?: boolean; strictTrades?: number; strictProfitFactor?: number;
    limitOffset?: number; limitExpireCandles?: number;   // limit entry: % of the stop distance, candles
    lock?: { enabled: boolean; trigger: number; at: number };   // profit lock: % of the way to the target
    fees: { maker: number; taker: number } };
}
