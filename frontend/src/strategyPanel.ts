// The strategies table under the coin list (the owner's design): every
// strategy with its result on the current chart. Clicking a row turns that
// strategy on (its trades are drawn on the chart); clicking again turns it off.
// Only one strategy is on at a time. ⚙ opens its rules and settings.

import { validFee, type FeeRates } from "./fees.ts";
import { invalidParams } from "./indicatorList.ts";
import type { MessageKey } from "./locales/en.ts";
import {
  cleanStrategyState,
  defaultValue,
  effectiveParams,
  formatPercent,
  loadStrategyState,
  saveStrategyState,
  setAuto,
  setParams,
  toggleActive,
  type AutoRule,
  type StrategyState,
} from "./strategyState.ts";
import type { MarketType, Mode, ParamSpec, StrategyCard, StrategyOverview, StrategyRow } from "./types.ts";

/** Settings every strategy has (the extra rules); shown under their own heading. */
const COMMON = new Set(["state_filter", "breakeven", "max_candles"]);

/** A 0/1 setting is shown as a tick box. */
function isSwitch(p: ParamSpec): boolean {
  return p.min === 0 && p.max === 1 && p.step === 1;
}

export interface StrategyHost {
  t(key: MessageKey, params?: Record<string, string>): string;
  mode(): Mode;
  openWindow(content: HTMLElement): void;
  closeWindow(): void;
  /** The active strategy or a setting changed: ask the backend again. */
  onChange(): void;
  /** Fee rates for the current market type (null until the backend's defaults arrived). */
  fees(): { market: MarketType; rates: FeeRates | null; defaults: FeeRates | null };
  saveFees(rates: FeeRates): void;
}

export class StrategyPanel {
  private cards: StrategyCard[] = [];
  private state: StrategyState = loadStrategyState();
  private overview: StrategyOverview | null = null;
  private status: "idle" | "loading" | "error" = "idle";

  constructor(private readonly host: StrategyHost, private readonly root: HTMLElement) {}

  setCatalog(cards: StrategyCard[]): void {
    this.cards = cards;
    this.state = cleanStrategyState(this.state, cards);
    this.render();
  }

  /** Automatic: the bot picks with this rule; null = manual. */
  get autoRule(): AutoRule | null {
    return this.state.auto ? this.state.rule : null;
  }

  get active(): string | null {
    return this.state.active;
  }

  /** Only the settings the user changed (the backend fills in the rest). */
  get settings(): StrategyState["settings"] {
    return this.state.settings;
  }

  setLoading(): void {
    this.status = "loading";
    this.render();
  }

  setError(): void {
    this.status = "error";
    this.render();
  }

  showOverview(overview: StrategyOverview | null): void {
    this.overview = overview;
    this.status = "idle";
    this.render();
  }

  private name(type: string): string {
    return this.host.t(`strat.${type}` as MessageKey);
  }

  private update(state: StrategyState): void {
    this.state = state;
    saveStrategyState(state);
    this.render();
    this.host.onChange();
  }

  render(): void {
    const t = this.host.t;
    const title = document.createElement("div");
    title.className = "section-title";
    title.textContent = t("strategies.title");

    // Auto / Manual, and in Auto the way the bot picks.
    const controls = document.createElement("div");
    controls.className = "strategy-controls";
    const segmented = (items: { label: string; active: boolean; title?: string; onClick: () => void }[]) => {
      const box = document.createElement("div");
      box.className = "segmented small";
      for (const item of items) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = item.label;
        b.className = item.active ? "active" : "";
        if (item.title) b.title = item.title;
        b.addEventListener("click", item.onClick);
        box.append(b);
      }
      return box;
    };
    const lastChoice = this.overview?.choice?.strategy ?? null;
    controls.append(segmented([
      { label: t("settings.auto"), active: this.state.auto, title: t("strategies.autoHint"),
        onClick: () => !this.state.auto && this.update(setAuto(this.state, true, lastChoice)) },
      { label: t("settings.manual"), active: !this.state.auto,
        onClick: () => this.state.auto && this.update(setAuto(this.state, false, lastChoice)) },
    ]));
    if (this.state.auto) {
      const rules: [AutoRule, MessageKey, MessageKey][] = [
        ["cautious", "strategies.cautious", "strategies.cautiousHint"],
        ["max_profit", "strategies.maxProfit", "strategies.maxProfitHint"],
      ];
      controls.append(segmented(rules.map(([rule, label, hint]) => ({
        label: t(label), active: this.state.rule === rule, title: t(hint),
        onClick: () => this.state.rule !== rule && this.update({ ...this.state, rule }),
      }))));
    }

