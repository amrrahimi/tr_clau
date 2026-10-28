// The scanner under the chart (always open, the owner's choice): every
// strategy on every coin of the list, as two top-10 tables. Clicking a row
// opens that coin with that strategy.

import { formatClock } from "./format.ts";
import type { MessageKey } from "./locales/en.ts";
import { formatPercent } from "./strategyState.ts";
import type { ZoneId } from "./timezone.ts";
import type { ScanEntry, ScanResult } from "./types.ts";

export interface ScannerHost {
  t(key: MessageKey, params?: Record<string, string>): string;
  zone(): ZoneId;
  /** Open this coin's chart with this strategy on (manual). */
  open(symbol: string, strategy: string): void;
}

export class ScannerPanel {
  private result: ScanResult | null = null;
  private error = false;

  constructor(private readonly host: ScannerHost, private readonly root: HTMLElement) {}

  show(result: ScanResult | null): void {
    this.result = result;
    this.error = false;
    this.render();
  }

  setError(): void {
    this.error = true;
    this.render();
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
    if (this.error) status.textContent = t("scanner.error");
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
    tables.append(
      this.table("scanner.maxProfit", "scanner.maxProfitHint", r?.maxProfit ?? []),
      this.table("scanner.cautious", "scanner.cautiousHint", r?.cautious ?? []),
    );
    const note = document.createElement("div");
    note.className = "strategy-note";
    note.textContent = t("scanner.note");
    this.root.replaceChildren(head, tables, note);
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
    const head = document.createElement("tr");
    for (const [key, cls] of [
      ["scanner.colCoin", "name"], ["strategies.colName", "name"], ["strategies.colNet", "num"],
      ["strategies.colTrades", "num"], ["scanner.colPf", "num"],
    ] as const) {
      const th = document.createElement("th");
      th.className = cls;
      th.textContent = t(key);
      head.append(th);
    }
    const thead = document.createElement("thead");
    thead.append(head);
    const body = document.createElement("tbody");
    for (const e of rows) {
      const tr = document.createElement("tr");
      tr.title = t("scanner.openHint");
      const pf = e.stats.profitFactor === null ? "∞" : e.stats.profitFactor.toFixed(2);
      const cells: [string, string, boolean][] = [
        [e.base, "name coin", false],
        [t(`strat.${e.strategy}` as MessageKey), "name", false],
        [formatPercent(e.stats.netPercent), "num up", true],
        [String(e.stats.trades), "num", true],
        [pf, "num", true],
      ];
      for (const [text, cls, ltr] of cells) {
        const td = document.createElement("td");
        td.className = cls;
        if (ltr) td.dir = "ltr";
        td.textContent = text;
        tr.append(td);
      }
      tr.addEventListener("click", () => this.host.open(e.symbol, e.strategy));
      body.append(tr);
    }
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "scanner-empty";
      td.textContent = this.result && !this.result.running ? t("scanner.empty") : "";
      tr.append(td);
      body.append(tr);
    }
    table.append(thead, body);
    box.append(title, table);
    return box;
  }
}
