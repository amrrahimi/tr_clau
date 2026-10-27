// The screen: choices at the top, coin list and strategies table on the side,
// chart in the middle, indicator controls in the chart's corner. It only asks the backend and shows
// answers; all calculations happen in the backend.

import { BackendError, type Backend, type LiveConnection } from "./api.ts";
import { applyLiveCandle, prependOlder } from "./candles.ts";
import { ChartView } from "./chart.ts";
import { displaySymbol, formatClock, formatPrice, formatSince, formatVolume } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import { IndicatorController } from "./indicatorController.ts";
import type { BotMode } from "./indicatorList.ts";
import type { MessageKey } from "./locales/en.ts";
import { effectiveFees, loadFees, saveFees, setFees, type FeeOverrides } from "./fees.ts";
import { StrategyPanel } from "./strategyPanel.ts";
import { ZONES, formatOffset, loadZone, offsetMinutes, saveZone, type ZoneId } from "./timezone.ts";
import type { Analysis, Candle, MarketInfo, MarketType, Mode, Options } from "./types.ts";

type LiveStatus = "connecting" | "live" | "stopped";

const DEFAULT_TIMEFRAME: Record<Mode, string> = { scalping: "5m", daily: "1h" };
const SEARCH_DELAY_MS = 300;
/** Wait after a candle closes before asking for indicators, so the exchange has the final price. */
const ANALYSIS_DELAY_MS = 2000;

export class App {
  private language: Language = loadLanguage();
  private options: Options | null = null;
  private marketType: MarketType = "spot";
  private mode: Mode = "scalping";
  private timeframe = DEFAULT_TIMEFRAME.scalping;
  private symbol: string | null = null;
  private markets: MarketInfo[] = [];
  private searchQuery = "";
  private candles: Candle[] = [];
  private liveStatus: LiveStatus = "stopped";
  private live: LiveConnection | null = null;
  private loadingOlder = false;
  private noMoreHistory = false;
  private errorKey: { key: MessageKey; detail?: string } | null = null;
  private chartMessage: MessageKey | null = null;
  private watchlistOpen = true;
  // Every new chart request gets a number; answers to older requests are ignored.
  // Without this, quickly clicking BTC then ETH could show BTC's candles under ETH's name.
  private requestId = 0;
  private searchTimer: ReturnType<typeof setTimeout> | undefined;
  // Indicators: the controller owns Auto/Manual/Start and the user's list.
  private indicators!: IndicatorController;
  private analysis: Analysis | null = null;
  private analysisId = 0;
  private analysisTimer: ReturnType<typeof setTimeout> | undefined;
  private zone: ZoneId = loadZone();
  // Strategies: the table under the coin list and the trades of the active one.
  private strategies!: StrategyPanel;
  private strategyId = 0;
  private fees: FeeOverrides = loadFees(); // the user's own fee rates, per market type

  private readonly root: HTMLElement;
  private chart!: ChartView;
  private els!: Record<string, HTMLElement>;

  constructor(root: HTMLElement, private readonly backend: Backend) {
    this.root = root;
  }

  async start(): Promise<void> {
    this.buildLayout();
    this.applyLanguage();
    await this.loadOptions();
  }

  private async loadOptions(): Promise<void> {
    try {
      this.options = await this.backend.getOptions();
      this.indicators.setCatalog(await this.backend.getCatalog());
      this.strategies.setCatalog(await this.backend.getStrategyCatalog());
      this.renderControls();
      await this.loadMarkets();
    } catch (error) {
      this.showError(error);
    }
  }

  // ---------- user actions ----------

  async setMarketType(marketType: MarketType): Promise<void> {
    if (marketType === this.marketType) return;
    this.marketType = marketType;
    this.symbol = null;
    this.renderControls();
    await this.loadMarkets();
  }

