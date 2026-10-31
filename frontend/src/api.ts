// Everything the screen needs from the backend, behind one interface.
// The real app uses HttpBackend; the preview uses a fake one with sample data.

import type {
  Analysis, Candle, CatalogSpec, ConnectionState, IndicatorInstance, MarketInfo, MarketType, Mode, Options, PaperState, ScanResult, StrategyCard,
  StrategyOverview,
} from "./types.ts";

export interface AnalysisRequest {
  marketType: MarketType;
  symbol: string;
  timeframe: string;
  tradingMode: Mode;
  indicators: IndicatorInstance[] | null; // null = let the bot choose (automatic)
}

export interface StrategyRequest {
  marketType: MarketType;
  symbol: string;
  timeframe: string;
  tradingMode: Mode;
  settings: Record<string, Record<string, number>>; // only the settings the user changed
  active: string | null; // strategy whose trades are drawn (manual)
  autoRule: "cautious" | "max_profit" | null; // set = the bot picks the strategy
  fees: { maker: number; taker: number } | null; // percent; null = the backend's defaults
}

/** The scanner works on the whole coin list, so no symbol and no active strategy. */
export type ScanRequest = Omit<StrategyRequest, "symbol" | "active" | "autoRule">;

export type PaperAction =
  | { kind: "start" }
  | { kind: "stop" }
  | { kind: "reset"; capital: number }
  | { kind: "mode"; mode: "auto" | "manual"; strategies: string[] }
  | { kind: "close"; position_id: number }
  | { kind: "close-all" }
  | { kind: "cap"; usd: number }
  | { kind: "timeframes"; timeframes: string[] }
  | { kind: "advice"; position_id: number; answer: "hold" | "close" };

/** main: the careful bot. fast: the owner's high-risk test account (its own virtual money). */
export type BotAccount = "main" | "fast";
const ACCOUNT_PATH: Record<BotAccount, string> = { main: "/api/paper", fast: "/api/fast" };

export interface CandleRequest {
  marketType: MarketType;
  symbol: string;
  timeframe: string;
  before?: number; // seconds; ask for candles older than this time
}

export interface LiveHandlers {
  onCandle(candle: Candle): void;
  onError(message: string): void; // live updates stopped
}

export interface LiveConnection {
  close(): void;
}

export interface Backend {
  getOptions(): Promise<Options>;
  getMarkets(marketType: MarketType, query?: string): Promise<MarketInfo[]>;
  getCandles(request: CandleRequest): Promise<Candle[]>;
  getAnalysis(request: AnalysisRequest): Promise<Analysis>;
  getCatalog(): Promise<CatalogSpec[]>;
  getStrategyCatalog(): Promise<StrategyCard[]>;
  getStrategyOverview(request: StrategyRequest): Promise<StrategyOverview>;
  getScan(request: ScanRequest): Promise<ScanResult>;
  getPaper(account?: BotAccount): Promise<PaperState>;
  /** Bot buttons: start, stop, reset (with capital), mode (auto/manual with strategies). */
  paperAction(action: PaperAction, account?: BotAccount): Promise<PaperState>;
  getConnection(): Promise<ConnectionState>;
  setConnection(proxy: string): Promise<ConnectionState>;
  openLive(request: CandleRequest, handlers: LiveHandlers): LiveConnection;
}

/** Error carrying the backend's message, so the screen can show it. */
export class BackendError extends Error {
  constructor(message: string, readonly unreachable = false) {
    super(message);
  }
}

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";

export class HttpBackend implements Backend {
  constructor(private readonly baseUrl: string = DEFAULT_BACKEND_URL) {}

