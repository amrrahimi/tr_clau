// A pretend backend with made-up prices, for the preview and for working on
// the screen without the Python backend. Prices are random walks, NOT real data.

import type { AnalysisRequest, Backend, CandleRequest, LiveConnection, LiveHandlers } from "./api.ts";
import { DEFAULT_SETTINGS } from "./indicatorSettings.ts";
import type { Analysis, Candle, IndicatorSettings, LinePoint, MarketInfo, MarketState, MarketType, Options } from "./types.ts";

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

  /**
   * Simplified analysis for the preview only. The real numbers come from the
   * Python backend (backend/app/analysis.py); this just draws plausible lines.
   */
  async getAnalysis(request: AnalysisRequest): Promise<Analysis> {
    const step = TIMEFRAME_SECONDS[request.timeframe];
    const closed = this.history(request).filter((c) => c.time + step <= this.now());
    const closes = closed.map((c) => c.close);
    const [fastLen, slowLen] = request.tradingMode === "scalping" ? [9, 21] : [20, 50];
    const slow = ema(closes, slowLen);
    const last = closes.length - 1;
    const slope = (slow[last] ?? 0) - (slow[Math.max(0, last - 10)] ?? 0);
    const trendStrength = Math.abs(slope) / ((slow[last] ?? 1) * 0.002);
    const state: MarketState = trendStrength > 1 ? (slope > 0 ? "trend_up" : "trend_down") : "range";
    const auto: IndicatorSettings = {
      ...DEFAULT_SETTINGS,
      ema_fast: fastLen,
      ema_slow: slowLen,
      bb_on: state === "range",
      ema_fast_on: state !== "range",
    };
    const s = request.settings ?? auto;
    const shown = closed.slice(-500);
    const cut = closed.length - shown.length;
    const line = (values: (number | null)[]): LinePoint[] =>
      shown.flatMap((c, i) => (values[cut + i] === null ? [] : [{ time: c.time, value: values[cut + i] as number }]));
    const lines: Analysis["lines"] = {};
    if (s.ema_fast_on) lines.emaFast = line(ema(closes, s.ema_fast));
    if (s.ema_slow_on) lines.emaSlow = line(ema(closes, s.ema_slow));
    if (s.bb_on) {
      const mid = sma(closes, s.bb_period);
      const dev = closes.map((_, i) => {
        if (i < s.bb_period - 1) return null;
        const w = closes.slice(i - s.bb_period + 1, i + 1);
        const m = w.reduce((a, b) => a + b, 0) / w.length;
        return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / w.length);
      });
      lines.bbMiddle = line(mid);
      lines.bbUpper = line(mid.map((m, i) => (m === null || dev[i] === null ? null : m + s.bb_mult * (dev[i] as number))));
      lines.bbLower = line(mid.map((m, i) => (m === null || dev[i] === null ? null : m - s.bb_mult * (dev[i] as number))));
    }
    if (s.rsi_on) lines.rsi = line(rsi(closes, s.rsi_period));
    const ranges = closed.slice(-s.atr_period).map((c) => c.high - c.low);
    return {
      auto: !request.settings,
      tradingMode: request.tradingMode,
      settings: s,
      state: {
        current: state,
        since: closed[Math.max(0, last - 37)]?.time ?? null,
        adx: Math.min(60, 12 + trendStrength * 14),
        atrRatio: 1,
      },
      atr: ranges.reduce((a, b) => a + b, 0) / Math.max(1, ranges.length),
      lastClosedTime: closed[last]?.time ?? null,
      lines,
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