    const table = document.createElement("table");
    table.className = "strategy-table";
    const head = document.createElement("tr");
    for (const [key, cls] of [
      ["strategies.colName", "name"], ["strategies.colTrades", "num"], ["strategies.colWins", "num win"],
      ["strategies.colLosses", "num loss"], ["strategies.colNet", "num"],
    ] as const) {
      const th = document.createElement("th");
      th.className = cls;
      th.textContent = t(key);
      head.append(th);
    }
    const thead = document.createElement("thead");
    thead.append(head);
    const body = document.createElement("tbody");
    const rows = new Map((this.overview?.rows ?? []).map((r) => [r.strategy, r]));
    for (const card of this.cards) body.append(this.row(card, rows.get(card.type)));
    table.append(thead, body);

    const note = document.createElement("div");
    note.className = "strategy-note";
    note.textContent = this.status === "loading" ? t("strategies.loading")
      : this.status === "error" ? t("strategies.error")
      : t("strategies.note", { n: String(this.overview?.candles ?? "") });
    const parts: HTMLElement[] = [title, controls, table];
    if (this.state.auto && this.status === "idle" && this.overview) {
      // Why the bot picked what it picked (or that it waits).
      const choice = document.createElement("div");
      choice.className = "strategy-choice";
      const c = this.overview.choice;
      choice.textContent = c
        ? t("strategies.chosen", {
            name: this.name(c.strategy),
            pf: c.profitFactor === null ? "∞" : c.profitFactor.toFixed(2),
            n: String(c.trades),
            net: `\u2066${formatPercent(c.netPercent)}\u2069`, // keep "+4.4%" together in right-to-left text
          })
        : t("strategies.noChoice");
      choice.classList.toggle("waiting", !c);
      parts.push(choice);
    }
    parts.push(note);
    // Fee rates in use; click to change them.
    const rates = this.host.fees().rates;
    if (rates) {
      const feeLine = document.createElement("button");
      feeLine.type = "button";
      feeLine.className = "fee-line";
      feeLine.textContent = `${t("strategies.feeLine", { taker: String(rates.taker), maker: String(rates.maker) })} ⚙`;
      feeLine.addEventListener("click", () => this.openFees());
      parts.push(feeLine);
    }
    this.root.replaceChildren(...parts);
  }

  private row(card: StrategyCard, row: StrategyRow | undefined): HTMLTableRowElement {
    const t = this.host.t;
    const tr = document.createElement("tr");
    const on = this.state.auto
      ? this.overview?.choice?.strategy === card.type
      : this.state.active === card.type;
    // Dimmed when the market's current state does not suit this strategy.
    const current = this.overview?.marketState;
    const unsuited = current !== undefined && !card.states.includes(current);
    tr.className = (on ? "active" : "") + (unsuited ? " unsuited" : "");
    tr.title = (this.state.auto ? t("strategies.autoRows") : on ? t("strategies.turnOff") : t("strategies.turnOn"))
      + (unsuited ? `\n${t("strategies.unsuited")}` : "");
    if (this.state.auto) tr.classList.add("locked");
    const s = row?.stats;
    const name = document.createElement("td");
    name.className = "name";
    name.innerHTML = `<div class="name-wrap"><span class="radio"></span><span class="label"></span></div>`;
    name.querySelector(".label")!.textContent = this.name(card.type);
    const cells = [
      s ? String(s.trades) : "—",
      s ? String(s.wins) : "—",
      s ? String(s.losses) : "—",
      s ? formatPercent(s.netPercent) : "—",
    ];
    const classes = ["num", "num win", "num loss", `num ${s ? (s.netPercent > 0 ? "up" : s.netPercent < 0 ? "down" : "") : ""}`];
    tr.append(name, ...cells.map((text, i) => {
      const td = document.createElement("td");
      td.className = classes[i];
      td.dir = "ltr";
      td.textContent = text;
      return td;
    }));
    const gear = document.createElement("button");
    gear.type = "button";
    gear.className = "legend-button";
    gear.textContent = "⚙";
    gear.title = t("strategies.details");
    gear.addEventListener("click", (event) => {
      event.stopPropagation();
      this.openDetails(card);
    });
    name.firstElementChild!.append(gear);
    tr.addEventListener("click", () => {
      if (!this.state.auto) this.update(toggleActive(this.state, card.type)); // in Auto the bot picks
    });
    return tr;
  }

  /** The rules in plain words, the result on this chart, and the settings. */
  private openDetails(card: StrategyCard): void {
    const t = this.host.t;
    const mode = this.host.mode();
    const current = effectiveParams(card, this.state, mode);
    const stats = this.overview?.rows.find((r) => r.strategy === card.type)?.stats;

    const form = document.createElement("form");
    form.className = "window settings-window strategy-window";
    form.noValidate = true;
    const title = document.createElement("div");
    title.className = "window-title";
    title.textContent = this.name(card.type);
    const desc = document.createElement("p");
    desc.className = "strategy-desc";
    desc.textContent = t(`strat.${card.type}.desc` as MessageKey);
    const facts = document.createElement("dl");
    facts.className = "strategy-facts";
    const fact = (label: MessageKey, value: string) => {
      const dt = document.createElement("dt");
      dt.textContent = t(label);
      const dd = document.createElement("dd");
      dd.textContent = value;
      facts.append(dt, dd);
    };
    fact("strategies.suits", card.states.map((s) => t(`state.${s}` as MessageKey)).join("، "));
    fact("strategies.uses", card.uses.join(", "));
    if (stats) {
      fact("strategies.colTrades", `${stats.trades} (${t("strategies.colWins")} ${stats.wins} · ${t("strategies.colLosses")} ${stats.losses} · ${t("strategies.breakevens")} ${stats.breakevens})`);
      fact("strategies.winRate", stats.winRate === null ? "—" : `${stats.winRate.toFixed(0)}%`);
      fact("strategies.profitFactor", stats.profitFactor === null ? (stats.wins ? "∞" : "—") : stats.profitFactor.toFixed(2));
      fact("strategies.colNet", formatPercent(stats.netPercent));
      fact("strategies.feeTotal", `${stats.feePercent.toFixed(2)}%`);
    }
    form.append(title, desc, facts);

    const heading = (key: MessageKey) => {
      const h = document.createElement("div");
      h.className = "list-heading";
      h.textContent = t(key);
      form.append(h);
    };
    const input = (p: ParamSpec) => form.querySelector(`#param-${p.name}`) as HTMLInputElement;
    const read = (p: ParamSpec) => (isSwitch(p) ? (input(p).checked ? 1 : 0) : Number(input(p).value));
    const write = (p: ParamSpec, value: number) => {
      if (isSwitch(p)) input(p).checked = value === 1;
      else input(p).value = String(value);
    };
    const own = card.params.filter((p) => !COMMON.has(p.name));
    const common = card.params.filter((p) => COMMON.has(p.name));
    for (const [key, list] of [["strategies.settings", own], ["strategies.extraRules", common]] as const) {
      heading(key);
      for (const p of list) {
        const field = document.createElement("label");
        field.className = "field";
        const label = document.createElement("span");
        label.textContent = t(`param.${p.name}` as MessageKey);
        const box = document.createElement("input");
        box.id = `param-${p.name}`;
        field.append(label, box);
        if (isSwitch(p)) {
          box.type = "checkbox";
          box.className = "switch";
        } else {
          box.type = "number";
          box.dir = "ltr";
          box.min = String(p.min);
          box.max = String(p.max);
          box.step = String(p.step);
          const range = document.createElement("small");
          range.textContent = t("settings.range", { min: String(p.min), max: String(p.max) });
          field.append(range);
        }
        form.append(field);
        write(p, current[p.name]);
      }
    }
    const error = document.createElement("div");
    error.className = "popup-error";
    error.hidden = true;
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const apply = document.createElement("button");
    apply.type = "submit";
    apply.className = "primary";
    apply.textContent = t("settings.apply");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = t("strategies.defaults");
    reset.addEventListener("click", () => {
      for (const p of card.params) write(p, defaultValue(card, p.name, mode));
    });
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = t("settings.cancel");
    cancel.addEventListener("click", () => this.host.closeWindow());
    actions.append(apply, reset, cancel);
    form.append(error, actions);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const params: Record<string, number> = {};
      for (const p of card.params) params[p.name] = read(p);
      const bad = invalidParams(card, params);
      form.querySelectorAll("input").forEach((i) => i.classList.toggle("invalid", bad.includes(i.id.slice(6))));
      if (bad.length) {
        error.textContent = t("settings.invalidParam");
        error.hidden = false;
        return;
      }
      this.host.closeWindow();
      this.update(setParams(this.state, card, params, mode));
    });
    this.host.openWindow(form);
  }

  /** Window to change the fee rates of the current market type. */
  private openFees(): void {
    const t = this.host.t;
    const { market, rates, defaults } = this.host.fees();
    if (!rates) return;
    const form = document.createElement("form");
    form.className = "window settings-window";
    form.noValidate = true;
    const title = document.createElement("div");
    title.className = "window-title";
    title.textContent = t("strategies.feeTitle", { market: t(market === "spot" ? "market.spot" : "market.futures") });
    const help = document.createElement("p");
    help.className = "strategy-desc";
    help.textContent = t("strategies.feeHelp");
    form.append(title, help);
    const field = (id: string, label: MessageKey, value: number) => {
      const wrap = document.createElement("label");
      wrap.className = "field";
      const name = document.createElement("span");
      name.textContent = t(label);
      const input = document.createElement("input");
      input.type = "number";
      input.id = id;
      input.dir = "ltr";
      input.min = "0";
      input.max = "1";
      input.step = "0.001";
      input.value = String(value);
      const range = document.createElement("small");
      range.textContent = t("settings.range", { min: "0", max: "1" });
      wrap.append(name, input, range);
      form.append(wrap);
      return input;
    };
    const taker = field("fee-taker", "strategies.feeTaker", rates.taker);
    const maker = field("fee-maker", "strategies.feeMaker", rates.maker);
    const error = document.createElement("div");
    error.className = "popup-error";
    error.hidden = true;
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const apply = document.createElement("button");
    apply.type = "submit";
    apply.className = "primary";
    apply.textContent = t("settings.apply");
    const reset = document.createElement("button");
    reset.type = "button";
    reset.textContent = t("strategies.defaults");
    reset.addEventListener("click", () => {
      if (!defaults) return;
      taker.value = String(defaults.taker);
      maker.value = String(defaults.maker);
    });
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = t("settings.cancel");
    cancel.addEventListener("click", () => this.host.closeWindow());
    actions.append(apply, reset, cancel);
    form.append(error, actions);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const chosen = { maker: Number(maker.value), taker: Number(taker.value) };
      taker.classList.toggle("invalid", !validFee(chosen.taker));
      maker.classList.toggle("invalid", !validFee(chosen.maker));
      if (!validFee(chosen.taker) || !validFee(chosen.maker)) {
        error.textContent = t("settings.invalidParam");
        error.hidden = false;
        return;
      }
      this.host.closeWindow();
      this.host.saveFees(chosen);
    });
    this.host.openWindow(form);
  }
}
