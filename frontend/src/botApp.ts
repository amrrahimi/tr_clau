// The automatic screen (owner's design): the bot does everything. A chart,
// the bot panel (start/stop, virtual money, results) and the bot's trades.
// The bot itself runs in the backend; this screen only shows it and sends
// the button presses.

import { BackendError, type Backend, type BotAccount, type LiveConnection, type PaperAction } from "./api.ts";
import { applyLiveCandle, pricePrecision } from "./candles.ts";
import { ChartView } from "./chart.ts";
import { adviceText, brainText, defaultTarget, eventText, formatMoney, paperAsTrade, statusKey, tradeOutcome } from "./botView.ts";
import { formatClock, formatPrice } from "./format.ts";
import { direction, loadLanguage, saveLanguage, translate, type Language } from "./i18n.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import { loadZone } from "./timezone.ts";
import type { Candle, ConnectionState, PaperPosition, PaperState, PaperTrade, StrategyCard } from "./types.ts";

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
  private capDraft: string | null = null;
  private proxyDraft: string | null = null;
  private confirmCloseAll = false;
  private failures = 0; // polls in a row without an answer from the engine
  private account: BotAccount = "main"; // which virtual account the screen shows
  private connection: ConnectionState | null = null;
  private polls = 0;
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
    try {
      const account = this.account;
      const state = await this.backend.getPaper(account);
      if (account !== this.account) return; // the owner switched accounts meanwhile
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
    const typing = document.activeElement instanceof HTMLInputElement && this.els.panel.contains(document.activeElement);
    if (!typing) this.renderPanel();
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
      this.state = await this.backend.paperAction(action, this.account);
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
    // Two accounts: the main bot, and the owner's high-risk test account (its own virtual money).
    const accounts = el("div", "segmented small bot-accounts");
    for (const account of ["main", "fast"] as const) {
      const b = el("button", this.account === account ? "active" : "", t(account === "main" ? "bot.account.main" : "bot.account.fast"));
      b.addEventListener("click", () => {
        if (this.account === account) return;
        this.account = account;
        this.state = null;
        this.pinned = false;
        this.capDraft = null;
        this.capitalDraft = null;
        this.render();
        void this.refresh();
      });
      accounts.append(b);
    }
    parts.push(accounts);
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
    // What happened to the signals lately (most useful for the barrage account).
    if (s.flow) {
      parts.push(el("div", "bot-hint", t("bot.flow", { seen: String(s.flow.seen), opened: String(s.flow.opened) })));
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
          const next = s.timeframes.filter((x) => (x === tf ? box.checked : chosen.includes(x)));
          if (!next.length) {
            box.checked = true; // at least one
            return;
          }
          void this.act({ kind: "timeframes", timeframes: next });
        });
        const name = el("span", "", tf);
        name.dir = "ltr";
        line.append(box, name);
        list.append(line);
      }
      parts.push(el("div", "list-heading", t("bot.timeframes")), list, el("div", "bot-hint", t("bot.timeframesHint")));
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
      parts.push(el("div", "bot-hint", t("bot.autoHint", { tfs: (s.chosenTimeframes ?? s.timeframes).join("، ") })));
    }
    if (s.profile === "fast") {
      parts.push(el("div", "bot-hint warn", t("bot.fastHint", { cap: String(s.rules.profitCap ?? 0.05) })));
    } else if (s.rules.strictTrades) {
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

    // Rules in one line.
    parts.push(el("div", "bot-hint rules", t("bot.rules", {
      risk: String(s.rules.risk), open: String(s.rules.maxOpen), fast: String(s.rules.maxFast ?? 3),
      slow: String(s.rules.maxSlow ?? 3), side: String(s.rules.maxSameSide ?? 4), lev: String(s.rules.maxLeverage),
      losses: String(s.rules.pauseLosses ?? 4), fall: String(s.rules.pauseFall ?? 5),
      hours: String(s.rules.pauseHours ?? 3), total: String(s.rules.totalStop), wins: String(s.rules.recoverWins ?? 2),
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
    for (const key of ["bot.colState", "scanner.colCoin", "bot.colTf", "strategies.colName", "scanner.colSide", "bot.colLev",
      "scanner.colEntry", "scanner.colSl", "scanner.colTp", "bot.colPrice", "bot.colPnl", "scanner.colTime"] as MessageKey[]) {
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
        [p.base, "coin"],
        [p.timeframe, ""],
        [t(`strat.${p.strategy}` as MessageKey), ""],
        [t(p.side === "long" ? "strategies.long" : "strategies.short"), `side ${p.side}`],
        [`×${p.leverage}`, ""],
        [formatPrice(p.entryPrice, digits), ""],
        // After break-even the stop sits at the break-even price: marked with "＝".
        [`${p.breakevenAt ? "＝ " : ""}${formatPrice(p.stop, digits)}`, p.breakevenAt ? "even-stop" : "loss"],
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
    box.replaceChildren(title, scroll);
  }
}
