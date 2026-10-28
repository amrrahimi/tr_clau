// A pretend backend with made-up prices, for the preview and for working on
// the screen without the Python backend. Prices are random walks, NOT real data.

import type {
  AnalysisRequest, Backend, CandleRequest, LiveConnection, LiveHandlers, PaperAction, ScanRequest, StrategyRequest,
} from "./api.ts";
import { MOCK_CATALOG } from "./mockCatalog.ts";
import { MOCK_STRATEGIES } from "./mockStrategies.ts";
import type {
  Analysis, CatalogSpec, Candle, IndicatorInstance, IndicatorResult, MarketInfo, MarketState, MarketType, Options,
  PaperPosition, PaperState, PaperTrade, ScanEntry, ScanResult, ScanSignal, StrategyCard, StrategyOverview, StrategyRow, Trade,
} from "./types.ts";

const TIMEFRAME_SECONDS: Record<string, number> = {
  "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
  "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
};

// [coin, rough price, rough 24h volume in USDT]
const COINS: [string, number, number][] = [
  ["BTC", 67000, 2.1e9], ["ETH", 3400, 1.3e9], ["SOL", 160, 6.2e8], ["XRP", 0.58, 4.1e8],
  ["DOGE", 0.15, 3.6e8], ["BNB", 590, 2.2e8], ["TON", 6.8, 1.9e8], ["ADA", 0.45, 1.5e8],
  ["AVAX", 34, 1.4e8], ["LINK", 15.2, 1.2e8], ["SUI", 1.1, 1.1e8], ["PEPE", 0.0000112, 1.05e8],
  ["TRX", 0.13, 9.8e7], ["DOT", 6.9, 9.1e7], ["LTC", 82, 8.7e7], ["NEAR", 5.6, 8.2e7],
  ["APT", 8.9, 7.6e7], ["ARB", 0.92, 7.1e7], ["OP", 2.1, 6.6e7], ["SHIB", 0.0000235, 6.2e7],
  ["UNI", 9.8, 5.9e7], ["WIF", 2.4, 5.5e7], ["FIL", 5.4, 5.1e7], ["ATOM", 8.1, 4.8e7],
  ["INJ", 24, 4.5e7], ["TIA", 9.2, 4.2e7], ["SEI", 0.46, 3.9e7], ["RNDR", 7.8, 3.7e7],
  ["FET", 1.9, 3.5e7], ["BCH", 470, 3.3e7], ["ETC", 26, 3.1e7], ["HBAR", 0.09, 2.9e7],
  ["ICP", 11.5, 2.7e7], ["STX", 1.9, 2.5e7], ["IMX", 2.0, 2.3e7], ["MKR", 2600, 2.2e7],
  ["AAVE", 98, 2.1e7], ["GRT", 0.27, 2.0e7], ["ALGO", 0.18, 1.9e7], ["VET", 0.033, 1.8e7],
  ["XLM", 0.11, 1.7e7], ["EGLD", 38, 1.6e7], ["SAND", 0.42, 1.5e7], ["MANA", 0.44, 1.4e7],
  ["AXS", 7.2, 1.3e7], ["FLOW", 0.83, 1.2e7], ["CHZ", 0.11, 1.1e7], ["GALA", 0.038, 1.0e7],
  ["CRV", 0.45, 9.5e6], ["LDO", 2.0, 9.0e6], ["DYDX", 1.8, 8.5e6], ["ENS", 21, 8.0e6],
  ["WBTC", 66900, 7.5e6], ["ZEC", 26, 7.0e6], ["KAVA", 0.62, 6.5e6], ["ONE", 0.018, 6.0e6],
];

/** Small deterministic random generator, so the same coin always draws the same history. */
function seeded(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13; state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5; state >>>= 0;
    return state / 4294967296;
  };
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

export class MockBackend implements Backend {
  private readonly now: () => number;
  private readonly historyDepth = 3000; // candles of made-up history per chart
  private series = new Map<string, Candle[]>();

