// The automatic screen (owner's design): the bot does everything. A chart,
// the bot panel (start/stop, virtual money, results) and the bot's trades.
// The bot itself runs in the backend; this screen only shows it and sends
// the button presses.

import { BackendError, type Backend, type LiveConnection, type PaperAction } from "./api.ts";
import { applyLiveCandle, pricePrecision } from "./candles.ts";
import { leonWordmark } from "./brand.ts";
import { ChartView, THEME, type BoxDecor, type Level } from "./chart.ts";
import { adviceText, allStrategies, brainKnobHint, brainText, breakevenTrigger, candleStart, CHART_TFS, COMPANION_TF, EYE_GROUPS, explainLines, LINE_GROUPS, loadFolds, saveFolds, sectionOpen, type PanelSection, loadEye, loadLines, saveLines, type LineGroup, type LineLook, type LineStyleName, lockPrices, saveEye, swingLevels, type EyeGroup, formatR, lockValid, timeLeft, toggled, typingField, levelProblem, resultAt, defaultTarget, eventText, formatMoney, paperAsTrade, pauseRuleText, statusKey, strategyOrder, timeframesOf, tradeOutcome } from "./botView.ts";
import { formatClock, formatPrice } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import { loadZone } from "./timezone.ts";
import type { Candle, ConnectionState, IndicatorResult, ConsultAnswer, MarketInfo, PaperPosition, PaperState, PaperTrade, StrategyCard, StrategyResults, StrategyRow } from "./types.ts";

const POLL_MS = 5000;

export type View = "auto" | "semi";

/** The chart opens on the position: this many candles before its entry, this much room after. */
const ZOOM_BEFORE = 30;
const ZOOM_AFTER = 8;

export class BotApp {
  private language: Language = loadLanguage();
  private zone = loadZone();
  private state: PaperState | null = null;
  private cards: StrategyCard[] = [];
  private coinQuery = "";                         // the owner's search in the coin list
  private coinFound: MarketInfo[] = [];
  private coinManualOpen = false;
  private aiTest: string | null = null;   // the last "test connection" result line
  private chart!: ChartView;
  private els!: Record<string, HTMLElement>;
  private target: { symbol: string; timeframe: string; id: number | null } | null = null;
  private pinned = false; // the owner clicked a trade: keep showing it
  private candles: Candle[] = [];
  private live: LiveConnection | null = null;
  private chartId = 0;
  private confirmReset = false;
  private capitalDraft: string | null = null; // what the owner typed, kept across redraws
  private capDraft: string | null = null;
  private pauseDraft: { losses: string; fall: string } | null = null;
  private lockDraft: { trigger: string; at: string } | null = null;
  private brainDraft: number | null = null;   // percent while the knob is being moved
  private proxyDraft: string | null = null;
  private confirmCloseAll = false;
  private failures = 0; // polls in a row without an answer from the engine
  private connection: ConnectionState | null = null;
  private polls = 0;
  private actions = 0;   // counts button presses, so a poll answer from before a press is not shown
  private error: string | null = null;

  constructor(private readonly root: HTMLElement, private readonly backend: Backend,
              private readonly onSwitch: (view: View) => void) {}

  async start(): Promise<void> {
    this.build();
    this.applyLanguage();
    await this.loadCatalog();
    await this.refresh();
    void this.loadConnection();
    setInterval(() => {
      void this.refresh();
      if (++this.polls % 12 === 0) void this.loadConnection(); // about once a minute
    }, POLL_MS);
  }