  async setMode(mode: Mode): Promise<void> {
    if (mode === this.mode) return;
    this.mode = mode;
    const choices = this.options?.timeframes[mode] ?? [];
    this.timeframe = choices.includes(DEFAULT_TIMEFRAME[mode]) ? DEFAULT_TIMEFRAME[mode] : choices[0];
    this.renderControls();
    await this.openChart();
  }

  async setTimeframe(timeframe: string): Promise<void> {
    if (timeframe === this.timeframe) return;
    this.timeframe = timeframe;
    this.renderControls();
    await this.openChart();
  }

  async selectSymbol(symbol: string): Promise<void> {
    if (symbol === this.symbol) return;
    this.symbol = symbol;
    this.renderWatchlist();
    await this.openChart();
  }

  setLanguage(language: Language): void {
    this.language = language;
    saveLanguage(language);
    this.applyLanguage();
  }

  // ---------- loading data ----------

  private async loadMarkets(): Promise<void> {
    const requestedType = this.marketType;
    try {
      const markets = await this.backend.getMarkets(requestedType, this.searchQuery);
      if (requestedType !== this.marketType) return; // user switched market meanwhile
      this.markets = markets;
      this.renderWatchlist();
      if (!this.symbol && markets.length) await this.selectSymbol(markets[0].symbol);
    } catch (error) {
      this.showError(error);
    }
  }

  private async openChart(): Promise<void> {
    if (!this.symbol) return;
    const id = ++this.requestId;
    this.stopLive();
    this.candles = [];
    this.analysis = null;
    this.indicators.clearResults();
    this.chart.setTrades([], null);
    this.strategies.showOverview(null);
    this.renderAnalysis();
    this.noMoreHistory = false;
    this.loadingOlder = false;
    this.clearError();
    this.setChartMessage("chart.loading");
    this.renderHeader();

    const request = { marketType: this.marketType, symbol: this.symbol, timeframe: this.timeframe };
    try {
      const candles = await this.backend.getCandles(request);
      if (id !== this.requestId) return;
      this.candles = candles;
      this.chart.setCandles(candles);
      this.setChartMessage(null);
      this.renderHeader();
      this.startLive(id);
      void this.loadAnalysis();
      void this.loadStrategies();
    } catch (error) {
      if (id !== this.requestId) return;
      this.setChartMessage(null);
      this.showError(error);
    }
  }

  private startLive(id: number): void {
    if (!this.symbol) return;
    this.setLiveStatus("connecting");
    this.live = this.backend.openLive(
      { marketType: this.marketType, symbol: this.symbol, timeframe: this.timeframe },
      {
        onCandle: (candle) => {
          if (id !== this.requestId) return;
          if (this.liveStatus !== "live") this.setLiveStatus("live");
          const action = applyLiveCandle(this.candles, candle);
          if (action !== "ignore") this.chart.updateCandle(candle);
          // A new candle started, so the previous one just closed: refresh indicators.
          if (action === "append") this.scheduleAnalysis();
          this.renderPrice();
        },
        onError: (message) => {
          if (id !== this.requestId) return;
          this.live = null;
          this.setLiveStatus("stopped");
          this.errorKey = { key: "error.liveStopped", detail: message };
          this.renderError();
        },
      },
    );
  }

  private scheduleAnalysis(): void {
    clearTimeout(this.analysisTimer);
    this.analysisTimer = setTimeout(() => {
      void this.loadAnalysis();
      void this.loadStrategies();
    }, ANALYSIS_DELAY_MS);
  }

  /** Ask the backend for market state and indicator lines with the current settings. */
  private async loadAnalysis(): Promise<void> {
    if (!this.symbol) return;
    const wanted = this.indicators.request();
    const id = ++this.analysisId;
    const chartId = this.requestId;
    try {
      const analysis = await this.backend.getAnalysis({
        marketType: this.marketType,
        symbol: this.symbol,
        timeframe: this.timeframe,
        tradingMode: this.mode,
        indicators: wanted,
      });
      // Ignore answers for an older chart or older settings.
      if (id !== this.analysisId || chartId !== this.requestId) return;
      this.analysis = analysis;
      this.indicators.showResults(analysis.indicators);
      this.renderAnalysis();
    } catch (error) {
      if (id !== this.analysisId) return;
      if (error instanceof BackendError && error.unreachable) this.showError(error);
      else {
        this.errorKey = { key: "error.analysis", detail: error instanceof Error ? error.message : String(error) };
        this.renderError();
      }
    }
  }