  constructor(options: { now?: () => number } = {}) {
    this.now = options.now ?? (() => Math.floor(Date.now() / 1000));
  }

  async getOptions(): Promise<Options> {
    return {
      exchange: "toobit",
      marketTypes: ["spot", "futures"],
      timeframes: { scalping: ["1m", "3m", "5m", "15m"], daily: ["15m", "30m", "1h", "2h", "4h", "6h", "1d"] },
      fees: { spot: { maker: 0.075, taker: 0.1 }, futures: { maker: 0.02, taker: 0.06 } },
    };
  }

  async getMarkets(marketType: MarketType, query = ""): Promise<MarketInfo[]> {
    const futures = marketType === "futures";
    let list = COINS.map(([base, price, volume]) => ({
      symbol: futures ? `${base}/USDT:USDT` : `${base}/USDT`,
      base,
      quote: "USDT",
      volume24h: futures ? volume * 1.7 : volume,
      lastPrice: price,
    }));
    const text = query.trim().toUpperCase();
    if (text) {
      list = list.filter((m) => m.base.includes(text))
        .sort((a, b) => Number(a.base !== text) - Number(b.base !== text) || b.volume24h - a.volume24h);
      return list;
    }
    return list.sort((a, b) => b.volume24h - a.volume24h).slice(0, 50);
  }

  async getCandles(request: CandleRequest): Promise<Candle[]> {
    const all = this.history(request);
    const before = request.before ?? Infinity;
    const older = all.filter((c) => c.time < before);
    return older.slice(-500).map((c) => ({ ...c }));
  }

  async getCatalog(): Promise<CatalogSpec[]> {
    return MOCK_CATALOG;
  }

  private paper: PaperState | null = null;

  /** Preview only: a pretend bot account; starting it shows a few made-up trades. */
  async getPaper(): Promise<PaperState> {
    if (!this.paper) this.paper = this.emptyPaper(100);
    return this.paper;
  }

  async paperAction(action: PaperAction): Promise<PaperState> {
    const state = await this.getPaper();
    if (action.kind === "reset") this.paper = this.emptyPaper(action.capital);
    else if (action.kind === "stop") state.status = "stopped";
    else if (action.kind === "mode") {
      state.mode = action.mode;
      state.strategies = action.mode === "auto" ? MOCK_STRATEGIES.map((c) => c.type) : action.strategies;
    } else if (action.kind === "start") {
      state.status = "running";
      if (!state.positions.length && !state.closed.length) await this.sampleTrades(state);
    }
    return this.paper!;
  }

  private emptyPaper(capital: number): PaperState {
    return {
      capital, balance: capital, equity: capital, status: "stopped", pausedToday: false, mode: "auto",
      strategies: MOCK_STRATEGIES.map((c) => c.type), positions: [], closed: [], events: [],
      stats: { trades: 0, wins: 0, winRate: null, netPnl: 0, netPercent: 0, todayPnl: 0, fees: 0, maxDrawdown: 0 },
      scanning: null, lastScan: {}, timeframes: ["1m", "3m", "5m", "15m", "1h"],
      rules: { risk: 1, maxOpen: 6, maxFast: 3, maxSlow: 3, maxSameSide: 4, maxLeverage: 10, dailyStop: 5, totalStop: 30, fees: { maker: 0.02, taker: 0.06 } },
    };
  }

