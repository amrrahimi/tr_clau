// The scanner under the chart (always open, the owner's choice): every
// strategy on every coin of the top-100 list. Three tables: max profit and
// cautious (from the history) and the latest signals. The history tables and
// the signals each have their own Start / Stop (owner's choice); a scan runs
// while either is on. Clicking a row opens that coin with that strategy.

import { pricePrecision } from "./candles.ts";
import { formatClock, formatPrice } from "./format.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import type { ZoneId } from "./timezone.ts";
import type { ScanEntry, ScanResult, ScanSignal } from "./types.ts";

export interface ScannerHost {
  t(key: MessageKey, params?: Record<string, string>): string;
  zone(): ZoneId;
  /** Open this coin's chart with this strategy on (manual). */
  open(symbol: string, strategy: string): void;
  /** A Start / Stop button was pressed. */
  onToggle(): void;
}

export interface ScannerSwitches {
  history: boolean;
  signals: boolean;
}

const STORAGE_KEY = "trading-bot.scanner";

export function loadSwitches(storage: Pick<Storage, "getItem"> | null = safeStorage()): ScannerSwitches {
  try {
    const data = JSON.parse(storage?.getItem(STORAGE_KEY) ?? "{}") as Partial<ScannerSwitches>;
    return { history: data.history === true, signals: data.signals === true };
  } catch {
    return { history: false, signals: false };
  }
}