  /** Results of every strategy on this chart, and the trades of the active one. */
  private async loadStrategies(): Promise<void> {
    if (!this.symbol) return;
    const id = ++this.strategyId;
    const chartId = this.requestId;
    this.strategies.setLoading();
    try {
      const overview = await this.backend.getStrategyOverview({
        marketType: this.marketType,
        symbol: this.symbol,
        timeframe: this.timeframe,
        tradingMode: this.mode,
        settings: this.strategies.settings,
        active: this.strategies.active,
        autoRule: this.strategies.autoRule,
        fees: effectiveFees(this.options?.fees, this.fees, this.marketType),
      });
      // Ignore answers for an older chart or older choices.
      if (id !== this.strategyId || chartId !== this.requestId) return;
      this.strategies.showOverview(overview);
      this.chart.setTrades(overview.active?.trades ?? [], overview.lastClosedTime);
    } catch (error) {
      if (id !== this.strategyId) return;
      this.strategies.setError();
      if (error instanceof BackendError && error.unreachable) this.showError(error);
    }
  }

  /** Called by the indicator controller when Auto/Manual/Start changes the mode. */
  private onBotModeChange(mode: BotMode): void {
    if (mode === "manual-stopped") {
      // The bot stops; the top bar says so. Lines stay as a preview.
      this.renderAnalysis();
    }
    void this.loadAnalysis(); // a new request also drops answers still on their way
  }

  private stopLive(): void {
    this.live?.close();
    this.live = null;
    this.setLiveStatus("stopped");
  }

  /** Called by the chart when the user scrolls near the oldest loaded candle. */
  private async loadOlder(): Promise<void> {
    if (this.loadingOlder || this.noMoreHistory || !this.symbol || !this.candles.length) return;
    const id = this.requestId;
    this.loadingOlder = true;
    this.setChartMessage("chart.loadingOlder");
    try {
      const older = await this.backend.getCandles({
        marketType: this.marketType,
        symbol: this.symbol,
        timeframe: this.timeframe,
        before: this.candles[0].time,
      });
      if (id !== this.requestId) return;
      const { candles, added } = prependOlder(older, this.candles);
      if (added === 0) {
        this.noMoreHistory = true;
        this.setChartMessage("chart.noMoreHistory");
        setTimeout(() => this.chartMessage === "chart.noMoreHistory" && this.setChartMessage(null), 2000);
        return;
      }
      this.candles = candles;
      this.chart.prependCandles(candles, added);
      this.setChartMessage(null);
    } catch (error) {
      if (id === this.requestId) {
        this.setChartMessage(null);
        this.showError(error);
      }
    } finally {
      if (id === this.requestId) this.loadingOlder = false;
    }
  }