  private async sampleTrades(state: PaperState): Promise<void> {
    const candles = this.history({ marketType: "futures", symbol: "BTC/USDT:USDT", timeframe: "5m" });
    const at = (n: number) => candles[candles.length - n];
    const base = (n: number, side: "long" | "short", id: number): PaperPosition => {
      const c = at(n);
      const stop = side === "long" ? c.open * 0.995 : c.open * 1.005;
      const target = side === "long" ? c.open * 1.01 : c.open * 0.99;
      return { id, symbol: "BTC/USDT:USDT", base: "BTC", timeframe: "5m", strategy: "supertrend", side,
        entryTime: c.time + 5, entryPrice: c.open, entryCandle: c.time, stopLoss: stop, stop, takeProfit: target,
        quantity: 0.002, notional: c.open * 0.002, leverage: 3, margin: (c.open * 0.002) / 3, risk: 1,
        liquidation: c.open * (side === "long" ? 0.67 : 1.33), breakevenAt: null,
        history: { trades: 24, winRate: 46, profitFactor: 1.6 } };
    };
    const closedTrade = (p: PaperPosition, n: number, win: boolean): PaperTrade => ({
      ...p, exitPrice: win ? p.takeProfit : p.stopLoss, exitTime: at(n).time + 60, exitReason: win ? "target" : "stop",
      pnl: win ? 1.8 : -1, fees: 0.15, pnlPercent: win ? 9 : -5,
    });
    const open = base(6, "long", 3);
    open.lastPrice = at(1).close;
    open.openPnl = (at(1).close - open.entryPrice) * open.quantity;
    state.positions = [open];
    state.closed = [closedTrade(base(30, "short", 2), 20, true), closedTrade(base(60, "long", 1), 50, false)];
    state.balance = state.capital + 0.8;
    state.equity = state.balance + (open.openPnl ?? 0);
    state.stats = { trades: 2, wins: 1, winRate: 50, netPnl: state.equity - state.capital,
      netPercent: ((state.equity - state.capital) / state.capital) * 100, todayPnl: 0.8, fees: 0.3, maxDrawdown: 1 };
    const now = this.now();
    state.events = [
      { time: now - 30, kind: "open", symbol: "BTC", side: "long", timeframe: "5m", strategy: "supertrend", leverage: 3 },
      { time: now - 900, kind: "close", symbol: "BTC", reason: "target", pnl: 1.8 },
      { time: now - 2000, kind: "start" },
    ];
  }

  /** Preview only: the scanner over the first 12 coins, with the made-up strategy results. */
  async getScan(request: ScanRequest): Promise<ScanResult> {
    const coins = (await this.getMarkets(request.marketType)).slice(0, 12);
    const entries: ScanEntry[] = [];
    for (const coin of coins) {
      const overview = await this.getStrategyOverview({ ...request, symbol: coin.symbol, active: null, autoRule: null });
      for (const row of overview.rows) {
        entries.push({ symbol: coin.symbol, base: coin.base, strategy: row.strategy, marketState: overview.marketState, stats: row.stats });
      }
    }
    const best = (list: ScanEntry[], score: (e: ScanEntry) => number) => {
      const perCoin = new Map<string, ScanEntry>();
      for (const e of list) if (!perCoin.has(e.symbol) || score(e) > score(perCoin.get(e.symbol)!)) perCoin.set(e.symbol, e);
      return [...perCoin.values()].sort((a, b) => score(b) - score(a)).slice(0, 10);
    };
    const winners = entries.filter((e) => e.stats.trades > 0 && e.stats.netPercent > 0);
    // Preview only: a few made-up signals at the last closed candle.
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const last = Math.floor(this.now() / step) * step - step;
    const signals: ScanSignal[] = entries.filter((_, i) => i % 9 === 0).slice(0, 8).map((e, i) => {
      const price = coins.find((c) => c.symbol === e.symbol)?.lastPrice ?? 1;
      const long = i % 2 === 0;
      return { ...e, reliable: e.stats.trades >= 10 && e.stats.netPercent > 0, signal: {
        side: long ? "long" : "short", time: last - (i % 3) * step, entry: price,
        stopLoss: price * (long ? 0.99 : 1.01), takeProfit: price * (long ? 1.02 : 0.98), confirmedAt: last - (i % 3) * step + step } };
    });
    return {
      running: false, done: coins.length, total: coins.length, failed: [], error: null,
      finishedAt: this.now(),
      maxProfit: best(winners, (e) => e.stats.netPercent),
      signals,
      cautious: best(winners.filter((e) => e.stats.trades >= 10 && (e.stats.profitFactor ?? Infinity) > 1), (e) => e.stats.profitFactor ?? Infinity),
    };
  }