function saveSwitches(value: ScannerSwitches): void {
  try {
    safeStorage()?.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // not remembered
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export class ScannerPanel {
  private result: ScanResult | null = null;
  private error = false;
  private switches: ScannerSwitches = loadSwitches();

  constructor(private readonly host: ScannerHost, private readonly root: HTMLElement) {}

  /** True while at least one part is started: then the app keeps scanning. */
  get active(): boolean {
    return this.switches.history || this.switches.signals;
  }

  show(result: ScanResult | null): void {
    this.result = result;
    this.error = false;
    this.render();
  }

  setError(): void {
    this.error = true;
    this.render();
  }

  private toggle(part: keyof ScannerSwitches): void {
    this.switches = { ...this.switches, [part]: !this.switches[part] };
    saveSwitches(this.switches);
    this.render();
    this.host.onToggle();
  }

  render(): void {
    const t = this.host.t;
    const r = this.result;
    const head = document.createElement("div");
    head.className = "scanner-head";
    const title = document.createElement("span");
    title.className = "section-title";
    title.textContent = t("scanner.title");
    const status = document.createElement("span");
    status.className = "scanner-status";
    if (!this.active) status.textContent = t("scanner.stopped");
    else if (this.error) status.textContent = t("scanner.error");
    else if (!r) status.textContent = t("scanner.waiting");
    else if (r.running) {
      status.textContent = t("scanner.progress", { done: String(r.done), total: String(r.total || "…") });
      const bar = document.createElement("span");
      bar.className = "scanner-bar";
      const fill = document.createElement("span");
      fill.style.width = `${r.total ? (r.done / r.total) * 100 : 0}%`;
      bar.append(fill);
      status.append(bar);
    } else {
      status.textContent = t("scanner.done", {
        total: String(r.total),
        time: r.finishedAt ? formatClock(r.finishedAt * 1000, this.host.zone()) : "—",
      });
      if (r.failed.length) status.textContent += ` · ${t("scanner.failed", { coins: r.failed.join(", ") })}`;
    }
    head.append(title, status);

    const tables = document.createElement("div");
    tables.className = "scanner-tables";
    const history = document.createElement("div");
    history.className = "scanner-part" + (this.switches.history ? "" : " paused");
    history.append(
      this.partHead("scanner.history", "history"),
      this.twoTables(r),
    );
    const signals = document.createElement("div");
    signals.className = "scanner-part signals" + (this.switches.signals ? "" : " paused");
    signals.append(this.partHead("scanner.signals", "signals"), this.signalsTable(r?.signals ?? []));
    tables.append(history, signals);

    const note = document.createElement("div");
    note.className = "strategy-note";
    note.textContent = t("scanner.note");
    this.root.replaceChildren(head, tables, note);
  }

  /** Title of a part with its Start / Stop button. */
  private partHead(titleKey: MessageKey, part: keyof ScannerSwitches): HTMLElement {
    const t = this.host.t;
    const row = document.createElement("div");
    row.className = "scanner-part-head";
    const title = document.createElement("span");
    title.className = "scanner-table-title";
    title.textContent = t(titleKey);
    if (part === "signals") title.title = t("scanner.signalsHint");
    const on = this.switches[part];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "scanner-switch" + (on ? " on" : "");
    button.textContent = on ? t("scanner.stop") : t("scanner.start");
    button.addEventListener("click", () => this.toggle(part));
    row.append(title, button);
    return row;
  }

  private twoTables(r: ScanResult | null): HTMLElement {
    const box = document.createElement("div");
    box.className = "scanner-pair";
    box.append(
      this.table("scanner.maxProfit", "scanner.maxProfitHint", r?.maxProfit ?? []),
      this.table("scanner.cautious", "scanner.cautiousHint", r?.cautious ?? []),
    );
    return box;
  }

  private header(keys: [MessageKey, string][]): HTMLTableSectionElement {
    const head = document.createElement("tr");
    for (const [key, cls] of keys) {
      const th = document.createElement("th");
      th.className = cls;
      th.textContent = this.host.t(key);
      head.append(th);
    }
    const thead = document.createElement("thead");
    thead.append(head);
    return thead;
  }

  private cell(text: string, cls: string, ltr = false): HTMLTableCellElement {
    const td = document.createElement("td");
    td.className = cls;
    if (ltr) td.dir = "ltr";
    td.textContent = text;
    return td;
  }

  private emptyRow(columns: number, key: MessageKey): HTMLTableRowElement {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = columns;
    td.className = "scanner-empty";
    td.textContent = this.result && !this.result.running ? this.host.t(key) : "";
    tr.append(td);
    return tr;
  }

  private table(titleKey: MessageKey, hintKey: MessageKey, rows: ScanEntry[]): HTMLElement {
    const t = this.host.t;
    const box = document.createElement("div");
    box.className = "scanner-box";
    const title = document.createElement("div");
    title.className = "scanner-table-title";
    title.textContent = t(titleKey);
    title.title = t(hintKey);
    const table = document.createElement("table");
    table.className = "scanner-table";
    const body = document.createElement("tbody");
    for (const e of rows) {
      const tr = document.createElement("tr");
      tr.title = t("scanner.openHint");
      const pf = e.stats.profitFactor === null ? "∞" : e.stats.profitFactor.toFixed(2);
      tr.append(
        this.cell(e.base, "name coin"),
        this.cell(t(`strat.${e.strategy}` as MessageKey), "name"),
        this.cell(formatPercent(e.stats.netPercent), "num up", true),
        this.cell(String(e.stats.trades), "num", true),
        this.cell(pf, "num", true),
      );
      tr.addEventListener("click", () => this.host.open(e.symbol, e.strategy));
      body.append(tr);
    }
    if (!rows.length) body.append(this.emptyRow(5, "scanner.empty"));
    table.append(this.header([
      ["scanner.colCoin", "name"], ["strategies.colName", "name"], ["strategies.colNet", "num"],
      ["strategies.colTrades", "num"], ["scanner.colPf", "num"],
    ]), body);
    box.append(title, table);
    return box;
  }

  /** Latest signals, newest first; reliable ones bright, the rest dimmed. */
  private signalsTable(rows: ScanSignal[]): HTMLElement {
    const t = this.host.t;
    const box = document.createElement("div");
    box.className = "scanner-box";
    const table = document.createElement("table");
    table.className = "scanner-table";
    const body = document.createElement("tbody");
    for (const e of rows) {
      const s = e.signal;
      const digits = pricePrecision(s.entry);
      const tr = document.createElement("tr");
      tr.className = e.reliable ? "reliable" : "weak";
      tr.title = `${t(e.reliable ? "scanner.reliable" : "scanner.unreliable")}\n${t("scanner.openHint")}`;
      tr.append(
        this.cell(formatClock(s.time * 1000, this.host.zone()).slice(0, 5), "num", true),
        this.cell(e.base, "name coin"),
        this.cell(t(`strat.${e.strategy}` as MessageKey), "name"),
        this.cell(t(s.side === "long" ? "strategies.long" : "strategies.short"), `side ${s.side}`),
        this.cell(formatPrice(s.entry, digits), "num", true),
        this.cell(formatPrice(s.stopLoss, digits), "num loss", true),
        this.cell(formatPrice(s.takeProfit, digits), "num up", true),
        this.cell(e.stats.winRate == null ? "—" : `${e.stats.winRate.toFixed(0)}%`, "num", true),
        this.cell(String(e.stats.trades), "num", true),
      );
      tr.addEventListener("click", () => this.host.open(e.symbol, e.strategy));
      body.append(tr);
    }
    if (!rows.length) body.append(this.emptyRow(9, "scanner.noSignals"));
    table.append(this.header([
      ["scanner.colTime", "num"], ["scanner.colCoin", "name"], ["strategies.colName", "name"],
      ["scanner.colSide", "name"], ["scanner.colEntry", "num"], ["scanner.colSl", "num"],
      ["scanner.colTp", "num"], ["scanner.colWin", "num"], ["strategies.colTrades", "num"],
    ]), body);
    box.append(table);
    return box;
  }
}
