// The screen: choices at the top, coin list on the side, chart in the middle,
// indicator controls in the chart's corner. It only asks the backend and shows
// answers; all calculations happen in the backend.

import { BackendError, type Backend, type LiveConnection } from "./api.ts";
import { applyLiveCandle, prependOlder } from "./candles.ts";
import { ChartView, LINE_COLORS } from "./chart.ts";
import { displaySymbol, formatClock, formatPrice, formatSince, formatVolume } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import {
  DEFAULT_SETTINGS, MULT_MAX, MULT_MIN, PERIOD_MAX, PERIOD_MIN,
  clearManual, invalidFields, legendItems, loadManual, saveManual, type LegendItem,
} from "./indicatorSettings.ts";
import type { MessageKey } from "./locales/en.ts";
import { ZONES, formatOffset, loadZone, offsetMinutes, saveZone, type ZoneId } from "./timezone.ts";
import type { Analysis, Candle, IndicatorSettings, MarketInfo, MarketType, Mode, Options } from "./types.ts";

type LiveStatus = "connecting" | "live" | "stopped";

const DEFAULT_TIMEFRAME: Record<Mode, string> = { scalping: "5m", daily: "1h" };
const SEARCH_DELAY_MS = 300;
/** Wait after a candle closes before asking for indicators, so the exchange has the final price. */
const ANALYSIS_DELAY_MS = 2000;