  /** Under each strategy in the manual list: how the bot, its signals and the brain's picks have done. */
  private strategyStatsView(stats: StrategyResults | undefined): HTMLElement {
    const el = (tag: string, cls: string, text = "") => {
      const e = document.createElement(tag);
      e.className = cls;
      e.textContent = text;
      return e;
    };
    const box = el("div", "bot-strategy-stats");
    const pct = (v: number | null | undefined) => (v == null ? "–" : String(Math.round(v)));
    const r = (v: number | null | undefined) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`);
    const tone = (v: number | null | undefined) => (v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");
    if (!stats || (!stats.bot && !stats.signals && !stats.brain)) {
      box.append(el("div", "", this.t("bot.statNone")));
      return box;
    }
    if (stats.signals) {
      box.append(el("div", tone(stats.signals.avgR), this.t("bot.statSignals",
        { n: String(stats.signals.count), win: pct(stats.signals.winRate), r: r(stats.signals.avgR) })));
    }
    if (stats.brain) {
      box.append(el("div", tone(stats.brain.avgR), this.t("bot.statBrain",
        { n: String(stats.brain.count), win: pct(stats.brain.winRate), r: r(stats.brain.avgR) })));
    }
    if (stats.bot) {
      box.append(el("div", tone(stats.bot.netPnl), this.t("bot.statBot",
        { n: String(stats.bot.count), win: pct(stats.bot.winRate), pnl: r(stats.bot.netPnl) })));
    }
    return box;
  }

  private t(key: MessageKey, params?: Record<string, string>): string {
    return translate(this.language, key, params);
  }

  private build(): void {
    this.root.innerHTML = `
      <div class="app bot-app">
        <header class="topbar">
          <span class="app-name" data-el="title"></span>
          <div class="segmented" data-el="view"></div>
          <span class="symbol" data-el="chartTitle"></span>
          <div class="segmented small chart-tfs" data-el="tfs"></div>
          <div class="spacer"></div>
          <button class="lang-button" data-el="language"></button>
        </header>
        <div class="error-banner" data-el="error" hidden><span data-el="errorText"></span></div>
        <main class="body">
          <aside class="bot-panel" data-el="panel"></aside>
          <div class="chart-column">
            <section class="chart-area" dir="ltr">
              <div class="chart" data-el="chart"></div>
              <div class="chart-eye" data-el="eye"></div>
              <div class="chart-message" data-el="chartMessage" hidden></div>
            </section>
            <section class="bot-consult" data-el="consult" hidden></section>
            <section class="bot-trades" data-el="trades"></section>
          </div>
        </main>
      </div>`;
    this.els = {};
    this.root.querySelectorAll<HTMLElement>("[data-el]").forEach((el) => (this.els[el.dataset.el!] = el));
    this.chart = new ChartView(this.els.chart, () => undefined);
    this.chart.setTimeZone(this.zone);
    this.els.language.addEventListener("click", () => {
      this.language = this.language === "fa" ? "en" : "fa";
      saveLanguage(this.language);
      this.applyLanguage();
    });
  }

  private applyLanguage(): void {
    document.documentElement.lang = this.language;
    document.documentElement.dir = direction(this.language);
    document.title = this.t("app.title");
    this.els.title.innerHTML = leonWordmark(20);
    this.els.language.textContent = this.t("language.switch");
    this.els.language.title = this.t("language.switchLabel");
    // The semi-automatic screen is switched off (owner 2026-11-09); its code stays (app.ts) for later.
    this.els.view.hidden = true;
    void this.onSwitch;   // kept for when the semi-automatic screen comes back
    this.render();
    this.drawTrades(); // labels on the chart follow the language too
  }

  // ---------- data ----------

  private async refresh(): Promise<void> {
    const asked = this.actions;
    if (!this.cards.length) void this.loadCatalog();   // it failed at start (engine busy): try again
    try {
      const state = await this.backend.getPaper();
      // A button was pressed while this answer was on its way: it may show the state from before the
      // press (ticks "coming back"); the button's own answer is newer, so this one is dropped.
      if (asked !== this.actions) return;
      this.state = state;
      this.error = null;
      this.failures = 0;
    } catch (error) {
      if (error instanceof BackendError && error.unreachable) {
        // A busy engine can miss an answer or two: only say so after a few misses in a row.
        this.failures += 1;
        if (this.failures >= 3) this.error = this.t("error.backendBusy");
      } else {
        this.error = this.t("error.generic", { detail: error instanceof Error ? error.message : String(error) });
      }
    }
    this.followBot();
    this.drawTrades();
    this.render();
  }

  private catalogLoading = false;

  /** The strategy catalog (names for the manual list). The panel still works without it; tried again later. */
  private async loadCatalog(): Promise<void> {
    if (this.catalogLoading) return;
    this.catalogLoading = true;
    try {
      this.cards = await this.backend.getStrategyCatalog();
    } catch {
      // engine busy at start: the next poll tries again
    } finally {
      this.catalogLoading = false;
    }
  }

  private async loadConnection(): Promise<void> {
    try {
      this.connection = await this.backend.getConnection();
    } catch {
      return;
    }
    if (!this.typing()) this.renderPanel();
  }

  /** The owner is typing in a box of the panel (or moving its slider): do not redraw it under the cursor.
   * A ticked checkbox is not typing: Windows gives it the keyboard focus on a click (macOS does not), and
   * counting it as typing stopped the panel from redrawing, so later ticks undid earlier ones. */
  private typing(): boolean {
    const active = document.activeElement;
    if (!active || !this.els.panel.contains(active)) return false;
    return typingField(active.tagName, active instanceof HTMLInputElement ? active.type : "");
  }

  /** Unless the owner clicked a trade, the chart follows the bot's newest trade. */
  private followBot(): void {
    if (!this.state || this.pinned) return;
    const next = defaultTarget(this.state);
    if (!this.target || next.symbol !== this.target.symbol || next.timeframe !== this.target.timeframe) {
      void this.showChart(next);
    } else {
      this.target = next;
    }
  }

  private async act(action: PaperAction): Promise<void> {
    this.actions++;
    try {
      this.state = await this.backend.paperAction(action);
      this.actions++;   // polls that started while this was on its way are older than this answer
      this.error = null;
    } catch (error) {
      this.error = error instanceof Error ? error.message : String(error);
    }
    if (action.kind === "reset") this.pinned = false;
    this.followBot();
    this.render();
    this.drawTrades();
  }

  /** Open the chart of a coin and timeframe (a trade of the bot). */
  private async showChart(target: { symbol: string; timeframe: string; id: number | null }): Promise<void> {
    this.target = target;
    const id = ++this.chartId;
    this.live?.close();
    this.live = null;
    this.els.chartMessage.hidden = false;
    this.els.chartMessage.textContent = this.t("chart.loading");
    this.renderTitle();
    const request = { marketType: "futures" as const, symbol: target.symbol, timeframe: target.timeframe };
    try {
      const candles = await this.backend.getCandles(request);
      if (id !== this.chartId) return;
      this.candles = candles;
      this.chart.setCandles(candles);
      this.els.chartMessage.hidden = true;
      this.drawTrades();
      this.zoomToPosition();
      this.live = this.backend.openLive(request, {
        onCandle: (candle) => {
          if (id !== this.chartId) return;
          if (applyLiveCandle(this.candles, candle) !== "ignore") this.chart.updateCandle(candle);
        },
        onError: () => undefined,
      });
    } catch {
      if (id === this.chartId) this.els.chartMessage.textContent = this.t("error.generic", { detail: target.symbol });
    }
  }

  /** Arrows and boxes of the bot's trades on the coin and timeframe shown. */
  /** Owner 2026-11-09: the chart opens zoomed in on the position (its entry and what came after, with about
   * 30 candles before it and some room on the right), not on hundreds of older candles. */
  private zoomToPosition(): void {
    if (!this.target || !this.state || !this.candles.length) return;
    const open = this.state.positions.filter((p) => p.symbol === this.target!.symbol);
    const p = open.find((x) => x.id === this.target!.id) ?? open[open.length - 1]
      ?? this.state.closed.find((x) => x.id === this.target!.id && x.symbol === this.target!.symbol);
    if (!p) return;
    const at = candleStart(p.entryTime, this.target.timeframe);
    const last = this.candles.length - 1;
    let idx = this.candles.findIndex((c) => c.time >= at);
    if (idx < 0) idx = last;
    const exitTime = "exitTime" in p ? (p.exitTime as number | null) : null;
    const exit = exitTime ? this.candles.findIndex((c) => c.time >= candleStart(exitTime, this.target!.timeframe)) : -1;
    const end = exit >= 0 ? exit : last;
    this.chart.showRange(idx - ZOOM_BEFORE, end + ZOOM_AFTER);
  }

  private drawTrades(): void {
    if (!this.state || !this.target || !this.candles.length) return;
    const symbol = this.target.symbol;
    const tf = this.target.timeframe;
    const same = (p: PaperPosition) => p.symbol === symbol;   // any timeframe of this coin
    const first = this.candles[0].time;
    const open = this.state.positions.filter(same);
    const trades = [...this.state.closed.filter(same), ...open]
      .filter((p) => p.entryTime >= first)
      .map(paperAsTrade)
      .map((x) => {   // drawn on the candles of the chart's timeframe, whatever timeframe the trade had
        const at = (time: number) => candleStart(time, tf);
        return { ...x, signalTime: at(x.signalTime), entryTime: at(x.entryTime), exitTime: x.exitTime == null ? null : at(x.exitTime),
          breakevenTime: x.breakevenTime == null ? null : at(x.breakevenTime) };
      })
      .sort((a, b) => a.entryTime - b.entryTime);
    const last = this.candles[this.candles.length - 1].time;
    this.chart.setTrades(trades, last, { long: this.t("strategies.long"), short: this.t("strategies.short") }, null,
      { markers: this.eye.markers, boxes: this.eye.boxes });
    this.applyDecor();
    // Lines: entry / stop / target (stop and target draggable), liquidation, the hidden draggable lock
    // point (drawn inside the green box), waiting limit orders, and support / resistance.
    const orders = (this.state.orders ?? []).filter((o) => o.symbol === symbol);
    const levels: Level[] = open.flatMap((p) => this.positionLevels(p));
    if (this.eye.orders) {
      levels.push(...orders.flatMap((o): Level[] => [
        { key: `o${o.id}`, price: o.price, ...this.look("orders"), title: this.t("bot.level.order") },
        { key: `os${o.id}`, price: o.stopLoss, ...this.look("orders"), color: THEME.down, title: this.t("bot.level.orderStop") },
        { key: `ot${o.id}`, price: o.takeProfit, ...this.look("orders"), color: THEME.up, title: this.t("bot.level.orderTarget") },
      ]));
    }
    levels.push(...this.supportResistance());
    this.chart.setLevels(levels);
    void this.drawStrategy(open);
  }

  /** Inside the boxes of the open positions: texts (target / stop $, reward:risk, lock) and the lock lines. */
  private applyDecor(): void {
    if (!this.state || !this.target) return;
    const fees = this.state.rules.fees;
    const decor: BoxDecor[] = [];
    const signals: number[] = [];
    for (const p of this.state.positions.filter((x) => x.symbol === this.target!.symbol)) {
      if (this.eye.strategy && p.why?.signalTime) signals.push(candleStart(p.why.signalTime, this.target.timeframe));
      if (!this.eye.boxes) continue;
      const lock = lockPrices(p, this.state.rules.lock);
      const point = this.lockPoint?.id === p.id ? this.lockPoint.price : lock?.point;
      const way = p.takeProfit - p.entryPrice;
      const trigger = lock && point != null && way ? (point - p.entryPrice) / way : null;
      const at = lock && trigger != null ? trigger * (lock.at / lock.trigger) : null;
      const profit = resultAt(p, p.takeProfit, fees.taker, fees.maker);
      const loss = resultAt(p, p.stop, fees.taker, fees.taker);
      const rr = Math.abs(p.takeProfit - p.entryPrice) / Math.abs(p.entryPrice - p.stopLoss);   // the first stop, not a moved one
      const num = (x: string) => `\u202A${x}\u202C`;   // a number keeps its own order inside Persian text (canvas)
      const texts = [this.t("box.profit", { pnl: num(`${formatMoney(profit)}$`), rr: num(`1:${rr.toFixed(1)}`) })];
      const lines: BoxDecor["lines"] = [];
      if (this.eye.lock && trigger != null && at != null) {
        texts.push(this.t("box.lock", { trigger: num(`${Math.round(trigger * 100)}%`), at: num(`${Math.round(at * 100)}%`) }));
        lines.push({ price: p.entryPrice + way * trigger, ...this.look("lockPoint") },
          { price: p.entryPrice + way * at, ...this.look("lockStop") });
      }
      const even = breakevenTrigger(p);
      if (this.eye.lock && even !== null) lines.push({ price: even, ...this.look("breakeven") });
      const from = candleStart(p.entryCandle, this.target.timeframe);
      decor.push({ from, kind: "profit", texts, lines },
        { from, kind: "loss", texts: [this.t("box.loss", { pnl: num(`${formatMoney(loss)}$`) })], lines: [] });
    }
    this.chart.setDecor(decor, signals);
  }

  /** Support / resistance: swing highs / lows of this chart (thin) and of its companion timeframe (bold). */
  private supportResistance(): Level[] {
    const out: Level[] = [];
    if (!this.target || !this.candles.length) return out;
    const price = this.candles[this.candles.length - 1].close;
    const add = (candles: Candle[], tf: string, bold: boolean) => {
      const sr = swingLevels(candles, price);
      sr.above.forEach((x, n) => out.push({ key: `r${tf}${n}`, price: x, ...this.look(bold ? "resHigher" : "resChart"),
        title: this.t("chart.resistance", { tf }), axisLabel: false }));
      sr.below.forEach((x, n) => out.push({ key: `u${tf}${n}`, price: x, ...this.look(bold ? "supHigher" : "supChart"),
        title: this.t("chart.support", { tf }), axisLabel: false }));
    };
    if (this.eye.srChart) add(this.candles, this.target.timeframe, false);
    const higher = COMPANION_TF[this.target.timeframe];
    if (this.eye.srHigher && higher) {
      const key = `${this.target.symbol}|${higher}`;
      const got = this.companion.get(key);
      if (got) add(got.candles, higher, true);
      if (!got || Date.now() - got.time > 120_000) void this.loadCompanion(this.target.symbol, higher);
    }
    return out;
  }

  private async loadCompanion(symbol: string, tf: string): Promise<void> {
    const key = `${symbol}|${tf}`;
    const got = this.companion.get(key);
    if (got && Date.now() - got.time < 30_000) return;
    this.companion.set(key, { time: Date.now(), candles: got?.candles ?? [] });
    try {
      const candles = await this.backend.getCandles({ marketType: "futures", symbol, timeframe: tf });
      this.companion.set(key, { time: Date.now(), candles });
      if (this.target?.symbol === symbol) this.drawTrades();
    } catch {
      // drawn without it
    }
  }

  /** The lines of the strategy that opened the position shown (the one clicked, else the newest). */
  private async drawStrategy(open: PaperPosition[]): Promise<void> {
    if (!this.target) return;
    const p = open.find((x) => x.id === this.target!.id) ?? open[open.length - 1];
    if (!this.eye.strategy || !p) {
      this.chart.setIndicators([]);
      return;
    }
    const key = `${p.symbol}|${this.target.timeframe}|${p.strategy}`;
    const got = this.strategyLines.get(key);
    if (got) this.chart.setIndicators(got.indicators.filter((r) => r.pane === "price"), this.lines.strategy);
    if (got && Date.now() - got.time < 120_000) return;
    this.strategyLines.set(key, { time: Date.now(), indicators: got?.indicators ?? [] });
    try {
      const run = await this.backend.runStrategy(p.symbol, this.target.timeframe, p.strategy);
      this.strategyLines.set(key, { time: Date.now(), indicators: run.indicators });
      if (this.target && `${this.target.symbol}|${this.target.timeframe}|${p.strategy}` === key && this.eye.strategy) {
        this.chart.setIndicators(run.indicators.filter((r) => r.pane === "price"), this.lines.strategy);
      }
    } catch {
      // drawn without them
    }
  }

  private positionLevels(p: PaperPosition): Level[] {
    const digits = this.chart.pricePrecision;
    const fees = this.state!.rules.fees;
    const now = () => p.lastPrice ?? this.candles[this.candles.length - 1]?.close ?? p.entryPrice;
    const evenTitle = this.t("bot.level.breakevenAt");
    const lockTitle = this.t("bot.level.lockAt");
    const label = (kind: "stop" | "target", price: number) => {
      const level = this.t(kind === "target" ? "bot.level.target" : p.lockedAt ? "bot.level.locked"
        : p.breakevenAt ? "bot.level.breakeven" : "bot.level.stop");
      const pnl = resultAt(p, price, fees.taker, kind === "target" ? fees.maker : fees.taker);
      const bad = levelProblem(p, kind, price, now()) ? "⛔ " : "";
      return bad + this.t("bot.drag.label", { level, price: formatPrice(price, digits), pnl: formatMoney(pnl) });
    };
    const drag = (kind: "stop" | "target") => ({
      onMove: (price: number) => {
        const others: Record<string, { price: number; title: string }> = {};
        if (kind === "target") {   // the lock point follows the target (its hidden handle too)
          const lock = lockPrices(p, this.state?.rules.lock, price);
          if (lock !== null) others[`k${p.id}`] = { price: lock.point, title: "" };
        }
        return { title: label(kind, price), others };
      },
      onDrop: (price: number) => void this.moveLevel(p, kind, Number(price.toFixed(digits))),
    });
    const short = (kind: "stop" | "target") => this.t(kind === "target" ? "bot.level.target"
      : p.lockedAt ? "bot.level.locked" : p.breakevenAt ? "bot.level.breakeven" : "bot.level.stop");
    const levels: Level[] = [];
    if (this.eye.levels) {
      levels.push(
        { key: `e${p.id}`, price: p.entryPrice, ...this.look("entry"), title: this.t("bot.level.entrySized", {
          kind: this.t(p.entryType === "limit" ? "bot.entry.limit" : "bot.entry.market"),
          margin: p.margin.toFixed(2), lev: String(p.leverage) }) },
        { key: `s${p.id}`, price: p.stop, ...this.look("stop"), title: short("stop"), drag: drag("stop") },
        { key: `t${p.id}`, price: p.takeProfit, ...this.look("target"), title: short("target"), drag: drag("target") },
      );
    }
    if (this.eye.liquidation) {
      levels.push({ key: `l${p.id}`, price: p.liquidation, ...this.look("liquidation"), title: this.t("bot.level.liquidation") });
    }
    // The profit-lock point: drawn inside the green box; this hidden line only makes it draggable.
    const lock = lockPrices(p, this.state!.rules.lock);
    if (lock && this.eye.lock && this.eye.boxes) {
      levels.push({ key: `k${p.id}`, price: lock.point, color: "#b388ff", title: "", hidden: true, drag: {
        onMove: (price: number) => {
          this.lockPoint = { id: p.id, price };
          this.applyDecor();
          return { title: "" };
        },
        onDrop: (price: number) => void this.moveLockPoint(p, Number(price.toFixed(digits))),
      } });
    }
    void lockTitle;
    void evenTitle;
    return levels;
  }

  private async loadHistory(symbol: string, timeframe: string): Promise<void> {
    const key = `${symbol}|${timeframe}`;
    this.historyLoading.add(key);
    try {
      const o = await this.backend.getStrategyOverview({ marketType: "futures", symbol, timeframe,
        tradingMode: ["1m", "3m", "5m"].includes(timeframe) ? "scalping" : "daily", settings: {}, active: null,
        autoRule: null, fees: null });
      this.history.set(key, { time: Date.now(), rows: o.rows, candles: o.candles });
    } catch {
      this.history.set(key, { time: Date.now() - 240_000, rows: [], candles: 0 });   // try again in a minute
    }
    this.historyLoading.delete(key);
    this.renderPanel();
  }

  /** A Telegram change or test; its answer (or error) is shown under the buttons. */
  private async telegram(call: () => Promise<PaperState>, ok?: string): Promise<void> {
    try {
      this.state = await call();
      this.tgTest = ok ?? null;
    } catch (error) {
      this.tgTest = this.t("bot.tg.error", { error: error instanceof Error ? error.message : String(error) });
    }
    this.renderPanel();
  }

  /** The owner let go of the profit-lock point of one position: sent to the bot at once. */
  private async moveLockPoint(p: PaperPosition, price: number): Promise<void> {
    try {
      this.state = await this.backend.paperAction({ kind: "levels", position_id: p.id, lock_point: price });
      this.error = null;
    } catch (error) {
      const code = error instanceof Error ? error.message : String(error);
      this.error = ["lock_off", "lock_done", "lock_side"].includes(code) ? this.t(`bot.drag.${code}` as MessageKey) : code;
    }
    this.lockPoint = null;
    this.render();
    this.drawTrades();
  }

  /** The owner let go of a dragged stop or target line: checked here first, then sent to the bot at once. */
  private async moveLevel(p: PaperPosition, kind: "stop" | "target", price: number): Promise<void> {
    const now = p.lastPrice ?? this.candles[this.candles.length - 1]?.close ?? p.entryPrice;
    const problem = levelProblem(p, kind, price, now);
    if (problem) {
      this.error = this.t(`bot.drag.${problem}` as MessageKey);
    } else {
      try {
        this.state = await this.backend.paperAction(kind === "stop"
          ? { kind: "levels", position_id: p.id, stop: price }
          : { kind: "levels", position_id: p.id, take_profit: price });
        this.error = null;
      } catch (error) {
        const code = error instanceof Error ? error.message : String(error);
        this.error = ["stop_side", "stop_liquidation", "target_side"].includes(code)
          ? this.t(`bot.drag.${code}` as MessageKey)
          : code.startsWith("no open position") ? this.t("bot.drag.missing") : code;
      }
    }
    this.render();
    this.drawTrades();   // the line goes to its new place, or back where it was
  }

  // ---------- screen ----------

  private render(): void {
    this.els.error.hidden = !this.error;
    if (this.error) this.els.errorText.textContent = this.error;
    this.renderTitle();
    // Do not redraw the panel while the owner is typing (money, keys, coin search).
    if (!this.typing()) this.renderPanel();
    this.renderTrades();
    this.renderConsult();
  }

  /** A new element with a class and text (the consult bar). */
  private static el(tag: string, cls: string, text = ""): HTMLElement {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  /** Answers of the "stay or exit?" button by position id; asking: waiting for Gemini. */
  /** What is drawn on the chart (the eye buttons, top-left), kept in the browser. */
  private eye: Record<EyeGroup, boolean> = loadEye();
  private eyeOpen = false;
  /** Colour, style and width of the chart's lines (the gear next to the eye), kept in this browser. */
  private lines: Record<LineGroup, LineLook> = loadLines();
  private linesOpen = false;
  /** A profit-lock point being dragged (position id, price), drawn in the box until let go. */
  private lockPoint: { id: number; price: number } | null = null;
  /** Explanations open in the bar under the chart, by position id. */
  private explaining = new Set<number>();
  /** Companion-timeframe candles for support / resistance, and strategy lines, by key, with their time. */
  private companion = new Map<string, { time: number; candles: Candle[] }>();
  private strategyLines = new Map<string, { time: number; indicators: IndicatorResult[] }>();
  private tgTest: string | null = null;
  /** The owner's open / close choice of each panel section (this computer), and which switches were on. */
  private folds: Partial<Record<PanelSection, boolean>> = loadFolds();
  private wasOn: Partial<Record<PanelSection, boolean>> = {};
  /** History test of the strategies on a coin and timeframe ("symbol|tf"), asked for when its section is open. */
  private history = new Map<string, { time: number; rows: StrategyRow[]; candles: number }>();
  private historyLoading = new Set<string>();   // the last Telegram test's words
  private consults = new Map<number, ConsultAnswer>();
  private consulting = new Set<number>();
  /** The consult window open (full answers) or folded to one line, so the chart gets its room back. */
  private consultOpen = (() => {
    try { return localStorage.getItem("consultOpen") !== "0"; } catch { return true; }
  })();

  private setConsultOpen(open: boolean): void {
    this.consultOpen = open;
    try { localStorage.setItem("consultOpen", open ? "1" : "0"); } catch { /* not kept */ }
    this.renderConsult();   // the chart follows its box by itself (autoSize)
  }

  /** Under the chart: for each open position of this chart, the button (right) and its answer (to its left). */
  private renderConsult(): void {
    const box = this.els.consult;
    const t = this.t.bind(this);
    const here = (this.state?.positions ?? []).filter((p) => this.target && p.symbol === this.target.symbol);
    box.hidden = !here.length;
    box.replaceChildren();
    box.classList.toggle("folded", !this.consultOpen);
    // The tab: folds the window to one line (the verdicts) or opens it again.
    const tab = BotApp.el("button", "consult-tab", `${this.consultOpen ? "▾" : "▴"} ${t(this.consultOpen ? "consult.fold" : "consult.unfold")}`);
    tab.addEventListener("click", () => this.setConsultOpen(!this.consultOpen));
    box.append(tab);
    for (const p of here) {
      const row = BotApp.el("div", "consult-row");
      if (!this.consultOpen) {   // folded: the button and one line with the latest verdicts
        const button = BotApp.el("button", "consult-button small", this.consulting.has(p.id) ? t("consult.asking") : t("consult.button"));
        (button as HTMLButtonElement).disabled = this.consulting.has(p.id);
        button.addEventListener("click", () => void this.askConsult(p));
        const last = this.consults.get(p.id) ?? p.consults?.[p.consults.length - 1];
        row.append(button, BotApp.el("div", "consult-line", last ? this.consultSummary(last) : t("consult.hint")));
        box.append(row);
        continue;
      }
      const button = BotApp.el("button", "consult-button", this.consulting.has(p.id) ? t("consult.asking") : t("consult.button"));
      (button as HTMLButtonElement).disabled = this.consulting.has(p.id);
      button.addEventListener("click", () => void this.askConsult(p));
      // «Explanation»: why the bot entered this position (from what it stored when it opened).
      const explain = BotApp.el("button", `consult-button why-button${this.explaining.has(p.id) ? " active" : ""}`, t("why.button"));
      explain.addEventListener("click", () => {
        if (this.explaining.has(p.id)) this.explaining.delete(p.id);
        else this.explaining.add(p.id);
        this.renderConsult();
      });
      const buttons = BotApp.el("div", "consult-buttons");
      buttons.append(button, explain);
      const answer = this.consults.get(p.id) ?? p.consults?.[p.consults.length - 1];
      const message = BotApp.el("div", "consult-message");
      if (this.explaining.has(p.id)) {
        message.append(BotApp.el("div", "why-title", t("why.title", { symbol: p.symbol.split(":")[0], tf: p.timeframe })),
          ...explainLines(p, t, this.chart.pricePrecision).map((line) => BotApp.el("div", "why-line", line)));
      } else if (this.consulting.has(p.id)) message.append(BotApp.el("div", "consult-wait", t("consult.wait")));
      else if (answer) message.append(...this.consultLines(p, answer));
      else message.append(BotApp.el("div", "consult-wait", t("consult.hint")));
      row.append(buttons, message);
      box.append(row);
    }
  }

  /** One line for the folded window: the bot's and the AI's verdicts. */
  private consultSummary(a: ConsultAnswer): string {
    const t = this.t.bind(this);
    const bot = t(a.bot.suggest === "close" ? "consult.bot.close" : "consult.bot.hold");
    if (!a.ai) return t("consult.summaryBot", { bot });
    const verdict = a.ai.action === "exit" ? t("consult.ai.exit") : a.ai.action === "move_stop"
      ? t("consult.ai.move", { price: formatPrice(a.ai.newStop ?? 0, this.chart.pricePrecision) }) : t("consult.ai.hold");
    return t("consult.summary", { bot, verdict, confidence: a.ai.confidence == null ? "–" : String(Math.round(a.ai.confidence)) });
  }

  private consultLines(p: PaperPosition, a: ConsultAnswer): HTMLElement[] {
    const t = this.t.bind(this);
    const digits = this.chart.pricePrecision;
    const out: HTMLElement[] = [];
    const b = a.bot;
    const arrows = Object.entries(b.trends).map(([tf, tr]) => `${tf} ${tr === "up" ? "↑" : tr === "down" ? "↓" : "→"}`).join("  ");
    const levels = [b.swingHighAbove != null ? t("consult.resistance", { price: formatPrice(b.swingHighAbove, digits) }) : "",
      b.swingLowBelow != null ? t("consult.support", { price: formatPrice(b.swingLowBelow, digits) }) : ""].filter(Boolean).join(" · ");
    const why = t(`bot.advice.why.${b.reason}` as MessageKey, { detail: b.reason === "opposite"
      ? t(`strat.${b.detail}` as MessageKey) : t(`state.${b.detail || "unknown"}` as MessageKey) });
    out.push(BotApp.el("div", `consult-bot ${b.suggest}`, t("consult.bot", {
      suggest: t(b.suggest === "close" ? "consult.bot.close" : "consult.bot.hold"), why,
      progress: b.progress == null ? "–" : String(b.progress), r: b.r == null ? "–" : formatR(b.r) })));
    out.push(BotApp.el("div", "consult-facts", [arrows, b.rsi != null ? `RSI ${b.rsi}` : "", levels].filter(Boolean).join("   ·   ")));
    if (a.ai) {
      const ai = a.ai;
      const verdict = ai.action === "exit" ? t("consult.ai.exit") : ai.action === "move_stop"
        ? t("consult.ai.move", { price: formatPrice(ai.newStop ?? 0, digits) }) : t("consult.ai.hold");
      const head = BotApp.el("div", `consult-ai ${ai.action}`, t("consult.ai", { verdict,
        confidence: ai.confidence == null ? "–" : String(Math.round(ai.confidence)) }));
      out.push(head, BotApp.el("div", "consult-reason", ai.reason));
      if (ai.levels) out.push(BotApp.el("div", "consult-facts", t("consult.levels", { levels: ai.levels })));
      if (ai.note === "badStop") out.push(BotApp.el("div", "consult-facts", t("consult.badStop")));
      const still = this.state?.positions.some((x) => x.id === p.id);
      if (still && ai.action === "exit") {
        const go = BotApp.el("button", "consult-act", t("consult.doExit"));
        go.addEventListener("click", () => void this.act({ kind: "close", position_id: p.id }));
        out.push(go);
      }
      if (still && ai.action === "move_stop" && ai.newStop != null) {
        const go = BotApp.el("button", "consult-act", t("consult.doMove", { price: formatPrice(ai.newStop, digits) }));
        go.addEventListener("click", () => void this.act({ kind: "levels", position_id: p.id, stop: ai.newStop! }));
        out.push(go);
      }
    } else {
      out.push(BotApp.el("div", "consult-error", a.error === "noKeys" ? t("consult.noKeys") : t("consult.error", { error: a.error ?? "" })));
    }
    out.push(BotApp.el("div", "consult-time", t("consult.when", { time: new Date(a.time * 1000).toTimeString().slice(0, 5) })));
    return out;
  }

  private async askConsult(p: PaperPosition): Promise<void> {
    if (this.consulting.has(p.id)) return;
    this.consulting.add(p.id);
    this.renderConsult();
    try {
      this.consults.set(p.id, await this.backend.consult(p.id));
      if (!this.consultOpen) this.setConsultOpen(true);   // a new answer opens the window to be read
    } catch (error) {
      this.consults.set(p.id, { position: p.id, time: Date.now() / 1000, ai: null,
        error: error instanceof Error ? error.message : String(error),
        bot: { suggest: "hold", reason: "unknown", detail: "", marketState: null, progress: null, pnl: 0, r: null,
          price: p.entryPrice, trends: {}, rsi: null, swingHighAbove: null, swingLowBelow: null } });
    } finally {
      this.consulting.delete(p.id);
      this.renderConsult();
    }
  }

  private renderTitle(): void {
    if (!this.target) return;
    this.els.chartTitle.textContent = `${this.target.symbol.split(":")[0]} · ${this.target.timeframe}`;
    // The chart's timeframe can be changed; the trades of this coin are drawn on any timeframe.
    const tfs = this.els.tfs;
    tfs.replaceChildren();
    for (const tf of CHART_TFS) {
      const b = document.createElement("button");
      b.textContent = tf;
      if (tf === this.target.timeframe) b.className = "active";
      b.addEventListener("click", () => {
        if (!this.target || tf === this.target.timeframe) return;
        this.pinned = true;
        void this.showChart({ ...this.target, timeframe: tf });
      });
      tfs.append(b);
    }
    this.renderEye();
  }

  /** The owner's look of one group of lines. */
  private look(g: LineGroup): { color: string; style: LineStyleName; width: number } {
    return this.lines[g];
  }

  /** The gear next to the eye: colour, style and width of each group of lines. */
  private renderLines(box: HTMLElement): void {
    const t = this.t.bind(this);
    const tf = this.target?.timeframe ?? "";
    const higher = COMPANION_TF[tf] ?? "";
    const list = document.createElement("div");
    list.className = "eye-list line-list";
    for (const g of LINE_GROUPS) {
      const row = document.createElement("div");
      row.className = "line-row";
      const name = document.createElement("span");
      name.textContent = t(`lines.${g}` as MessageKey, { tf: g.endsWith("Higher") ? higher : tf });
      row.append(name);
      const look = this.lines[g];
      const changed = () => {
        saveLines(this.lines);
        this.strategyLines.forEach((v) => (v.time = 0));
        this.drawTrades();
      };
      if (g !== "strategy") {
        const color = document.createElement("input");
        color.type = "color";
        color.value = look.color;
        color.addEventListener("input", () => {
          look.color = color.value;
          changed();
        });
        row.append(color);
      } else {
        row.append(Object.assign(document.createElement("span"), { className: "line-auto", textContent: t("lines.auto") }));
      }
      const style = document.createElement("select");
      for (const v of ["solid", "dashed", "dotted"] as LineStyleName[]) {
        style.append(new Option(t(`lines.style.${v}` as MessageKey), v, false, look.style === v));
      }
      style.addEventListener("change", () => {
        look.style = style.value as LineStyleName;
        changed();
      });
      const width = document.createElement("select");
      for (const w of [1, 2, 3, 4]) width.append(new Option(String(w), String(w), false, look.width === w));
      width.addEventListener("change", () => {
        look.width = Number(width.value);
        changed();
      });
      row.append(style, width);
      list.append(row);
    }
    const reset = document.createElement("button");
    reset.className = "eye-row";
    reset.textContent = t("lines.reset");
    reset.addEventListener("click", () => {
      this.lines = loadLines(() => null);
      saveLines(this.lines);
      this.renderEye();
      this.drawTrades();
    });
    list.append(reset);
    box.append(list);
  }

  /** Top-left of the chart: an eye button that opens the list of things drawn, each with its own eye. */
  private renderEye(): void {
    const box = this.els.eye;
    const t = this.t.bind(this);
    box.replaceChildren();
    const toggle = document.createElement("button");
    toggle.className = "eye-toggle";
    toggle.textContent = "👁";
    toggle.title = t("eye.title");
    toggle.addEventListener("click", () => {
      this.eyeOpen = !this.eyeOpen;
      if (this.eyeOpen) this.linesOpen = false;
      this.renderEye();
    });
    const gear = document.createElement("button");
    gear.className = "eye-toggle";
    gear.textContent = "⚙";
    gear.title = t("lines.title");
    gear.addEventListener("click", () => {
      this.linesOpen = !this.linesOpen;
      if (this.linesOpen) this.eyeOpen = false;
      this.renderEye();
    });
    const buttons = document.createElement("div");
    buttons.className = "eye-buttons";
    buttons.append(toggle, gear);
    box.append(buttons);
    if (this.linesOpen) {
      this.renderLines(box);
      return;
    }
    if (!this.eyeOpen) return;
    const tf = this.target?.timeframe ?? "";
    const list = document.createElement("div");
    list.className = "eye-list";
    for (const g of EYE_GROUPS) {
      const row = document.createElement("button");
      row.className = `eye-row${this.eye[g] ? "" : " off"}`;
      const label = g === "srChart" ? t("eye.srChart", { tf }) : g === "srHigher" ? t("eye.srHigher", { tf: COMPANION_TF[tf] ?? "" })
        : t(`eye.${g}` as MessageKey);
      row.textContent = `${this.eye[g] ? "👁" : "◌"}  ${label}`;
      row.addEventListener("click", () => {
        this.eye[g] = !this.eye[g];
        saveEye(this.eye);
        this.renderEye();
        this.drawTrades();
      });
      list.append(row);
    }
    box.append(list);
  }

  private renderPanel(): void {
    const t = this.t.bind(this);
    const s = this.state;
    const panel = this.els.panel;
    if (!s) {
      panel.textContent = t("chart.loading");
      return;
    }
    const parts: HTMLElement[] = [];
    const el = (tag: string, cls: string, text = "") => {
      const e = document.createElement(tag);
      e.className = cls;
      e.textContent = text;
      return e;
    };

    const heading = (id: PanelSection, text: string) => {
      const h = el("div", "list-heading", text);
      h.dataset.section = id;
      return h;
    };

    parts.push(el("div", "section-title", t("bot.title")));
    // Start / Stop.
    const running = s.status === "running";
    const power = el("button", `bot-power ${running ? "on" : ""}`, t(running ? "bot.stopButton" : "bot.startButton"));
    (power as HTMLButtonElement).disabled = s.status === "halted";
    power.addEventListener("click", () => void this.act({ kind: running ? "stop" : "start" }));
    parts.push(power);
    // Signals waiting for the owner because the AI did not answer.
    for (const q of s.pendingAsks ?? []) {
      const box = el("div", "bot-ask");
      const digits = pricePrecision(q.entry);
      const left = Math.max(0, Math.round(q.expires - Date.now() / 1000));   // seconds until it opens by itself
      box.append(el("div", "bot-ask-title", t("bot.ask.title")), el("div", "bot-hint", t("bot.ask.line", {
        coin: q.base, tf: q.timeframe, side: t(q.side === "long" ? "strategies.long" : "strategies.short"),
        strategy: t(`strat.${q.strategy}` as MessageKey), entry: formatPrice(q.entry, digits),
        stop: formatPrice(q.stopLoss, digits), target: formatPrice(q.takeProfit, digits), left: String(left),
      })));
      const yes = el("button", "bot-reset", t("bot.ask.open"));
      yes.addEventListener("click", () => void this.act({ kind: "ask", id: q.id, answer: "open" }));
      const no = el("button", "bot-reset", t("bot.ask.skip"));
      no.addEventListener("click", () => void this.act({ kind: "ask", id: q.id, answer: "skip" }));
      const row = el("div", "bot-ask-buttons");
      row.append(yes, no);
      box.append(row);
      parts.push(box);
    }
    parts.push(el("div", `bot-status ${s.status}`, t(statusKey(s), {
      tf: s.scanning ?? "",
      until: s.pausedUntil ? formatClock(s.pausedUntil * 1000, this.zone).slice(0, 5) : "",
      reason: s.pauseReason ? t(s.pauseReason === "streak" ? "bot.pause.streak" : "bot.pause.fall") : "",
    })));
    // Half way to the target the bot advises: hold or close. The owner answers with a button.
    const waiting = s.positions.filter((p) => p.advice && p.advice.answer === null);
    if (waiting.length) {
      parts.push(el("div", "list-heading", t("bot.advice.title")));
      for (const p of waiting) {
        const card = el("div", `bot-advice ${p.advice!.suggest}`);
        card.append(el("div", "", adviceText(p, t)));
        const buttons = el("div", "bot-advice-buttons");
        for (const answer of ["hold", "close"] as const) {
          const b = el("button", answer === p.advice!.suggest ? "suggested" : "", t(answer === "hold" ? "bot.advice.hold" : "bot.advice.close"));
          b.addEventListener("click", () => void this.act({ kind: "advice", position_id: p.id, answer }));
          buttons.append(b);
        }
        card.append(buttons);
        parts.push(card);
      }
    }
    // What happened to the signals lately.
    if (s.btc && (s.btc["1h"] || s.btc["4h"])) {   // step 3: Bitcoin's trend, which the coins that follow it need
      const word = (x: string | null | undefined) => x ? t(`bot.trend.${x}` as MessageKey) : "–";
      parts.push(el("div", "bot-hint btc-line", t("bot.btcLine", { h1: word(s.btc["1h"]), h4: word(s.btc["4h"]) })));
    }
    if (s.flow) {
      parts.push(el("div", "bot-hint", t("bot.flow", { seen: String(s.flow.seen), opened: String(s.flow.opened) })));
      if (s.flow.placed) parts.push(el("div", "bot-hint", t("bot.flowPlaced", { n: String(s.flow.placed) })));
      const times = Object.entries(s.scanSeconds ?? {});
      if (times.length) {
        parts.push(el("div", "bot-hint", t("bot.scanTimes", { list: times.map(([tf, sec]) => `${tf}: ${sec}s`).join("، ") })));
      }
      const skipped = Object.entries(s.flow.skipped);
      if (skipped.length) {
        parts.push(el("div", "bot-hint", t("bot.flowSkipped", {
          list: skipped.map(([reason, n]) => `${t(`bot.skip.${reason}` as MessageKey)} (${n})`).join("، "),
        })));
      }
    }
    const benched = Object.keys(s.benched ?? {});
    if (benched.length) {
      parts.push(el("div", "bot-hint", t("bot.benchedNow", { list: benched.map((k) => t(`strat.${k}` as MessageKey)).join("، ") })));
    }

    // Money.
    const money = el("dl", "bot-money");
    const row = (label: MessageKey, value: string, cls = "") => {
      money.append(el("dt", "", t(label)));
      const dd = el("dd", cls, value);
      dd.dir = "ltr";
      money.append(dd);
    };
    const sign = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "");
    row("bot.equity", `${s.equity.toFixed(2)} USDT`);
    row("bot.total", `${formatMoney(s.stats.netPnl)} (${formatPercent(s.stats.netPercent)})`, sign(s.stats.netPnl));
    row("bot.today", formatMoney(s.stats.todayPnl), sign(s.stats.todayPnl));
    // Break-even trades are neither won nor lost (owner 2026-11-09): shown on their own.
    row("bot.winRate", s.stats.winRate === null ? "—" : `${s.stats.winRate.toFixed(0)}% (${t("bot.winSplit", {
      w: String(s.stats.wins), l: String(s.stats.losses ?? s.stats.trades - s.stats.wins), e: String(s.stats.evens ?? 0) })})`);
    row("bot.drawdown", `${s.stats.maxDrawdown.toFixed(1)}%`);
    row("bot.feesPaid", `${s.stats.fees.toFixed(2)} USDT`);
    parts.push(money);

    // Virtual money: the owner chooses the amount.
    const capital = el("div", "bot-capital");
    const label = el("label", "", t("bot.capital"));
    const input = document.createElement("input");
    input.type = "number";
    input.min = "10";
    input.step = "1";
    input.dir = "ltr";
    input.value = this.capitalDraft ?? String(s.capital);
    input.addEventListener("input", () => (this.capitalDraft = input.value));
    const reset = el("button", "bot-reset", t(this.confirmReset ? "bot.resetConfirm" : "bot.reset"));
    reset.addEventListener("click", () => {
      const value = Number(input.value);
      if (!Number.isFinite(value) || value < 10) {
        input.classList.add("invalid");
        return;
      }
      if (!this.confirmReset) {
        this.confirmReset = true; // a second press is needed: the old trades are removed
        this.renderPanel();
        setTimeout(() => {
          this.confirmReset = false;
          this.renderPanel();
        }, 4000);
        return;
      }
      this.confirmReset = false;
      this.capitalDraft = null;
      void this.act({ kind: "reset", capital: value });
    });
    capital.append(label, input, reset);
    parts.push(capital, el("div", "bot-hint", t("bot.resetHint")));

    // Timeframes the bot may trade on: the owner ticks them (all others are still watched for learning).
    if (s.timeframes.length > 1) {
      const chosen = s.chosenTimeframes ?? s.timeframes;
      const list = el("div", "bot-timeframes");
      for (const tf of s.timeframes) {
        const line = el("label", "");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = chosen.includes(tf);
        box.addEventListener("change", () => {
          const now = this.state ?? s;   // the latest state: earlier ticks may not be redrawn yet
          const next = toggled(now.timeframes, now.chosenTimeframes ?? now.timeframes, tf, box.checked);
          if (!next.length) {
            box.checked = true; // at least one
            return;
          }
          now.chosenTimeframes = next;   // at once, so a quick next tick builds on this one
          void this.act({ kind: "timeframes", timeframes: next });
        });
        const name = el("span", "", tf);
        name.dir = "ltr";
        line.append(box, name);
        list.append(line);
      }
      // The owner's maximum of open trades (2026-11-10); the margin share of one trade follows it.
      const maxRow = el("label", "bot-review-row", t("bot.maxOpen"));
      const maxInput = document.createElement("input");
      maxInput.type = "number";
      maxInput.min = "1";
      maxInput.max = "20";
      maxInput.dir = "ltr";
      maxInput.value = String(s.rules.maxOpen ?? 6);
      maxInput.addEventListener("change", () => {
        const n = Math.round(Number(maxInput.value));
        if (!(n >= 1 && n <= 20)) {
          maxInput.classList.add("invalid");
          return;
        }
        void this.act({ kind: "max-open", value: n });
      });
      maxRow.append(maxInput);
      // Owner 2026-11-11: a coin waits this many hours after a stop-loss (a number, 0 = off).
      const pauseParts: HTMLElement[] = [];
      if (s.coinPause) {
        const cp = s.coinPause;
        const pauseRow = el("label", "bot-review-row", t("bot.coinPause"));
        const pauseInput = document.createElement("input");
        pauseInput.type = "number";
        pauseInput.min = "0";
        pauseInput.max = "168";
        pauseInput.step = "0.5";
        pauseInput.dir = "ltr";
        pauseInput.value = String(cp.hours);
        pauseInput.addEventListener("change", () => {
          const h = Number(pauseInput.value);
          if (!(h >= 0 && h <= 168) || pauseInput.value.trim() === "") {
            pauseInput.classList.add("invalid");
            return;
          }
          void this.act({ kind: "coin-pause", hours: h });
        });
        pauseRow.append(pauseInput);
        const now = Date.now() / 1000;
        const waiting = Object.entries(cp.paused).filter(([, until]) => until > now)
          .map(([coin, until]) => t("bot.coinPause.left", { coin, minutes: String(Math.ceil((until - now) / 60)) }));
        pauseParts.push(pauseRow, el("div", "bot-hint", t(cp.hours > 0 ? "bot.coinPauseHint" : "bot.coinPauseOff")));
        if (waiting.length) pauseParts.push(el("div", "bot-hint", t("bot.coinPause.now", { list: waiting.join("، ") })));
      }
      // The owner's focus switch (2026-11-10): 5m + 15m on the volatile coins, the earlier settings kept.
      const focusParts: HTMLElement[] = [];
      if (s.focus) {
        const f = s.focus;
        const onOff = el("div", "segmented small");
        for (const on of [true, false]) {
          const b = el("button", f.on === on ? "active" : "", t(on ? "bot.ai.on" : "bot.ai.off"));
          b.addEventListener("click", () => {
            if (f.on !== on) void this.act({ kind: "focus", on });
          });
          onOff.append(b);
        }
        const row = el("div", "bot-review-row", t("bot.focus"));
        row.append(onOff);
        const line = (name: "focus" | "other") => {
          const x = f.stats[name];
          const decided = x.wins + x.losses;
          return t(name === "focus" ? "bot.focus.focus" : "bot.focus.other", {
            n: String(x.trades), rate: decided ? String(Math.round((x.wins / decided) * 100)) : "–",
            pnl: formatMoney(x.pnl),
          });
        };
        focusParts.push(row, el("div", "bot-hint", t(f.on ? "bot.focus.onHint" : "bot.focus.offHint")),
          el("div", "bot-hint", line("focus")), el("div", "bot-hint", line("other")));
      }
      parts.push(heading("timeframes", t("bot.timeframes")), ...focusParts, list, el("div", "bot-hint", t("bot.timeframesHint")),
        maxRow, el("div", "bot-hint", t("bot.maxOpenHint")), ...pauseParts);
    }

    // Limit entry (paper only): on/off, the waiting orders, market vs limit results.
    {
      const onOff = el("div", "segmented small");
      for (const on of [true, false]) {
        const b = el("button", !!s.limitEntry === on ? "active" : "", t(on ? "bot.ai.on" : "bot.ai.off"));
        b.addEventListener("click", () => {
          if (!!s.limitEntry !== on) void this.act({ kind: "limit", enabled: on });
        });
        onOff.append(b);
      }
      parts.push(heading("limit", t("bot.limit.title")), onOff, el("div", "bot-hint", t("bot.limit.hint", {
        offset: String(s.rules.limitOffset ?? 10), maker: String(s.rules.fees.maker), taker: String(s.rules.fees.taker),
      })));
      const orders = s.orders ?? [];
      if (orders.length) {
        const list = el("div", "bot-orders");
        const nowSec = Date.now() / 1000;
        for (const o of orders) {
          const left = timeLeft(o.expires - nowSec);
          list.append(el("div", `bot-order side ${o.side}`, t("bot.limit.order", {
            coin: o.base, tf: o.timeframe, side: t(o.side === "long" ? "strategies.long" : "strategies.short"),
            price: formatPrice(o.price, pricePrecision(o.price)),
            left: t(left.unit === "s" ? "bot.limit.left.s" : "bot.limit.left.m", { n: left.n }),
          })));
        }
        parts.push(el("div", "bot-hint", t("bot.limit.orders")), list);
      }
      const st = s.entryStats;
      if (st && (st.market.trades || st.limit.trades || st.limit.orders.placed)) {
        const table = document.createElement("table");
        table.className = "bot-compare";
        const head = document.createElement("tr");
        for (const k of ["bot.limit.colKind", "bot.limit.colTrades", "bot.limit.colWin", "bot.limit.colR", "bot.limit.colFees"] as MessageKey[]) {
          head.append(el("th", "", t(k)));
        }
        table.append(head);
        for (const kind of ["market", "limit"] as const) {
          const r = st[kind];
          const tr = document.createElement("tr");
          tr.append(el("td", "", t(kind === "market" ? "bot.limit.market" : "bot.limit.limit")),
            el("td", "", String(r.trades)),
            el("td", "", r.winRate == null ? "–" : String(Math.round(r.winRate))),
            el("td", r.avgR == null ? "" : r.avgR > 0 ? "up" : r.avgR < 0 ? "down" : "", formatR(r.avgR)),
            el("td", "", r.fees.toFixed(2)));
          for (const td of Array.from(tr.children).slice(1)) (td as HTMLElement).dir = "ltr";
          table.append(tr);
        }
        const o = st.limit.orders;
        const ended = o.filled + o.expired + o.cancelled;
        parts.push(el("div", "bot-hint", t("bot.limit.compare")), table, el("div", "bot-hint", ended
          ? t("bot.limit.fillRate", { rate: String(Math.round(st.limit.fillRate ?? 0)), filled: String(o.filled),
              ended: String(ended), expired: String(o.expired), cancelled: String(o.cancelled) })
          : t("bot.limit.noFills")));
      }
    }

    // The AI's approval (Gemini): on/off, the timeframes it checks, the owner's keys.
    if (s.ai) {
      const ai = s.ai;
      const onOff = el("div", "segmented small");
      for (const on of [true, false]) {
        const b = el("button", ai.enabled === on ? "active" : "", t(on ? "bot.ai.on" : "bot.ai.off"));
        b.addEventListener("click", () => {
          if (ai.enabled !== on) void this.act({ kind: "ai", enabled: on, timeframes: ai.timeframes });
        });
        onOff.append(b);
      }
      parts.push(heading("ai", t("bot.ai.title")), onOff);
      const tfs = el("div", "bot-timeframes");
      for (const tf of s.timeframes) {
        const line = el("label", "");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = ai.timeframes.includes(tf);
        box.addEventListener("change", () => {
          const now = (this.state ?? s).ai ?? ai;
          const next = toggled(s.timeframes, now.timeframes, tf, box.checked);
          now.timeframes = next;
          void this.act({ kind: "ai", enabled: now.enabled, timeframes: next });
        });
        const name = el("span", "", tf);
        name.dir = "ltr";
        line.append(box, name);
        tfs.append(line);
      }
      parts.push(el("div", "bot-hint", t("bot.ai.timeframes")), tfs);
      const keysBox = el("div", "bot-capital");
      const area = document.createElement("textarea");
      area.rows = 2;
      area.dir = "ltr";
      area.autocomplete = "off";
      area.spellcheck = false;
      area.placeholder = "AIza… / AQ.…";
      const saveKeys = el("button", "bot-reset", t("bot.save"));
      saveKeys.addEventListener("click", async () => {
        const keys = area.value.split(/\s+/).map((k) => k.trim()).filter(Boolean);
        try {
          this.state = await this.backend.setAiKeys(keys);
          this.error = null;
        } catch (error) {
          this.error = error instanceof Error ? error.message : String(error);
        }
        area.value = "";
        this.render();
      });
      keysBox.append(el("label", "", t("bot.ai.keys")), area, saveKeys);
      parts.push(keysBox, el("div", "bot-hint", ai.keys.length ? t("bot.ai.keysSaved", { list: ai.keys.join("، ") }) : t("bot.ai.noKeys")));
      const testRow = el("div", "bot-ask-buttons");
      const testButton = el("button", "bot-reset", t("bot.ai.test"));
      testButton.addEventListener("click", async () => {
        this.aiTest = t("bot.ai.testing");
        this.renderPanel();
        try {
          const { results } = await this.backend.testAi();
          this.aiTest = results.length
            ? results.map((r) => r.ok ? t("bot.ai.testOk", { key: r.key, s: String(r.seconds ?? ""), model: r.model ?? "" })
              : t("bot.ai.testFail", { key: r.key, error: r.error ?? "" })).join(" · ")
            : t("bot.ai.noKeys");
        } catch (error) {
          this.aiTest = t("bot.ai.testFail", { key: "", error: error instanceof Error ? error.message : String(error) });
        }
        this.renderPanel();
      });
      testRow.append(testButton);
      parts.push(testRow);
      if (this.aiTest) parts.push(el("div", "bot-hint", this.aiTest));
      parts.push(el("div", "bot-hint", t("bot.ai.hint", { model: ai.model })));
      if (ai.lastError) parts.push(el("div", "bot-hint warn", t("bot.ai.error", { error: ai.lastError })));
      const res = (k: string) => {
        const r = ai.results?.[k];
        return r ? t("bot.ai.result", { n: String(r.count), r: (r.avgR ?? 0).toFixed(2), w: String(Math.round(r.winRate ?? 0)) }) : "–";
      };
      if (ai.results && Object.keys(ai.results).length) {
        parts.push(el("div", "bot-hint", t("bot.ai.results", { yes: res("approve"), no: res("reject") })));
      }
    }

    // Telegram: a message for every closed position (owner 2026-11-09). The token is typed here once,
    // kept on this computer and never shown again; the chat is found after the owner's /start.
    if (s.telegram) {
      const tg = s.telegram;
      const onOff = el("div", "segmented small");
      for (const on of [true, false]) {
        const b = el("button", tg.enabled === on ? "active" : "", t(on ? "bot.tg.on" : "bot.tg.off"));
        b.addEventListener("click", () => void this.telegram(() => this.backend.setTelegram({ enabled: on })));
        onOff.append(b);
      }
      parts.push(heading("tg", t("bot.tg.title")), onOff, el("div", "bot-hint", t("bot.tg.what")));
      const tokenBox = el("div", "bot-capital");
      const input = document.createElement("input");
      input.type = "password";
      input.dir = "ltr";
      input.autocomplete = "off";
      input.spellcheck = false;
      input.placeholder = "123456:ABC…";
      const save = el("button", "bot-reset", t("bot.save"));
      save.addEventListener("click", () => {
        const token = input.value.trim();
        input.value = "";
        if (token) void this.telegram(() => this.backend.setTelegram({ token }));
      });
      tokenBox.append(el("label", "", t("bot.tg.token")), input, save);
      parts.push(tokenBox, el("div", "bot-hint", tg.token ? t("bot.tg.saved", { hint: tg.tokenHint }) : t("bot.tg.noToken")));
      if (tg.token) parts.push(el("div", "bot-hint", t(tg.chat ? "bot.tg.chatOk" : "bot.tg.noChat")));
      const testRow = el("div", "bot-ask-buttons");
      const testButton = el("button", "bot-reset", t("bot.tg.test"));
      (testButton as HTMLButtonElement).disabled = !tg.token;
      testButton.addEventListener("click", () => {
        this.tgTest = t("bot.tg.testing");
        this.renderPanel();
        void this.telegram(() => this.backend.testTelegram(), t("bot.tg.testOk"));
      });
      testRow.append(testButton);
      parts.push(testRow);
      if (this.tgTest) parts.push(el("div", "bot-hint", this.tgTest));
      else if (tg.lastError) parts.push(el("div", "bot-hint", t("bot.tg.error", { error: tg.lastError })));
    }

    // Which coins the bot scans: top 100 by volume, the most volatile of the last 24h, or the owner's list.
    {
      const coinMode = s.rules.coinMode ?? "top";
      const mine = s.rules.coins ?? [];
      const modes = el("div", "segmented small");
      for (const mode of ["top", "volatile", "manual"] as const) {
        const b = el("button", coinMode === mode ? "active" : "", t(`bot.coins.${mode}` as MessageKey,
          { n: String(s.rules.volatileCoins ?? 30) }));
        b.addEventListener("click", () => {
          if (coinMode === mode) return;
          if (mode === "manual" && !mine.length) {
            this.coinManualOpen = true;   // choose coins first; saved once there is at least one
            this.renderPanel();
            return;
          }
          this.coinManualOpen = false;
          void this.act({ kind: "coins", mode, coins: mine });
        });
        modes.append(b);
      }
      parts.push(heading("coins", t("bot.coins.title")), modes);
      if (coinMode === "manual" || this.coinManualOpen) {
        const chips = el("div", "bot-coin-chips");
        for (const symbol of mine) {
          const chip = el("button", "bot-coin-chip", `${symbol.split("/")[0]} ×`);
          chip.title = t("bot.coins.remove");
          chip.addEventListener("click", () => {
            const rest = (this.state?.rules.coins ?? mine).filter((c) => c !== symbol);
            if (this.state) this.state.rules.coins = rest;
            void this.act(rest.length ? { kind: "coins", mode: "manual", coins: rest } : { kind: "coins", mode: "top", coins: [] });
          });
          chips.append(chip);
        }
        const search = document.createElement("input");
        search.type = "search";
        search.dir = "ltr";
        search.placeholder = t("bot.coins.search");
        search.value = this.coinQuery;
        const found = el("div", "bot-coin-chips");
        const showFound = () => {
          found.replaceChildren(...this.coinFound.filter((m) => !mine.includes(m.symbol)).slice(0, 8).map((m) => {
            const b = el("button", "bot-coin-add", `+ ${m.base}`);
            b.addEventListener("click", () => {
              this.coinQuery = "";
              this.coinFound = [];
              this.coinManualOpen = false;
              const now = this.state?.rules.coins ?? mine;
              const next = now.includes(m.symbol) ? now : [...now, m.symbol];
              if (this.state) this.state.rules.coins = next;
              void this.act({ kind: "coins", mode: "manual", coins: next });
            });
            return b;
          }));
        };
        showFound();
        let timer: ReturnType<typeof setTimeout> | undefined;
        search.addEventListener("input", () => {
          this.coinQuery = search.value;
          clearTimeout(timer);
          timer = setTimeout(async () => {
            const query = this.coinQuery.trim();
            try {
              this.coinFound = query ? await this.backend.getMarkets("futures", query) : [];
            } catch {
              this.coinFound = [];
            }
            showFound();
          }, 300);
        });
        parts.push(chips, search, found);
      }
      parts.push(el("div", "bot-hint", t(`bot.coins.hint.${coinMode}` as MessageKey, { n: String(s.rules.volatileCoins ?? 30) })));
    }

    // Auto / Manual: in manual the owner picks the strategies, the bot does the rest.
    const modes = el("div", "segmented small");
    for (const mode of ["auto", "manual"] as const) {
      const b = el("button", s.mode === mode ? "active" : "", t(mode === "auto" ? "settings.auto" : "settings.manual"));
      b.addEventListener("click", () => {
        if (s.mode === mode) return;
        void this.act({ kind: "mode", mode, strategies: mode === "auto" ? [] : s.strategies });
      });
      modes.append(b);
    }
    parts.push(heading("strategies", t("bot.strategies")), modes);
    if (s.mode === "manual") {
      const list = el("div", "bot-strategies");
      const stats = s.strategyStats ?? {};
      const onTf = timeframesOf(s.botStrategies ?? {});
      // All strategies: from the catalog, else from the bot's own lists per timeframe (always in its state),
      // so the unticked ones never disappear when the catalog did not load at start.
      const all = allStrategies(this.cards.map((c) => c.type), s.botStrategies ?? {}, s.strategies);
      const listed = s.botStrategies ? all.filter((k) => onTf[k]) : all;
      const kinds = strategyOrder(listed, stats);
      for (const kind of kinds) {
        const row = el("div", "bot-strategy");
        const line = el("label", "");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = s.strategies.includes(kind);
        box.addEventListener("change", () => {
          const now = this.state ?? s;
          const chosen = toggled(kinds, now.strategies, kind, box.checked);
          if (!chosen.length) {
            box.checked = true; // at least one
            return;
          }
          now.strategies = chosen;
          void this.act({ kind: "mode", mode: "manual", strategies: chosen });
        });
        line.append(box, document.createTextNode(` ${t(`strat.${kind}` as MessageKey)}`));
        if (onTf[kind]) line.append(el("span", "bot-strategy-tfs", onTf[kind].join(" · ")));
        row.append(line, this.strategyStatsView(stats[kind]));
        list.append(row);
      }
      parts.push(list, el("div", "bot-hint", t("bot.statHint")));
      const retired = all.filter((k) => s.botStrategies && !onTf[k]);
      if (retired.length) {
        parts.push(el("div", "bot-hint", t("bot.retired", { list: retired.map((k) => t(`strat.${k}` as MessageKey)).join("، ") })));
      }
    } else {
      const chosen = s.chosenTimeframes ?? s.timeframes;
      const byTf = s.botStrategies ?? {};
      const list = chosen.map((tf) => `${tf}: ${(byTf[tf] ?? []).length
        ? (byTf[tf] ?? []).map((k) => t(`strat.${k}` as MessageKey)).join("، ")
        : t("bot.noStrategy")}`).join(" · ");
      parts.push(el("div", "bot-hint", t("bot.autoHint", { list })));
    }
    if (s.rules.strictTrades) {
      parts.push(el("div", "bot-hint", t("bot.strictHint", { trades: String(s.rules.strictTrades),
        pf: String(s.rules.strictProfitFactor ?? 1.5) })));
    }

    // Profit cap per position (owner's option, 0 = off).
    const capBox = el("div", "bot-capital");
    const capInput = document.createElement("input");
    capInput.type = "number";
    capInput.min = "0";
    capInput.step = "0.05";
    capInput.dir = "ltr";
    capInput.value = this.capDraft ?? String(s.rules.profitCap ?? 0);
    capInput.addEventListener("input", () => (this.capDraft = capInput.value));
    const capSave = el("button", "bot-reset", t("bot.save"));
    capSave.addEventListener("click", () => {
      const usd = Number(capInput.value);
      if (!Number.isFinite(usd) || usd < 0) {
        capInput.classList.add("invalid");
        return;
      }
      this.capDraft = null;
      void this.act({ kind: "cap", usd });
    });
    capBox.append(el("label", "", t("bot.cap")), capInput, capSave);
    parts.push(capBox, el("div", "bot-hint", t("bot.capHint")));

    // Profit lock (owner's option): at `trigger` % of the way to the target the stop moves to `at` %.
    {
      const lock = s.rules.lock ?? { enabled: false, trigger: 80, at: 40 };
      const onOff = el("div", "segmented small");
      for (const on of [true, false]) {
        const b = el("button", lock.enabled === on ? "active" : "", t(on ? "bot.ai.on" : "bot.ai.off"));
        b.addEventListener("click", () => {
          if (lock.enabled !== on) void this.act({ kind: "lock", enabled: on, trigger: lock.trigger, at: lock.at });
        });
        onOff.append(b);
      }
      const draft = this.lockDraft ?? { trigger: String(lock.trigger), at: String(lock.at) };
      const box = el("div", "bot-capital");
      const number = (value: string, key: "trigger" | "at") => {
        const input = document.createElement("input");
        input.type = "number";
        input.min = "1";
        input.max = "99";
        input.step = "5";
        input.dir = "ltr";
        input.value = value;
        input.addEventListener("input", () => {
          this.lockDraft = { ...(this.lockDraft ?? draft), [key]: input.value };
          input.classList.remove("invalid");
        });
        return input;
      };
      const triggerInput = number(draft.trigger, "trigger");
      const atInput = number(draft.at, "at");
      const save = el("button", "bot-reset", t("bot.save"));
      save.addEventListener("click", () => {
        const trigger = Number(triggerInput.value);
        const at = Number(atInput.value);
        const ok = lockValid(trigger, at);
        triggerInput.classList.toggle("invalid", !ok);
        atInput.classList.toggle("invalid", !ok);
        if (!ok) return;
        this.lockDraft = null;
        void this.act({ kind: "lock", enabled: lock.enabled, trigger, at });
      });
      box.append(el("label", "", t("bot.lock.trigger")), triggerInput, el("label", "", t("bot.lock.at")), atInput, save);
      parts.push(heading("lock", t("bot.lock.title")), onOff, box,
        el("div", "bot-hint", t("bot.lock.hint", { trigger: String(lock.trigger), at: String(lock.at) })));
    }

    // Smart pause rules (owner's option, 0 = off).
    if (s.rules.smartPause !== false) {
      const draft = this.pauseDraft ?? {
        losses: String(s.rules.pauseLosses ?? 4), fall: String(s.rules.pauseFall ?? 5),
      };
      const pauseBox = el("div", "bot-capital");
      const number = (value: string, step: string, max: string, key: "losses" | "fall") => {
        const input = document.createElement("input");
        input.type = "number";
        input.min = "0";
        input.max = max;
        input.step = step;
        input.dir = "ltr";
        input.value = value;
        input.addEventListener("input", () => {
          this.pauseDraft = { ...(this.pauseDraft ?? draft), [key]: input.value };
          input.classList.remove("invalid");
        });
        return input;
      };
      const lossesInput = number(draft.losses, "1", "50", "losses");
      const fallInput = number(draft.fall, "0.5", "50", "fall");
      const pauseSave = el("button", "bot-reset", t("bot.save"));
      pauseSave.addEventListener("click", () => {
        const losses = Number(lossesInput.value);
        const fall = Number(fallInput.value);
        const badLosses = !Number.isInteger(losses) || losses < 0 || losses > 50;
        const badFall = !Number.isFinite(fall) || fall < 0 || fall > 50;
        lossesInput.classList.toggle("invalid", badLosses);
        fallInput.classList.toggle("invalid", badFall);
        if (badLosses || badFall) return;
        this.pauseDraft = null;
        void this.act({ kind: "pause", losses, fall });
      });
      pauseBox.append(el("label", "", t("bot.pauseLosses")), lossesInput,
        el("label", "", t("bot.pauseFall")), fallInput, pauseSave);
      parts.push(pauseBox, el("div", "bot-hint", t("bot.pauseHint")));
    }

    // The owner's brain knob: least chance a signal needs (0 = brain off), or the brain's own ("auto").
    if (s.brain) {
      const own = s.brain.model ? Math.round(s.brain.model.threshold * 100) : null;
      const set = s.rules.brainThreshold;
      const value = this.brainDraft ?? (set != null ? Math.round(set * 100) : own ?? 0);
      const brainBox = el("div", "bot-capital");
      const knob = document.createElement("input");
      knob.type = "range";
      knob.min = "0";
      knob.max = "60";
      knob.step = "1";
      knob.value = String(value);
      knob.dir = "ltr";
      const shown = el("span", "bot-knob-value", `${value}%`);
      knob.addEventListener("input", () => {
        this.brainDraft = Number(knob.value);
        shown.textContent = `${knob.value}%`;
      });
      const brainSave = el("button", "bot-reset", t("bot.save"));
      brainSave.addEventListener("click", () => {
        const pct = Number(knob.value);
        this.brainDraft = null;
        void this.act({ kind: "brain", threshold: pct / 100 });
      });
      const auto = el("button", `bot-reset ${set == null ? "active" : ""}`, t("bot.brainAuto"));
      auto.addEventListener("click", () => {
        this.brainDraft = null;
        void this.act({ kind: "brain", threshold: null });
      });
      brainBox.append(el("label", "", t("bot.brainKnob")), knob, shown, brainSave, auto);
      parts.push(brainBox, el("div", "bot-hint", brainKnobHint(set, own, t)));
    }

    // Rules in one line.
    parts.push(el("div", "bot-hint rules", t("bot.rules", {
      risk: String(s.rules.risk), lev: String(s.rules.maxLeverage),
      pause: pauseRuleText(s.rules, t),
      total: String(s.rules.totalStop),
    })));

    // The bot's memory: experience kept forever (not cleared by "start again").
    if (s.memory) {
      parts.push(heading("memory", t("bot.memory")));
      parts.push(el("div", "bot-hint", t("bot.memoryLine", {
        signals: String(s.memory.signals), ended: String(s.memory.ended), wins: String(s.memory.wins),
        losses: String(s.memory.losses), trades: String(s.memory.trades),
        reliable: String(s.memory.reliable ?? s.memory.signals), history: String(s.memory.history ?? 0),
      })));
    }

    // The bot's brain: the learning filter.
    if (s.brain) {
      parts.push(heading("brain", t("bot.brain")));
      parts.push(el("div", "bot-hint", brainText(s.brain, t)));
      const pre = s.brain.pretrain;
      if (pre && pre.total && (pre.running || pre.done < pre.total)) {
        parts.push(el("div", "bot-hint", t("bot.brain.pretrain", { done: String(pre.done), total: String(pre.total) })));
      }
      if (s.brain.nextTraining) {
        parts.push(el("div", "bot-hint", t("bot.brain.next", { time: formatClock(s.brain.nextTraining * 1000, this.zone).slice(0, 5) })));
      }
    }

    // Connection to the exchange: direct, the computer's proxy, or one typed here (VPN in proxy mode).
    if (this.connection) {
      const c = this.connection;
      parts.push(heading("connection", t("bot.connection")));
      parts.push(el("div", "bot-hint", c.source === "direct" ? t("bot.conn.direct")
        : t(c.source === "app" ? "bot.conn.app" : "bot.conn.system", { proxy: c.proxy ?? "" })));
      const box = el("div", "bot-capital");
      const proxy = document.createElement("input");
      proxy.type = "text";
      proxy.dir = "ltr";
      proxy.placeholder = t("bot.conn.placeholder");
      proxy.value = this.proxyDraft ?? c.typed;
      proxy.addEventListener("input", () => (this.proxyDraft = proxy.value));
      const save = el("button", "bot-reset", t("bot.save"));
      save.addEventListener("click", async () => {
        try {
          this.connection = await this.backend.setConnection(proxy.value);
          this.proxyDraft = null;
        } catch (error) {
          this.error = error instanceof Error ? error.message : String(error);
        }
        this.render();
      });
      box.append(proxy, save);
      parts.push(box, el("div", "bot-hint", t("bot.conn.hint")));
    }

    // The timed look at long positions (owner 2026-11-09): on/off, after how many candles, minutes per timeframe.
    if (s.review) {
      const review = s.review;
      const onOff = el("div", "segmented small");
      for (const on of [true, false]) {
        const b = el("button", review.enabled === on ? "active" : "", t(on ? "bot.ai.on" : "bot.ai.off"));
        b.addEventListener("click", () => {
          if (review.enabled !== on) void this.act({ kind: "review", enabled: on });
        });
        onOff.append(b);
      }
      const box = el("div", "bot-review");
      const field = (value: number, max: number, send: (n: number) => void) => {
        const input = document.createElement("input");
        input.type = "number";
        input.min = "1";
        input.max = String(max);
        input.value = String(value);
        input.dir = "ltr";
        input.addEventListener("change", () => {
          const n = Math.round(Number(input.value));
          if (!(n >= 1 && n <= max)) {
            input.classList.add("invalid");
            return;
          }
          input.classList.remove("invalid");
          send(n);
        });
        return input;
      };
      const after = el("label", "bot-review-row", t("bot.review.after"));
      after.append(field(review.after, 500, (n) => void this.act({ kind: "review", after: n })));
      box.append(after);
      for (const tf of Object.keys(review.every)) {
        const row = el("label", "bot-review-row", t("bot.review.every", { tf }));
        row.append(field(review.every[tf], 1440, (n) => void this.act({ kind: "review", every: { [tf]: n } })));
        box.append(row);
      }
      parts.push(heading("review", t("bot.review.title")), onOff, el("div", "bot-hint", t("bot.review.hint")), box);
    }

    // History test of every strategy on the chart's coin and timeframe (owner 2026-11-09: moved here from
    // the semi-automatic screen, to help choose the strategies). Asked for only while the section is open.
    if (this.target) {
      const key = `${this.target.symbol}|${this.target.timeframe}`;
      parts.push(heading("history", t("bot.history.title", { coin: this.target.symbol.split("/")[0], tf: this.target.timeframe })));
      const got = this.history.get(key);
      if (sectionOpen("history", this.folds) && (!got || Date.now() - got.time > 300_000) && !this.historyLoading.has(key)) {
        void this.loadHistory(this.target.symbol, this.target.timeframe);
      }
      if (!got) {
        parts.push(el("div", "bot-hint", t(this.historyLoading.has(key) ? "bot.history.loading" : "bot.history.none")));
      } else {
        const table = document.createElement("table");
        table.className = "bot-history";
        const head = document.createElement("tr");
        for (const k of ["bot.history.strategy", "bot.history.trades", "bot.history.won", "bot.history.pf", "bot.history.net"] as MessageKey[]) {
          head.append(el("th", "", t(k)));
        }
        table.append(head);
        const used = new Set(s.strategies);
        for (const r of [...got.rows].sort((a, b) => b.stats.netPercent - a.stats.netPercent)) {
          const tr = document.createElement("tr");
          if (used.has(r.strategy)) tr.className = "used";
          const net = r.stats.netPercent;
          tr.append(el("td", "", `${used.has(r.strategy) ? "✓ " : ""}${t(`strat.${r.strategy}` as MessageKey)}`),
            el("td", "", String(r.stats.trades)),
            el("td", "", r.stats.winRate == null ? "–" : `${r.stats.winRate.toFixed(0)}%`),
            el("td", "", r.stats.profitFactor == null ? "–" : r.stats.profitFactor.toFixed(2)),
            el("td", net > 0 ? "up" : net < 0 ? "down" : "", `${net > 0 ? "+" : ""}${net.toFixed(1)}%`));
          table.append(tr);
        }
        parts.push(table, el("div", "bot-hint", t("bot.history.hint", { candles: String(got.candles) })));
      }
    }

    // The bot's diary.
    parts.push(heading("diary", t("bot.diary")));
    const diary = el("ul", "bot-diary");
    for (const e of s.events.slice(0, 12)) {
      const li = el("li", e.kind);
      const time = el("span", "time", formatClock(e.time * 1000, this.zone).slice(0, 5));
      time.dir = "ltr";
      li.append(time, document.createTextNode(` ${eventText(e, t)}`));
      diary.append(li);
    }
    if (!s.events.length) diary.append(el("li", "muted", t("bot.diaryEmpty")));
    parts.push(diary);
    const on: Partial<Record<PanelSection, boolean>> = {
      limit: !!s.limitEntry, ai: !!s.ai?.enabled, tg: !!(s.telegram?.enabled && s.telegram.token),
      lock: !!s.rules.lock?.enabled, review: !!s.review?.enabled,
    };
    const trouble: Partial<Record<PanelSection, boolean>> = { ai: !!s.ai?.lastError && !!s.ai.enabled,
      tg: !!s.telegram?.lastError && !!s.telegram.enabled };
    const summary: Partial<Record<PanelSection, string>> = {
      timeframes: (s.chosenTimeframes ?? []).join(" · "),
      lock: s.rules.lock?.enabled ? `${s.rules.lock.trigger}٪ / ${s.rules.lock.at}٪` : "",
      tg: s.telegram?.token ? t(s.telegram.chat ? "bot.tg.short.on" : "bot.tg.short.noChat") : "",
    };
    panel.replaceChildren(...this.foldSections(parts, on, trouble, summary));
  }

  /** The panel's sections can be opened / closed (owner 2026-11-09). A section with an on/off switch is open
   * while it is on; while off only its title and switch show, ▸ opens it to look. Turning it on opens it.
   * The owner's own open / close choice is kept on this computer; an error opens its section. */
  private foldSections(parts: HTMLElement[], on: Partial<Record<PanelSection, boolean>>,
    trouble: Partial<Record<PanelSection, boolean>>, summary: Partial<Record<PanelSection, string>>): HTMLElement[] {
    const out: HTMLElement[] = [];
    let n = 0;
    while (n < parts.length) {
      const h = parts[n];
      const id = h.dataset.section as PanelSection | undefined;
      if (!id) {
        out.push(h);
        n += 1;
        continue;
      }
      const body: HTMLElement[] = [];
      n += 1;
      while (n < parts.length && !parts[n].dataset.section) body.push(parts[n++]);
      const switched = id in on;
      if (switched && this.wasOn[id] === false && on[id]) delete this.folds[id];   // just turned on: open
      if (switched) this.wasOn[id] = !!on[id];
      const open = trouble[id] || sectionOpen(id, this.folds, on[id]);
      const section = document.createElement("section");
      section.className = `panel-section${open ? " open" : ""}`;
      const head = document.createElement("button");
      head.className = "panel-section-head";
      head.append(Object.assign(document.createElement("span"), { className: "fold", textContent: open ? "▾" : "▸" }),
        Object.assign(document.createElement("span"), { textContent: h.textContent ?? "" }));
      if (!open && summary[id]) head.append(Object.assign(document.createElement("span"), { className: "fold-summary", textContent: summary[id]! }));
      head.addEventListener("click", () => {
        this.folds[id] = !open;
        saveFolds(this.folds);
        this.renderPanel();
      });
      section.append(head);
      // The on/off switch stays in view while the section is closed.
      const toggle = switched ? body.find((e) => e.classList.contains("segmented")) : undefined;
      if (open) section.append(...body);
      else if (toggle) section.append(toggle);
      out.push(section);
    }
    return out;
  }

  private renderTrades(): void {
    const t = this.t.bind(this);
    const s = this.state;
    const box = this.els.trades;
    const title = document.createElement("div");
    title.className = "section-title bot-trades-title";
    title.textContent = t("bot.trades");
    if (s?.positions.length) {
      // Close every open position now and switch the bot off (two presses, like "start again").
      const all = document.createElement("button");
      all.className = `bot-close-all ${this.confirmCloseAll ? "confirm" : ""}`;
      all.textContent = t(this.confirmCloseAll ? "bot.closeAllConfirm" : "bot.closeAll");
      all.addEventListener("click", () => {
        if (!this.confirmCloseAll) {
          this.confirmCloseAll = true;
          this.renderTrades();
          setTimeout(() => {
            this.confirmCloseAll = false;
            this.renderTrades();
          }, 4000);
          return;
        }
        this.confirmCloseAll = false;
        void this.act({ kind: "close-all" });
      });
      title.append(all);
    }
    const table = document.createElement("table");
    table.className = "scanner-table bot-table";
    const head = document.createElement("tr");
    for (const key of ["bot.colState", "scanner.colCoin", "bot.colTf", "strategies.colName", "scanner.colSide", "bot.colEntryType",
      "bot.colMargin", "bot.colLev", "bot.colNotional", "scanner.colEntry", "scanner.colSl", "scanner.colTp", "bot.colPrice",
      "bot.colPnl", "scanner.colTime"] as MessageKey[]) {
      const th = document.createElement("th");
      th.textContent = t(key);
      head.append(th);
    }
    head.append(document.createElement("th")); // close buttons
    const thead = document.createElement("thead");
    thead.append(head);
    const body = document.createElement("tbody");
    const rows: (PaperPosition | PaperTrade)[] = s ? [...[...s.positions].reverse(), ...s.closed] : [];
    for (const p of rows) {
      const closed = "exitPrice" in p && (p as PaperTrade).exitPrice !== undefined;
      const tr = document.createElement("tr");
      // Row colour by result: green profit, red loss, grey break-even (open positions stay plain).
      const outcome = closed ? tradeOutcome(p as PaperTrade) : null;
      tr.className = [outcome ? `result-${outcome}` : "", this.target?.id === p.id ? "active" : ""].join(" ").trim();
      const digits = pricePrecision(p.entryPrice);
      const result = closed ? (p as PaperTrade).pnl : p.openPnl ?? null;
      const cells: [string, string][] = [
        [closed ? t(`bot.reason.${(p as PaperTrade).exitReason}` as MessageKey) : t("bot.open"), closed ? "" : "open-badge"],
        [p.edited ? `${p.base} ✎` : p.base, "coin"],
        [p.timeframe, ""],
        [t(`strat.${p.strategy}` as MessageKey), ""],
        [t(p.side === "long" ? "strategies.long" : "strategies.short"), `side ${p.side}`],
        [t(p.entryType === "limit" ? "bot.entry.limit" : "bot.entry.market"), p.entryType === "limit" ? "entry-limit" : ""],
        [`${p.margin.toFixed(2)}$`, "money"],
        [`×${p.leverage}`, ""],
        [`${p.notional.toFixed(2)}$`, ""],
        [formatPrice(p.entryPrice, digits), ""],
        // After break-even the stop sits at the break-even price: marked with "＝".
        [`${p.lockedAt ? "🔒 " : p.breakevenAt ? "＝ " : ""}${formatPrice(p.stop, digits)}`, p.lockedAt || p.breakevenAt ? "even-stop" : "loss"],
        [formatPrice(p.takeProfit, digits), "up"],
        [formatPrice(closed ? (p as PaperTrade).exitPrice : p.lastPrice ?? null, digits), ""],
        [outcome === "even" ? "0.00" : formatMoney(result),
          outcome ? { win: "up", loss: "loss", even: "" }[outcome] : result === null ? "" : result > 0 ? "up" : result < 0 ? "loss" : ""],
        [formatClock(((closed ? (p as PaperTrade).exitTime : p.entryTime)) * 1000, this.zone).slice(0, 5), ""],
      ];
      for (const [text, cls] of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        td.className = cls;
        if (cls === "coin") {
          const lines = [p.edited ? t("bot.edited") : "", p.trend ? t("bot.coinTrend", { trend: t(`bot.trend.${p.trend}` as MessageKey) }) : "",
            p.btcLink != null ? t(p.btcLink >= 0.2 ? "bot.coinFollower" : "bot.coinIndependent", { corr: p.btcLink.toFixed(2) }) : ""];
          td.title = lines.filter(Boolean).join("\n");
        }
        if (cls === "money") td.title = t("bot.riskAtStop", { usd: (p.risk ?? 0).toFixed(2) });
        if (/^[\d×+−.—]/.test(text)) td.dir = "ltr";
        tr.append(td);
      }
      const action = document.createElement("td");
      if (!closed) {
        const x = document.createElement("button");
        x.className = "bot-close";
        x.textContent = "✕";
        x.title = t("bot.closeOne");
        x.addEventListener("click", (event) => {
          event.stopPropagation(); // not a click on the row
          x.disabled = true;
          void this.act({ kind: "close", position_id: p.id });
        });
        action.append(x);
      }
      tr.append(action);
      tr.addEventListener("click", () => {
        this.pinned = true;
        void this.showChart({ symbol: p.symbol, timeframe: p.timeframe, id: p.id });
      });
      body.append(tr);
    }
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 12;
      td.className = "scanner-empty";
      td.textContent = t("bot.noTrades");
      tr.append(td);
      body.append(tr);
    }
    table.append(thead, body);
    const scroll = document.createElement("div");
    scroll.className = "scanner-box";
    scroll.append(table);
    // The table is rebuilt on every refresh: keep the owner's scroll place (it jumped to the top).
    const old = box.querySelector<HTMLElement>(".scanner-box");
    const top = old?.scrollTop ?? 0;
    const left = old?.scrollLeft ?? 0;
    box.replaceChildren(title, scroll);
    scroll.scrollTop = top;
    scroll.scrollLeft = left;
  }
}