  async getStrategyCatalog(): Promise<StrategyCard[]> {
    return MOCK_STRATEGIES;
  }

  /**
   * Made-up strategy results for the preview only: every strategy here is a
   * simple moving-average cross with different lengths. The real rules are in
   * the Python backend (backend/app/strategies.py).
   */
  async getStrategyOverview(request: StrategyRequest): Promise<StrategyOverview> {
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const closed = this.history(request).filter((c) => c.time + step <= this.now()).slice(-1000);
    const rows: StrategyRow[] = [];
    let active: StrategyOverview["active"] = null;
    const allTrades = new Map<string, Trade[]>();
    MOCK_STRATEGIES.forEach((card, n) => {
      const trades = mockTrades(closed, 5 + n * 2, 15 + n * 4, 1.5 + (n % 3) * 0.5);
      const done = trades.filter((t) => t.result !== "open");
      const wins = done.filter((t) => t.result === "win").map((t) => t.pnlPercent ?? 0);
      const losses = done.filter((t) => t.result === "loss").map((t) => t.pnlPercent ?? 0);
      const grossLoss = -losses.reduce((a, b) => a + b, 0);
      rows.push({
        strategy: card.type,
        name: card.name,
        params: Object.fromEntries(card.params.map((p) => [p.name, p.default])),
        stats: {
          trades: done.length,
          wins: wins.length,
          losses: losses.length,
          breakevens: 0,
          open: trades.length - done.length,
          winRate: done.length ? (wins.length / done.length) * 100 : null,
          profitFactor: grossLoss > 0 ? wins.reduce((a, b) => a + b, 0) / grossLoss : null,
          netPercent: [...wins, ...losses].reduce((a, b) => a + b, 0),
          feePercent: 0,
          feesIncluded: false,
        },
        nextSignal: null,
        // Preview only: the active strategy pretends to signal on the last closed candle.
        signal: card.type === request.active && closed.length > 1 && !trades.some((t) => t.result === "open") ? {
          side: "long", time: closed[closed.length - 1].time, entry: closed[closed.length - 1].close,
          stopLoss: closed[closed.length - 1].close * 0.995, takeProfit: closed[closed.length - 1].close * 1.01,
          confirmedAt: closed[closed.length - 1].time + step,
        } : null,
      });
      if (card.type === request.active) active = { strategy: card.type, trades };
      allTrades.set(card.type, trades);
    });
    // Preview only: a simple version of the bot's pick (the real rule is in the backend).
    let choice: StrategyOverview["choice"] = null;
    if (request.autoRule) {
      const best = rows.filter((r) => r.stats.netPercent > 0 && r.stats.trades > 0)
        .sort((a, b) => b.stats.netPercent - a.stats.netPercent)[0];
      choice = best ? { strategy: best.strategy, profitFactor: best.stats.profitFactor, trades: best.stats.trades, netPercent: best.stats.netPercent } : null;
      active = choice ? { strategy: choice.strategy, trades: allTrades.get(choice.strategy) ?? [] } : null;
    }
    return {
      rows,
      active,
      firstTime: closed[0]?.time ?? null,
      lastClosedTime: closed[closed.length - 1]?.time ?? null,
      marketState: "range",
      autoRule: request.autoRule,
      choice,
      fees: request.fees ?? { maker: 0, taker: 0 },
      candles: closed.length,
    };
  }