  private async getJson<T>(path: string, params: Record<string, string | number | undefined>): Promise<T> {
    const url = new URL(path, this.baseUrl);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
    let response: Response;
    try {
      response = await fetch(url);
    } catch {
      // fetch only throws when there is no answer at all: the backend is not running.
      throw new BackendError("Backend is not reachable", true);
    }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new BackendError(typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`);
    }
    return body as T;
  }

  async getOptions(): Promise<Options> {
    return this.getJson<Options>("/api/options", {});
  }

  async getMarkets(marketType: MarketType, query = ""): Promise<MarketInfo[]> {
    const body = await this.getJson<{ markets: MarketInfo[] }>("/api/markets", { market_type: marketType, query });
    return body.markets;
  }

  async getCandles(request: CandleRequest): Promise<Candle[]> {
    const body = await this.getJson<{ candles: Candle[] }>("/api/candles", {
      market_type: request.marketType,
      symbol: request.symbol,
      timeframe: request.timeframe,
      before: request.before,
    });
    return body.candles;
  }

  async getAnalysis(request: AnalysisRequest): Promise<Analysis> {
    const body = await this.getJson<Analysis>("/api/analysis", {
      market_type: request.marketType,
      symbol: request.symbol,
      timeframe: request.timeframe,
      trading_mode: request.tradingMode,
      ...analysisParams(request.indicators),
    });
    return body;
  }

  async getCatalog(): Promise<CatalogSpec[]> {
    const body = await this.getJson<{ indicators: CatalogSpec[] }>("/api/indicators/catalog", {});
    return body.indicators;
  }

  async getStrategyCatalog(): Promise<StrategyCard[]> {
    const body = await this.getJson<{ strategies: StrategyCard[] }>("/api/strategies/catalog", {});
    return body.strategies;
  }

  async getStrategyOverview(request: StrategyRequest): Promise<StrategyOverview> {
    return this.getJson<StrategyOverview>("/api/strategies/overview", {
      market_type: request.marketType,
      symbol: request.symbol,
      timeframe: request.timeframe,
      trading_mode: request.tradingMode,
      settings: JSON.stringify(request.settings),
      active: request.active ?? "",
      auto_rule: request.autoRule ?? "",
      maker_fee: request.fees?.maker,
      taker_fee: request.fees?.taker,
    });
  }

  async getPaper(account: BotAccount = "main"): Promise<PaperState> {
    return this.getJson<PaperState>(ACCOUNT_PATH[account], {});
  }

  async getConnection(): Promise<ConnectionState> {
    return this.getJson<ConnectionState>("/api/connection", {});
  }

  async setConnection(proxy: string): Promise<ConnectionState> {
    return this.post<ConnectionState>("/api/connection", { proxy });
  }

  async paperAction(action: PaperAction, account: BotAccount = "main"): Promise<PaperState> {
    const { kind, ...body } = action;
    return this.post<PaperState>(`${ACCOUNT_PATH[account]}/${kind}`, body);
  }

  private async post<T>(path: string, body: object): Promise<T> {
    let response: Response;
    try {
      response = await fetch(new URL(path, this.baseUrl), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new BackendError("Backend is not reachable", true);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new BackendError(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
    return data as T;
  }

  async getScan(request: ScanRequest): Promise<ScanResult> {
    return this.getJson<ScanResult>("/api/scanner", {
      market_type: request.marketType,
      timeframe: request.timeframe,
      trading_mode: request.tradingMode,
      settings: JSON.stringify(request.settings),
      maker_fee: request.fees?.maker,
      taker_fee: request.fees?.taker,
    });
  }

  openLive(request: CandleRequest, handlers: LiveHandlers): LiveConnection {
    const url = new URL("/ws/candles", this.baseUrl.replace(/^http/, "ws"));
    url.searchParams.set("market_type", request.marketType);
    url.searchParams.set("symbol", request.symbol);
    url.searchParams.set("timeframe", request.timeframe);

    const socket = new WebSocket(url);
    let closedByUs = false;
    let reportedError = false;

    socket.onmessage = (event) => {
      const message = parseLiveMessage(String(event.data));
      if (message.type === "candle") handlers.onCandle(message.candle);
      else if (message.type === "error") {
        reportedError = true;
        handlers.onError(message.message);
      }
    };
    socket.onclose = () => {
      if (!closedByUs && !reportedError) handlers.onError("Live connection closed");
    };

    return {
      close() {
        closedByUs = true;
        socket.close();
      },
    };
  }
}

/**
 * Wait until the backend answers. The desktop app starts the backend at the
 * same moment as the window, and the backend needs a few seconds to start.
 * Returns true when it answered, false after `timeoutMs`.
 */
export async function waitForBackend(
  baseUrl: string = DEFAULT_BACKEND_URL,
  timeoutMs = 30_000,
  intervalMs = 500,
  fetchFn: typeof fetch = fetch,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetchFn(new URL("/api/health", baseUrl));
      if (response.ok) return true;
    } catch {
      // not running yet
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

/** Query parameters for /api/analysis. `null` = automatic (the bot chooses). */
export function analysisParams(list: IndicatorInstance[] | null): Record<string, string> {
  if (!list) return { auto: "true" };
  return { auto: "false", indicators: JSON.stringify(list.map(({ id, type, params }) => ({ id, type, params }))) };
}

export type LiveMessage =
  | { type: "candle"; candle: Candle }
  | { type: "error"; message: string }
  | { type: "unknown" };

/** Read one WebSocket message from the backend. Anything unexpected is ignored. */
export function parseLiveMessage(text: string): LiveMessage {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { type: "unknown" };
  }
  if (typeof data !== "object" || data === null) return { type: "unknown" };
  const record = data as Record<string, unknown>;
  if (record.type === "candle" && isCandle(record.candle)) return { type: "candle", candle: record.candle };
  if (record.type === "error" && typeof record.message === "string") return { type: "error", message: record.message };
  return { type: "unknown" };
}

function isCandle(value: unknown): value is Candle {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return ["time", "open", "high", "low", "close", "volume"].every((key) => typeof c[key] === "number");
}