const LEGEND_COLORS: Record<LegendItem["id"], string> = {
  emaFast: LINE_COLORS.emaFast,
  emaSlow: LINE_COLORS.emaSlow,
  bb: LINE_COLORS.bbMiddle,
  rsi: LINE_COLORS.rsi,
};

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
  // Indicators. `manual` null means Auto: the bot picks the settings.
  private manual: IndicatorSettings | null = loadManual();
  private analysis: Analysis | null = null;
  private analysisId = 0;
  private analysisTimer: ReturnType<typeof setTimeout> | undefined;
  private zone: ZoneId = loadZone();

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
    this.chart.setIndicators(null);
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
    this.analysisTimer = setTimeout(() => void this.loadAnalysis(), ANALYSIS_DELAY_MS);
  }

  /** Ask the backend for market state and indicator lines with the current settings. */
  private async loadAnalysis(): Promise<void> {
    if (!this.symbol) return;
    const chartId = this.requestId;
    const id = ++this.analysisId;
    try {
      const analysis = await this.backend.getAnalysis({
        marketType: this.marketType,
        symbol: this.symbol,
        timeframe: this.timeframe,
        tradingMode: this.mode,
        settings: this.manual,
      });
      // Ignore answers for an older chart or older settings.
      if (id !== this.analysisId || chartId !== this.requestId) return;
      this.analysis = analysis;
      this.chart.setIndicators(analysis);
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

  // ---------- Auto / Manual ----------

  private setAuto(): void {
    this.closePopup();
    if (!this.manual) return;
    this.manual = null;
    clearManual();
    this.renderSettingsMode();
    void this.loadAnalysis();
  }

  /** Open the settings window, filled with the manual settings or, the first time, what the bot is using now. */
  private openPopup(): void {
    const start = this.manual ?? this.analysis?.settings ?? DEFAULT_SETTINGS;
    const form = this.els.popup as HTMLFormElement;
    form.dir = direction(this.language);
    const check = (field: keyof IndicatorSettings, label: MessageKey) =>
      `<label class="check"><input type="checkbox" id="set-${field}" ${start[field] ? "checked" : ""} /> ${this.t(label)}</label>`;
    const number = (field: keyof IndicatorSettings, label: MessageKey, step = 1) =>
      `<label class="num">${this.t(label)} <input type="number" id="set-${field}" dir="ltr" step="${step}" value="${start[field]}" /></label>`;
    form.innerHTML = `
      <div class="popup-title">${this.t("settings.title")}</div>
      <div class="popup-row">${check("ema_fast_on", "settings.emaFast")}${number("ema_fast", "settings.length")}</div>
      <div class="popup-row">${check("ema_slow_on", "settings.emaSlow")}${number("ema_slow", "settings.length")}</div>
      <div class="popup-row">${check("bb_on", "settings.bb")}${number("bb_period", "settings.length")}${number("bb_mult", "settings.mult", 0.1)}</div>
      <div class="popup-row">${check("rsi_on", "settings.rsi")}${number("rsi_period", "settings.length")}</div>
      <div class="popup-row"><span class="check">${this.t("settings.atr")}</span>${number("atr_period", "settings.length")}</div>
      <div class="popup-error" hidden></div>
      <div class="popup-actions">
        <button type="submit" class="primary">${this.t("settings.apply")}</button>
        <button type="button" data-action="cancel">${this.t("settings.cancel")}</button>
      </div>`;
    form.querySelector("[data-action=cancel]")!.addEventListener("click", () => this.closePopup());
    form.hidden = false;
    (form.querySelector("input[type=number]") as HTMLInputElement | null)?.focus();
  }

  private readPopup(): IndicatorSettings {
    const form = this.els.popup;
    const checked = (f: string) => (form.querySelector(`#set-${f}`) as HTMLInputElement).checked;
    const value = (f: string) => Number((form.querySelector(`#set-${f}`) as HTMLInputElement).value);
    return {
      ema_fast_on: checked("ema_fast_on"), ema_fast: value("ema_fast"),
      ema_slow_on: checked("ema_slow_on"), ema_slow: value("ema_slow"),
      bb_on: checked("bb_on"), bb_period: value("bb_period"), bb_mult: value("bb_mult"),
      rsi_on: checked("rsi_on"), rsi_period: value("rsi_period"),
      atr_period: value("atr_period"),
    };
  }

  private applyPopup(): void {
    const settings = this.readPopup();
    const bad = invalidFields(settings);
    const errorBox = this.els.popup.querySelector(".popup-error") as HTMLElement;
    this.els.popup.querySelectorAll("input").forEach((input) => input.classList.toggle("invalid", bad.includes(input.id.slice(4))));
    if (bad.length) {
      errorBox.textContent = this.t("settings.invalid", {
        pmin: String(PERIOD_MIN), pmax: String(PERIOD_MAX), mmin: String(MULT_MIN), mmax: String(MULT_MAX),
      });
      errorBox.hidden = false;
      return;
    }
    this.manual = settings;
    saveManual(settings);
    this.closePopup();
    this.renderSettingsMode();
    void this.loadAnalysis();
  }

  private closePopup(): void {
    this.els.popup.hidden = true;
    this.els.popup.replaceChildren();
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
          <button class="icon-button" data-el="watchlistToggle"></button>
          <button class="lang-button" data-el="language"></button>
        </header>
        <div class="error-banner" data-el="error" hidden>
          <span data-el="errorText"></span>
          <button data-el="retry"></button>
        </div>
        <main class="body">
          <aside class="watchlist" data-el="watchlist">
            <input class="search" data-el="search" type="search" autocomplete="off" />
            <div class="watchlist-title" data-el="watchlistTitle"></div>
            <ul class="coin-list" data-el="coinList"></ul>
          </aside>
          <section class="chart-area" dir="ltr">
            <div class="chart" data-el="chart"></div>
            <div class="chart-corner">
              <div class="corner-controls">
                <div class="segmented small" data-el="settingsMode"></div>
                <button type="button" class="icon-button small" data-el="gear">⚙</button>
              </div>
              <div class="legend" data-el="legend"></div>
            </div>
            <form class="settings-popup" data-el="popup" hidden></form>
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
    this.els.search.addEventListener("input", (e) => this.onSearchInput((e.target as HTMLInputElement).value));
    this.chart.setTimeZone(this.zone);
    this.els.tzButton.addEventListener("click", () => this.toggleZoneMenu());
    document.addEventListener("click", (event) => {
      if (!(event.target as HTMLElement).closest(".tz-picker")) this.els.tzMenu.hidden = true;
    });
    setInterval(() => this.renderClock(), 1000);
    this.els.gear.addEventListener("click", () => this.openPopup());
    this.els.popup.addEventListener("submit", (event) => {
      event.preventDefault();
      this.applyPopup();
    });
    this.els.popup.addEventListener("keydown", (event) => {
      if ((event as KeyboardEvent).key === "Escape") this.closePopup();
    });
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
    this.closePopup();
    this.els.tzMenu.hidden = true;
    this.renderClock();
    this.renderControls();
    this.renderSettingsMode();
    this.renderAnalysis();
    this.renderWatchlist();
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

  private renderSettingsMode(): void {
    this.renderSegmented(this.els.settingsMode, [
      { label: this.t("settings.auto"), active: !this.manual, onClick: () => this.setAuto() },
      { label: this.t("settings.manual"), active: !!this.manual, onClick: () => this.openPopup() },
    ]);
    (this.els.settingsMode.firstElementChild as HTMLElement).title = this.t("settings.autoHint");
    this.els.gear.hidden = !this.manual;
    this.els.gear.title = this.t("settings.edit");
  }

  /** Market state label, ATR and the legend in the chart's corner. */
  private renderAnalysis(): void {
    const a = this.analysis;
    if (!a) {
      this.els.marketState.textContent = "";
      this.els.marketState.className = "market-state";
      this.els.atr.textContent = "";
      this.els.legend.replaceChildren();
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
    this.els.atr.textContent = a.atr === null ? "" : `ATR ${a.settings.atr_period}: ${formatPrice(a.atr, this.chart.pricePrecision)}`;

    this.els.legend.replaceChildren(...legendItems(a).map((item) => {
      const row = document.createElement("div");
      row.className = "legend-row";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = LEGEND_COLORS[item.id];
      const name = document.createElement("span");
      name.className = "legend-label";
      name.textContent = item.label;
      const values = document.createElement("span");
      values.className = "legend-value";
      const precision = item.id === "rsi" ? 2 : this.chart.pricePrecision;
      values.textContent = item.values.map((v) => formatPrice(v, precision)).join("  ");
      row.append(dot, name, values);
      return row;
    }));
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