  /**
   * Simplified analysis for the preview only. The real numbers come from the
   * Python backend (backend/app/analysis.py); this just draws plausible lines.
   */
  async getAnalysis(request: AnalysisRequest): Promise<Analysis> {
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const closed = this.history(request).filter((c) => c.time + step <= this.now());
    const closes = closed.map((c) => c.close);
    const [fastLen, slowLen, longLen] = request.tradingMode === "scalping" ? [9, 21, 50] : [20, 50, 200];
    const slow = ema(closes, slowLen);
    const last = closes.length - 1;
    const slope = (slow[last] ?? 0) - (slow[Math.max(0, last - 10)] ?? 0);
    const trendStrength = Math.abs(slope) / ((slow[last] ?? 1) * 0.002);
    const state: MarketState = trendStrength > 1 ? (slope > 0 ? "trend_up" : "trend_down") : "range";
    const autoList: IndicatorInstance[] = state === "range"
      ? [inst("auto-ema", "ema", { length: slowLen }), inst("auto-bb", "bb", { length: 20, mult: 2 }), inst("auto-rsi", "rsi", { length: 14 })]
      : [inst("a1", "ema", { length: fastLen }), inst("a2", "ema", { length: slowLen }), inst("a3", "ema", { length: longLen }), inst("auto-rsi", "rsi", { length: 14 })];
    const list = request.indicators ?? autoList;
    const shown = closed.slice(-500);
    const perType = new Map<string, number>();
    const indicators = list.map((i) => {
      const n = perType.get(i.type) ?? 0;
      perType.set(i.type, n + 1);
      return mockIndicator(i, closed, shown.length, n);
    });
    const ranges = closed.slice(-14).map((c) => c.high - c.low);
    return {
      auto: !request.indicators,
      tradingMode: request.tradingMode,
      indicators,
      state: {
        current: state,
        since: closed[Math.max(0, last - 37)]?.time ?? null,
        adx: Math.min(60, 12 + trendStrength * 14),
        atrRatio: 1,
      },
      atr: ranges.reduce((a, b) => a + b, 0) / Math.max(1, ranges.length),
      atrLength: 14,
      lastClosedTime: closed[last]?.time ?? null,
      stateChanges: [],
    };
  }

  openLive(request: CandleRequest, handlers: LiveHandlers): LiveConnection {
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const all = this.history(request);
    const random = seeded(hash(request.symbol) ^ this.now());
    const timer = setInterval(() => {
      const last = all[all.length - 1];
      const bucket = Math.floor(this.now() / step) * step;
      const move = last.close * (random() - 0.5) * 0.0016;
      if (bucket > last.time) {
        all.push({ time: bucket, open: last.close, high: last.close, low: last.close, close: last.close, volume: 0 });
      }
      const current = all[all.length - 1];
      current.close = Math.max(current.close + move, current.close * 0.5);
      current.high = Math.max(current.high, current.close);
      current.low = Math.min(current.low, current.close);
      current.volume += random() * 10;
      handlers.onCandle({ ...current });
    }, 1000);
    return { close: () => clearInterval(timer) };
  }

  private history(request: CandleRequest): Candle[] {
    const key = `${request.marketType}|${request.symbol}|${request.timeframe}`;
    const cached = this.series.get(key);
    if (cached) return cached;

    const base = request.symbol.split("/")[0];
    const start = COINS.find(([coin]) => coin === base)?.[1] ?? 1;
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const random = seeded(hash(key));
    const volatility = 0.002 * Math.sqrt(step / 60);
    const lastTime = Math.floor(this.now() / step) * step;

    // Walk backwards from today's price so the latest candle is near the real-looking price.
    const closes: number[] = [start];
    for (let i = 1; i < this.historyDepth; i++) {
      const drift = Math.sin(i / 90) * volatility * 0.3;
      closes.push(closes[i - 1] * (1 + (random() - 0.5) * 2 * volatility + drift));
    }
    closes.reverse();

    const candles: Candle[] = closes.map((close, i) => {
      const open = i === 0 ? close : closes[i - 1];
      const wick = close * volatility * random();
      return {
        time: lastTime - (this.historyDepth - 1 - i) * step,
        open,
        close,
        high: Math.max(open, close) + wick,
        low: Math.min(open, close) - wick * random(),
        volume: 100 + random() * 1000,
      };
    });
    this.series.set(key, candles);
    return candles;
  }
}

// ---------- small indicator helpers for the preview ----------

const PALETTE = ["#f7c948", "#ab47bc", "#26c6da", "#ff7043", "#66bb6a", "#ec407a"];

function inst(id: string, type: string, params: Record<string, number>): IndicatorInstance {
  return { id, type, params };
}