  private onSearchInput(value: string): void {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.searchQuery = value.trim();
      void this.loadMarkets();
    }, SEARCH_DELAY_MS);
  }

  /** The ⟳ button and the error banner's retry: load everything for this chart again. */
  private retry(): void {
    this.clearError();
    if (!this.options) void this.loadOptions();
    else if (!this.markets.length) void this.loadMarkets();
    else {
      this.requestId++; // force a fresh chart even for the same coin
      void this.openChart();
    }
  }

  // ---------- screen ----------

  private t(key: MessageKey, params?: Record<string, string>): string {
    return translate(this.language, key, params);
  }

  private buildLayout(): void {
    this.root.innerHTML = `
      <div class="app">
        <header class="topbar">
          <div class="segmented" data-el="marketTypes"></div>
          <div class="symbol-info">
            <span class="symbol" data-el="symbol">—</span>
            <span class="price" data-el="price">—</span>
          </div>
          <span class="market-state" data-el="marketState"></span>
          <span class="atr-value" data-el="atr" dir="ltr"></span>
          <div class="segmented" data-el="modes"></div>
          <div class="timeframes" data-el="timeframes"></div>
          <div class="spacer"></div>
          <span class="live-status" data-el="liveStatus"></span>
          <button class="icon-button" data-el="refresh"></button>
          <button class="icon-button" data-el="watchlistToggle"></button>
          <button class="lang-button" data-el="language"></button>
        </header>
        <div class="error-banner" data-el="error" hidden>
          <span data-el="errorText"></span>
          <button data-el="retry"></button>
        </div>
        <main class="body">
          <aside class="watchlist" data-el="watchlist">
            <div class="coins">
              <input class="search" data-el="search" type="search" autocomplete="off" />
              <div class="watchlist-title" data-el="watchlistTitle"></div>
              <ul class="coin-list" data-el="coinList"></ul>
            </div>
            <section class="strategies" data-el="strategies"></section>
          </aside>
          <section class="chart-area" dir="ltr">
            <div class="chart" data-el="chart"></div>
            <div class="pane-legends" data-el="legends"></div>
            <div class="chart-corner corner-controls" data-el="corner"></div>
            <div class="modal-layer" data-el="modal" hidden></div>
            <div class="chart-footer">
              <div class="tz-picker">
                <button type="button" class="tz-button" data-el="tzButton"></button>
                <ul class="tz-menu" data-el="tzMenu" hidden></ul>
              </div>
            </div>
            <div class="chart-message" data-el="chartMessage" hidden></div>
          </section>
        </main>
      </div>`;
    this.els = {};
    this.root.querySelectorAll<HTMLElement>("[data-el]").forEach((el) => {
      this.els[el.dataset.el!] = el;
    });

    this.chart = new ChartView(this.els.chart, () => void this.loadOlder());
    this.els.language.addEventListener("click", () => this.setLanguage(this.language === "fa" ? "en" : "fa"));
    this.els.retry.addEventListener("click", () => this.retry());
    this.els.refresh.addEventListener("click", () => this.retry());
    this.els.search.addEventListener("input", (e) => this.onSearchInput((e.target as HTMLInputElement).value));
    this.chart.setTimeZone(this.zone);
    this.els.tzButton.addEventListener("click", () => this.toggleZoneMenu());
    document.addEventListener("click", (event) => {
      if (!(event.target as HTMLElement).closest(".tz-picker")) this.els.tzMenu.hidden = true;
    });
    setInterval(() => this.renderClock(), 1000);
    this.indicators = new IndicatorController(
      {
        t: (key, params) => this.t(key, params),
        dir: () => direction(this.language),
        chart: this.chart,
        onModeChange: (mode) => this.onBotModeChange(mode),
        onListChange: () => void this.loadAnalysis(),
      },
      { corner: this.els.corner, legends: this.els.legends, modal: this.els.modal },
    );
    this.strategies = new StrategyPanel(
      {
        t: (key, params) => this.t(key, params),
        mode: () => this.mode,
        openWindow: (content) => this.indicators.openModal(content),
        closeWindow: () => this.indicators.closeModal(),
        onChange: () => void this.loadStrategies(),
        fees: () => ({
          market: this.marketType,
          rates: effectiveFees(this.options?.fees, this.fees, this.marketType),
          defaults: this.options?.fees[this.marketType] ?? null,
        }),
        saveFees: (rates) => {
          this.fees = setFees(this.fees, this.marketType, rates, this.options?.fees[this.marketType]);
          saveFees(this.fees);
          void this.loadStrategies();
        },
      },
      this.els.strategies,
    );
    // Pane sizes change with the window; legends follow their panes.
    new ResizeObserver(() => this.indicators.render()).observe(this.els.chart);
    this.els.watchlistToggle.addEventListener("click", () => {
      this.watchlistOpen = !this.watchlistOpen;
      this.els.watchlist.hidden = !this.watchlistOpen;
    });
  }

  /** Re-draw every text in the current language and flip the page direction. */
  private applyLanguage(): void {
    document.documentElement.lang = this.language;
    document.documentElement.dir = direction(this.language);
    document.title = this.t("app.title");
    this.els.language.textContent = this.t("language.switch");
    this.els.language.title = this.t("language.switchLabel");
    this.els.watchlistToggle.textContent = "☰";
    this.els.watchlistToggle.title = this.t("watchlist.toggle");
    (this.els.search as HTMLInputElement).placeholder = this.t("watchlist.searchPlaceholder");
    this.els.retry.textContent = this.t("action.retry");
    this.els.refresh.textContent = "⟳";
    this.els.refresh.title = this.t("action.refresh");
    this.indicators.closeModal();
    this.indicators.render();
    this.els.tzMenu.hidden = true;
    this.renderClock();
    this.renderControls();
    this.renderAnalysis();
    this.renderWatchlist();
    this.strategies.render();
    this.renderLiveStatus();
    this.renderError();
    this.renderChartMessage();
  }

  private renderControls(): void {
    const types: MarketType[] = this.options?.marketTypes ?? ["spot", "futures"];
    this.renderSegmented(this.els.marketTypes, types.map((type) => ({
      label: this.t(type === "spot" ? "market.spot" : "market.futures"),
      active: type === this.marketType,
      onClick: () => void this.setMarketType(type),
    })));
    const modes: Mode[] = ["scalping", "daily"];
    this.renderSegmented(this.els.modes, modes.map((mode) => ({
      label: this.t(mode === "scalping" ? "mode.scalping" : "mode.daily"),
      active: mode === this.mode,
      onClick: () => void this.setMode(mode),
    })));
    const timeframes = this.options?.timeframes[this.mode] ?? [];
    this.renderSegmented(this.els.timeframes, timeframes.map((tf) => ({
      label: tf,
      active: tf === this.timeframe,
      onClick: () => void this.setTimeframe(tf),
    })));
  }

  /** Market state label and ATR in the top bar. */
  private renderAnalysis(): void {
    if (this.indicators?.mode === "manual-stopped") {
      this.els.marketState.textContent = this.t("bot.stopped");
      this.els.marketState.className = "market-state stopped";
      this.els.atr.textContent = "";
      return;
    }
    const a = this.analysis;
    if (!a) {
      this.els.marketState.textContent = "";
      this.els.marketState.className = "market-state";
      this.els.atr.textContent = "";
      return;
    }
    const state = a.state;
    let label = `${this.t("state.label")}: ${this.t(`state.${state.current}` as MessageKey)}`;
    if (state.since !== null) {
      label += ` · ${this.t("state.since", { time: formatSince(state.since, Date.now(), this.zone) })}`;
    }
    if (state.adx !== null) label += ` · ADX ${state.adx.toFixed(1)}`;
    this.els.marketState.textContent = label;
    this.els.marketState.className = `market-state ${state.current}`;
    this.els.atr.textContent = a.atr === null ? "" : `ATR ${a.atrLength}: ${formatPrice(a.atr, this.chart.pricePrecision)}`;
  }

  // ---------- time zone ----------

  private zoneLabel(zone: ZoneId): string {
    const option = ZONES.find((z) => z.id === zone);
    return option ? this.t(option.label) : zone;
  }

  /** Bottom-left clock: "14:06:32  UTC+3  Moscow". */
  private renderClock(): void {
    const now = Date.now();
    this.els.tzButton.textContent =
      `${formatClock(now, this.zone)}  ${formatOffset(offsetMinutes(now, this.zone))}  ${this.zoneLabel(this.zone)}`;
    this.els.tzButton.title = this.t("tz.title");
  }

  private toggleZoneMenu(): void {
    const menu = this.els.tzMenu;
    if (!menu.hidden) {
      menu.hidden = true;
      return;
    }
    const now = Date.now();
    menu.dir = direction(this.language);
    menu.replaceChildren(...ZONES.map((z) => {
      const item = document.createElement("li");
      item.className = z.id === this.zone ? "active" : "";
      const name = document.createElement("span");
      name.textContent = this.t(z.label);
      const offset = document.createElement("span");
      offset.className = "tz-offset";
      offset.dir = "ltr";
      offset.textContent = formatOffset(offsetMinutes(now, z.id));
      item.append(name, offset);
      item.addEventListener("click", () => this.setZone(z.id));
      return item;
    }));
    menu.hidden = false;
  }

  private setZone(zone: ZoneId): void {
    this.zone = zone;
    saveZone(zone);
    this.els.tzMenu.hidden = true;
    this.chart.setTimeZone(zone);
    this.renderClock();
    this.renderAnalysis();
  }

  private renderSegmented(container: HTMLElement, items: { label: string; active: boolean; onClick: () => void }[]): void {
    container.replaceChildren(...items.map((item) => {
      const button = document.createElement("button");
      button.textContent = item.label;
      button.className = item.active ? "active" : "";
      button.addEventListener("click", item.onClick);
      return button;
    }));
  }

  private renderWatchlist(): void {
    this.els.watchlistTitle.textContent = this.t(this.searchQuery ? "watchlist.searchResults" : "watchlist.title");
    if (!this.markets.length) {
      const empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = this.options ? this.t("watchlist.empty") : "";
      this.els.coinList.replaceChildren(empty);
      return;
    }
    this.els.coinList.replaceChildren(...this.markets.map((market) => {
      const item = document.createElement("li");
      item.className = market.symbol === this.symbol ? "active" : "";
      item.innerHTML = `<span class="coin"></span><span class="volume" dir="ltr"></span>`;
      item.querySelector(".coin")!.textContent = market.base;
      item.querySelector(".volume")!.textContent = formatVolume(market.volume24h);
      item.title = `${this.t("watchlist.volume")}: ${formatVolume(market.volume24h)} ${market.quote}`;
      item.addEventListener("click", () => void this.selectSymbol(market.symbol));
      return item;
    }));
  }

  private renderHeader(): void {
    this.els.symbol.textContent = this.symbol ? displaySymbol(this.symbol) : "—";
    this.renderPrice();
  }

  private renderPrice(): void {
    const last = this.candles[this.candles.length - 1];
    const previous = this.candles[this.candles.length - 2];
    this.els.price.textContent = formatPrice(last?.close, this.chart.pricePrecision);
    this.els.price.dir = "ltr";
    this.els.price.className = "price" + (last && previous ? (last.close >= previous.close ? " up" : " down") : "");
  }

  private setLiveStatus(status: LiveStatus): void {
    this.liveStatus = status;
    this.renderLiveStatus();
  }

  private renderLiveStatus(): void {
    const key: MessageKey = this.liveStatus === "live" ? "status.live"
      : this.liveStatus === "connecting" ? "status.connecting" : "status.stopped";
    this.els.liveStatus.textContent = this.t(key);
    this.els.liveStatus.className = `live-status ${this.liveStatus}`;
  }

  private showError(error: unknown): void {
    if (error instanceof BackendError && error.unreachable) this.errorKey = { key: "error.backendUnreachable" };
    else this.errorKey = { key: "error.generic", detail: error instanceof Error ? error.message : String(error) };
    this.renderError();
  }

  private clearError(): void {
    this.errorKey = null;
    this.renderError();
  }

  private renderError(): void {
    this.els.error.hidden = !this.errorKey;
    if (this.errorKey) this.els.errorText.textContent = this.t(this.errorKey.key, { detail: this.errorKey.detail ?? "" });
  }

  private setChartMessage(key: MessageKey | null): void {
    this.chartMessage = key;
    this.renderChartMessage();
  }

  private renderChartMessage(): void {
    this.els.chartMessage.hidden = !this.chartMessage;
    if (this.chartMessage) this.els.chartMessage.textContent = this.t(this.chartMessage);
  }
}
