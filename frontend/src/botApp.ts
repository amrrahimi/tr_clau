// The automatic screen (owner's design): the bot does everything. A chart,
// the bot panel (start/stop, virtual money, results) and the bot's trades.
// The bot itself runs in the backend; this screen only shows it and sends
// the button presses.

import { BackendError, type Backend, type LiveConnection, type PaperAction } from "./api.ts";
import { applyLiveCandle, pricePrecision } from "./candles.ts";
import { ChartView, THEME, type Level } from "./chart.ts";
import { adviceText, brainKnobHint, brainText, breakevenTrigger, formatR, lockTrigger, lockValid, timeLeft, toggled, typingField, levelProblem, resultAt, defaultTarget, eventText, formatMoney, paperAsTrade, pauseRuleText, statusKey, strategyOrder, timeframesOf, tradeOutcome } from "./botView.ts";
import { formatClock, formatPrice } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import { loadZone } from "./timezone.ts";
import type { Candle, ConnectionState, MarketInfo, PaperPosition, PaperState, PaperTrade, StrategyCard, StrategyResults } from "./types.ts";

const POLL_MS = 5000;

export type View = "auto" | "semi";

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
    try {
      this.cards = await this.backend.getStrategyCatalog();
    } catch {
      // the panel still works; manual strategy names come later
    }
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
          <div class="spacer"></div>
          <button class="lang-button" data-el="language"></button>
        </header>
        <div class="error-banner" data-el="error" hidden><span data-el="errorText"></span></div>
        <main class="body">
          <aside class="bot-panel" data-el="panel"></aside>
          <div class="chart-column">
            <section class="chart-area" dir="ltr">
              <div class="chart" data-el="chart"></div>
              <div class="chart-message" data-el="chartMessage" hidden></div>
            </section>
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
    this.els.title.textContent = this.t("app.title");
    this.els.language.textContent = this.t("language.switch");
    this.els.language.title = this.t("language.switchLabel");
    this.els.view.replaceChildren(...(["auto", "semi"] as View[]).map((v) => {
      const b = document.createElement("button");
      b.textContent = this.t(v === "auto" ? "view.auto" : "view.semi");
      b.className = v === "auto" ? "active" : "";
      if (v === "semi") b.addEventListener("click", () => this.onSwitch("semi"));
      return b;
    }));
    this.render();
    this.drawTrades(); // labels on the chart follow the language too
  }

  // ---------- data ----------

  private async refresh(): Promise<void> {
    const asked = this.actions;
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
  private drawTrades(): void {
    if (!this.state || !this.target || !this.candles.length) return;
    const same = (p: PaperPosition) => p.symbol === this.target!.symbol && p.timeframe === this.target!.timeframe;
    const first = this.candles[0].time;
    const trades = [...this.state.closed.filter(same), ...this.state.positions.filter(same)]
      .filter((p) => p.entryCandle >= first)
      .map(paperAsTrade)
      .sort((a, b) => a.entryTime - b.entryTime);
    this.chart.setTrades(trades, this.candles[this.candles.length - 1].time,
      { long: this.t("strategies.long"), short: this.t("strategies.short") });
    // Open positions of this chart: entry, liquidation, break-even trigger, and the stop-loss and
    // take-profit lines, which the owner can drag with the mouse (takes effect when let go).
    // Waiting limit orders: dashed, not draggable (the test compares the bot's own limit rule).
    const orders = (this.state.orders ?? []).filter((o) => o.symbol === this.target!.symbol && o.timeframe === this.target!.timeframe);
    this.chart.setLevels([
      ...this.state.positions.filter(same).flatMap((p) => this.positionLevels(p)),
      ...orders.flatMap((o): Level[] => [
        { key: `o${o.id}`, price: o.price, color: "#2962ff", title: this.t("bot.level.order"), style: "dashed" },
        { key: `os${o.id}`, price: o.stopLoss, color: THEME.down, title: this.t("bot.level.orderStop"), style: "dashed" },
        { key: `ot${o.id}`, price: o.takeProfit, color: THEME.up, title: this.t("bot.level.orderTarget"), style: "dashed" },
      ]),
    ]);
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
        if (kind === "target") {   // the break-even and profit-lock points follow the target
          const even = breakevenTrigger(p, price);
          if (even !== null) others[`b${p.id}`] = { price: even, title: evenTitle };
          const lock = lockTrigger(p, this.state?.rules.lock, price);
          if (lock !== null) others[`k${p.id}`] = { price: lock, title: lockTitle };
        }
        return { title: label(kind, price), others };
      },
      onDrop: (price: number) => void this.moveLevel(p, kind, Number(price.toFixed(digits))),
    });
    const levels: Level[] = [
      { key: `e${p.id}`, price: p.entryPrice, color: "#2962ff", title: this.t("bot.level.entrySized", {
        kind: this.t(p.entryType === "limit" ? "bot.entry.limit" : "bot.entry.market"),
        margin: p.margin.toFixed(2), lev: String(p.leverage) }) },
      { key: `l${p.id}`, price: p.liquidation, color: "#ff9800", title: this.t("bot.level.liquidation"), style: "dashed" },
      { key: `s${p.id}`, price: p.stop, color: THEME.down, title: label("stop", p.stop), drag: drag("stop") },
      { key: `t${p.id}`, price: p.takeProfit, color: THEME.up, title: label("target", p.takeProfit), drag: drag("target") },
    ];
    const trigger = breakevenTrigger(p);
    if (trigger !== null) levels.push({ key: `b${p.id}`, price: trigger, color: "#787b86", title: evenTitle, style: "dashed" });
    const lock = lockTrigger(p, this.state!.rules.lock);
    if (lock !== null) levels.push({ key: `k${p.id}`, price: lock, color: "#b388ff", title: lockTitle, style: "dashed" });
    return levels;
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
  }

  private renderTitle(): void {
    if (!this.target) return;
    this.els.chartTitle.textContent = `${this.target.symbol.split(":")[0]} · ${this.target.timeframe}`;
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
    row("bot.winRate", s.stats.winRate === null ? "—" : `${s.stats.winRate.toFixed(0)}% (${s.stats.wins}/${s.stats.trades})`);
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
      parts.push(el("div", "list-heading", t("bot.timeframes")), list, el("div", "bot-hint", t("bot.timeframesHint")));
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
      parts.push(el("div", "list-heading", t("bot.limit.title")), onOff, el("div", "bot-hint", t("bot.limit.hint", {
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
      parts.push(el("div", "list-heading", t("bot.ai.title")), onOff);
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
      parts.push(el("div", "list-heading", t("bot.coins.title")), modes);
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
    parts.push(el("div", "list-heading", t("bot.strategies")), modes);
    if (s.mode === "manual") {
      const list = el("div", "bot-strategies");
      const stats = s.strategyStats ?? {};
      const onTf = timeframesOf(s.botStrategies ?? {});
      const all = this.cards.length ? this.cards.map((c) => c.type) : s.strategies;
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
      parts.push(el("div", "list-heading", t("bot.lock.title")), onOff, box,
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
      parts.push(el("div", "list-heading", t("bot.memory")));
      parts.push(el("div", "bot-hint", t("bot.memoryLine", {
        signals: String(s.memory.signals), ended: String(s.memory.ended), wins: String(s.memory.wins),
        losses: String(s.memory.losses), trades: String(s.memory.trades),
        reliable: String(s.memory.reliable ?? s.memory.signals), history: String(s.memory.history ?? 0),
      })));
    }

    // The bot's brain: the learning filter.
    if (s.brain) {
      parts.push(el("div", "list-heading", t("bot.brain")));
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
      parts.push(el("div", "list-heading", t("bot.connection")));
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

    // The bot's diary.
    parts.push(el("div", "list-heading", t("bot.diary")));
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
    panel.replaceChildren(...parts);
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
        if (cls === "coin" && p.edited) td.title = t("bot.edited");
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