function mockIndicator(i: IndicatorInstance, candles: Candle[], keep: number, order: number): IndicatorResult {
  const spec = MOCK_CATALOG.find((s) => s.type === i.type)!;
  const p = { ...Object.fromEntries(spec.params.map((x) => [x.name, x.default])), ...i.params };
  const c = candles.map((x) => x.close);
  const h = candles.map((x) => x.high);
  const l = candles.map((x) => x.low);
  const series: Record<string, (number | null)[]> = {};
  switch (i.type) {
    case "ema": series.value = ema(c, p.length); break;
    case "sma": series.value = sma(c, p.length); break;
    case "wma": series.value = sma(c, p.length); break;
    case "bb": {
      const mid = sma(c, p.length);
      const dev = c.map((_, k) => (k < p.length - 1 ? null : std(c.slice(k - p.length + 1, k + 1))));
      series.basis = mid;
      series.upper = mid.map((m, k) => (m === null || dev[k] === null ? null : m + p.mult * (dev[k] as number)));
      series.lower = mid.map((m, k) => (m === null || dev[k] === null ? null : m - p.mult * (dev[k] as number)));
      break;
    }
    case "supertrend": {
      const mid = sma(c, p.atr_length);
      series.up = mid.map((m, k) => (m !== null && c[k] >= m ? m - (h[k] - l[k]) * p.factor : null));
      series.down = mid.map((m, k) => (m !== null && c[k] < m ? m + (h[k] - l[k]) * p.factor : null));
      break;
    }
    case "volume": series.volume = candles.map((x) => x.volume); break;
    case "rsi": series.rsi = rsi(c, p.length); break;
    case "macd": {
      const f = ema(c, p.fast), s2 = ema(c, p.slow);
      const m = f.map((v, k) => (v === null || s2[k] === null ? null : v - (s2[k] as number)));
      const sig = smooth(m, p.signal, 2 / (p.signal + 1));
      series.macd = m; series.signal = sig;
      series.hist = m.map((v, k) => (v === null || sig[k] === null ? null : v - (sig[k] as number)));
      break;
    }
    case "stoch": case "stochrsi": {
      const src = i.type === "stoch" ? c : rsi(c, 14).map((v) => v ?? 50);
      const len = i.type === "stoch" ? p.k_length : p.stoch_length;
      const k = src.map((v, n) => {
        if (n < len - 1) return null;
        const w = src.slice(n - len + 1, n + 1);
        const lo = Math.min(...w), hi = Math.max(...w);
        return hi === lo ? 50 : (100 * (v - lo)) / (hi - lo);
      });
      series.k = k; series.d = smaNullable(k, 3);
      break;
    }
    case "atr": series.atr = sma(h.map((v, k) => v - l[k]), p.length); break;
    case "dmi": {
      const r = rsi(c, p.length);
      series.plus = r.map((v) => (v === null ? null : v / 2));
      series.minus = r.map((v) => (v === null ? null : (100 - v) / 2));
      series.adx = r.map((v) => (v === null ? null : Math.abs(v - 50)));
      break;
    }
  }
  const cut = candles.length - keep;
  return {
    id: i.id,
    type: i.type,
    name: spec.name,
    label: [spec.name, ...spec.params.map((x) => String(p[x.name]))].join(" "),
    pane: spec.pane,
    params: p,
    levels: spec.levels,
    scale: spec.scale,
    outputs: spec.outputs.map((o) => ({
      key: o.key,
      style: o.style,
      color: spec.pane === "price" && spec.outputs.length === 1 && order ? PALETTE[order % PALETTE.length] : o.color,
      points: candles.slice(cut).flatMap((x, k) => {
        const v = series[o.key]?.[cut + k];
        if (v === null || v === undefined) return [];
        return [spec.candle_colors ? { time: x.time, value: v, color: x.close >= x.open ? "#089981" : "#f23645" } : { time: x.time, value: v }];
      }),
    })),
  };
}

