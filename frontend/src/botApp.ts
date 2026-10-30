// The automatic screen (owner's design): the bot does everything. A chart,
// the bot panel (start/stop, virtual money, results) and the bot's trades.
// The bot itself runs in the backend; this screen only shows it and sends
// the button presses.

import { BackendError, type Backend, type LiveConnection, type PaperAction } from "./api.ts";
import { applyLiveCandle, pricePrecision } from "./candles.ts";
import { ChartView } from "./chart.ts";
import { defaultTarget, eventText, formatMoney, paperAsTrade, statusKey } from "./botView.ts";
import { formatClock, formatPrice } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import { loadZone } from "./timezone.ts";
import type { Candle, PaperPosition, PaperState, PaperTrade, StrategyCard } from "./types.ts";

const POLL_MS = 5000;

export type View = "auto" | "semi";

export class BotApp {
  private language: Language = loadLanguage();
  private zone = loadZone();
  private state: PaperState | null = null;
  private cards: StrategyCard[] = [];
  private chart!: ChartView;
  private els!: Record<string, HTMLElement>;
  private target: { symbol: string; timeframe: string; id: number | null } | null = null;
  private pinned = false; // the owner clicked a trade: keep showing it
  private candles: Candle[] = [];
  private live: LiveConnection | null = null;
  private chartId = 0;
  private confirmReset = false;
  private capitalDraft: string | null = null; // what the owner typed, kept across redraws
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
    setInterval(() => void this.refresh(), POLL_MS);
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
  }

  // ---------- data ----------

  private async refresh(): Promise<void> {
    try {
      this.state = await this.backend.getPaper();
      this.error = null;
    } catch (error) {
      this.error = error instanceof BackendError && error.unreachable ? this.t("error.backendUnreachable")
        : this.t("error.generic", { detail: error instanceof Error ? error.message : String(error) });
    }
    this.followBot();
    this.drawTrades();
    this.render();
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
    try {
      this.state = await this.backend.paperAction(action);
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
  }

  // ---------- screen ----------

  private render(): void {
    this.els.error.hidden = !this.error;
    if (this.error) this.els.errorText.textContent = this.error;
    this.renderTitle();
    // Do not redraw the panel while the owner is typing the amount of money.
    const typing = document.activeElement instanceof HTMLInputElement && this.els.panel.contains(document.activeElement);
    if (!typing) this.renderPanel();
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
    parts.push(el("div", `bot-status ${s.status}`, t(statusKey(s), {
      tf: s.scanning ?? "",
      until: s.pausedUntil ? formatClock(s.pausedUntil * 1000, this.zone).slice(0, 5) : "",
      reason: s.pauseReason ? t(s.pauseReason === "streak" ? "bot.pause.streak" : "bot.pause.fall") : "",
    })));
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
      const kinds = this.cards.length ? this.cards.map((c) => c.type) : s.strategies;
      for (const kind of kinds) {
        const line = el("label", "");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = s.strategies.includes(kind);
        box.addEventListener("change", () => {
          const chosen = kinds.filter((k) => (k === kind ? box.checked : s.strategies.includes(k)));
          if (!chosen.length) {
            box.checked = true; // at least one
            return;
          }
          void this.act({ kind: "mode", mode: "manual", strategies: chosen });
        });
        line.append(box, document.createTextNode(` ${t(`strat.${kind}` as MessageKey)}`));
        list.append(line);
      }
      parts.push(list);
    } else {
      parts.push(el("div", "bot-hint", t("bot.autoHint", { tfs: s.timeframes.join("، ") })));
    }

    // Rules in one line.
    parts.push(el("div", "bot-hint rules", t("bot.rules", {
      risk: String(s.rules.risk), open: String(s.rules.maxOpen), fast: String(s.rules.maxFast ?? 3),
      slow: String(s.rules.maxSlow ?? 3), side: String(s.rules.maxSameSide ?? 4), lev: String(s.rules.maxLeverage),
      losses: String(s.rules.pauseLosses ?? 4), fall: String(s.rules.pauseFall ?? 5),
      hours: String(s.rules.pauseHours ?? 3), total: String(s.rules.totalStop),
    })));

    // The bot's memory: experience kept forever (not cleared by "start again").
    if (s.memory) {
      parts.push(el("div", "list-heading", t("bot.memory")));
      parts.push(el("div", "bot-hint", t("bot.memoryLine", {
        signals: String(s.memory.signals), ended: String(s.memory.ended), wins: String(s.memory.wins),
        losses: String(s.memory.losses), trades: String(s.memory.trades),
      })));
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
    title.className = "section-title";
    title.textContent = t("bot.trades");
    const table = document.createElement("table");
    table.className = "scanner-table bot-table";
    const head = document.createElement("tr");
    for (const key of ["bot.colState", "scanner.colCoin", "bot.colTf", "strategies.colName", "scanner.colSide", "bot.colLev",
      "scanner.colEntry", "scanner.colSl", "scanner.colTp", "bot.colPrice", "bot.colPnl", "scanner.colTime"] as MessageKey[]) {
      const th = document.createElement("th");
      th.textContent = t(key);
      head.append(th);
    }
    const thead = document.createElement("thead");
    thead.append(head);
    const body = document.createElement("tbody");
    const rows: (PaperPosition | PaperTrade)[] = s ? [...[...s.positions].reverse(), ...s.closed] : [];
    for (const p of rows) {
      const closed = "exitPrice" in p && (p as PaperTrade).exitPrice !== undefined;
      const tr = document.createElement("tr");
      if (this.target?.id === p.id) tr.className = "active";
      const digits = pricePrecision(p.entryPrice);
      const result = closed ? (p as PaperTrade).pnl : p.openPnl ?? null;
      const cells: [string, string][] = [
        [closed ? t(`bot.reason.${(p as PaperTrade).exitReason}` as MessageKey) : t("bot.open"), closed ? "" : "open-badge"],
        [p.base, "coin"],
        [p.timeframe, ""],
        [t(`strat.${p.strategy}` as MessageKey), ""],
        [t(p.side === "long" ? "strategies.long" : "strategies.short"), `side ${p.side}`],
        [`×${p.leverage}`, ""],
        [formatPrice(p.entryPrice, digits), ""],
        [formatPrice(p.stop, digits), "loss"],
        [formatPrice(p.takeProfit, digits), "up"],
        [formatPrice(closed ? (p as PaperTrade).exitPrice : p.lastPrice ?? null, digits), ""],
        [formatMoney(result), result === null ? "" : result > 0 ? "up" : result < 0 ? "loss" : ""],
        [formatClock(((closed ? (p as PaperTrade).exitTime : p.entryTime)) * 1000, this.zone).slice(0, 5), ""],
      ];
      for (const [text, cls] of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        td.className = cls;
        if (/^[\d×+−.—]/.test(text)) td.dir = "ltr";
        tr.append(td);
      }
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
    box.replaceChildren(title, scroll);
  }
}