function std(w: number[]): number {
  const m = w.reduce((a, b) => a + b, 0) / w.length;
  return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / w.length);
}

function smaNullable(values: (number | null)[], length: number): (number | null)[] {
  return values.map((_, i) => {
    if (i < length - 1) return null;
    const w = values.slice(i - length + 1, i + 1);
    return w.some((v) => v === null) ? null : (w as number[]).reduce((a, b) => a + b, 0) / length;
  });
}

function sma(values: number[], length: number): (number | null)[] {
  return values.map((_, i) => (i < length - 1 ? null : values.slice(i - length + 1, i + 1).reduce((a, b) => a + b, 0) / length));
}

function smooth(values: (number | null)[], length: number, alpha: number): (number | null)[] {
  const out: (number | null)[] = values.map(() => null);
  const start = values.findIndex((v) => v !== null);
  if (start < 0 || values.length < start + length) return out;
  let prev = (values.slice(start, start + length) as number[]).reduce((a, b) => a + b, 0) / length;
  out[start + length - 1] = prev;
  for (let i = start + length; i < values.length; i++) {
    prev = alpha * (values[i] as number) + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

function ema(values: number[], length: number): (number | null)[] {
  return smooth(values, length, 2 / (length + 1));
}

function rsi(closes: number[], length: number): (number | null)[] {
  const gains: (number | null)[] = [null];
  const losses: (number | null)[] = [null];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0));
    losses.push(Math.max(-d, 0));
  }
  const g = smooth(gains, length, 1 / length);
  const l = smooth(losses, length, 1 / length);
  return g.map((gain, i) => {
    const loss = l[i];
    if (gain === null || loss === null) return null;
    return loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  });
}

/** Preview only: EMA cross trades with stop 1.5 x average range and a fixed reward ratio. */
function mockTrades(candles: Candle[], fastLen: number, slowLen: number, reward: number): Trade[] {
  const closes = candles.map((c) => c.close);
  const fast = ema(closes, fastLen);
  const slow = ema(closes, slowLen);
  const trades: Trade[] = [];
  let open: Trade | null = null;
  for (let i = 1; i < candles.length; i++) {
    const c = candles[i];
    if (open) {
      const long = open.side === "long";
      const stop = long ? c.low <= open.stopLoss : c.high >= open.stopLoss;
      const target = long ? c.high >= open.takeProfit : c.low <= open.takeProfit;
      if (stop || target) {
        const exit = stop ? open.stopLoss : open.takeProfit;
        const move = (exit - open.entryPrice) * (long ? 1 : -1);
        open = { ...open, exitTime: c.time, exitPrice: exit, result: stop ? "loss" : "win", exitReason: stop ? "stop" : "target",
          pnlPercent: (move / open.entryPrice) * 100, grossPercent: (move / open.entryPrice) * 100, feePercent: 0, r: move / Math.abs(open.entryPrice - open.stopLoss) };
        trades.push(open);
        open = null;
      }
      continue;
    }
    const a = fast[i - 1], b = slow[i - 1], x = fast[i], y = slow[i];
    if (a === null || b === null || x === null || y === null || i + 1 >= candles.length) continue;
    const up = a <= b && x > y;
    const down = a >= b && x < y;
    if (!up && !down) continue;
    const range = candles.slice(Math.max(0, i - 14), i + 1).reduce((s, k) => s + k.high - k.low, 0) / 15;
    const entry = candles[i + 1].open;
    const risk = range * 1.5;
    const side = up ? "long" : "short";
    const dir = up ? 1 : -1;
    open = { side, signalTime: c.time, entryTime: candles[i + 1].time, entryPrice: entry,
      stopLoss: entry - dir * risk, takeProfit: entry + dir * risk * reward,
      exitTime: null, exitPrice: null, exitReason: null, breakevenTime: null, result: "open", pnlPercent: null, grossPercent: null, feePercent: null, r: null };
    // The entry candle (i + 1) is checked for stop and target on the next pass.
  }
  if (open) trades.push(open);
  return trades;
}
