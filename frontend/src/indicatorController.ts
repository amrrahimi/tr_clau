// Indicator controls on the chart: Auto/Manual/Start, the legend in each
// pane's corner, the indicator list window, the settings window and the
// confirmation dialogs. The rules for modes live in indicatorList.ts.

import type { ChartView } from "./chart.ts";
import { paneLayout } from "./chart.ts";
import { formatPrice } from "./format.ts";
import {
  MAX_INDICATORS, addIndicator, cleanList, fromResults, instanceLabel, invalidParams, latestValues,
  loadManualState, removeIndicator, saveManualState, updateParams, type BotMode,
} from "./indicatorList.ts";
import type { MessageKey } from "./locales/en.ts";
import type { CatalogSpec, IndicatorInstance, IndicatorResult } from "./types.ts";

export interface ControllerHost {
  t(key: MessageKey, params?: Record<string, string>): string;
  dir(): "rtl" | "ltr";
  chart: ChartView;
  /** The mode changed; the app asks for new lines (a preview when stopped). */
  onModeChange(mode: BotMode): void;
  /** The user's list changed while stopped: draw a new preview. */
  onListChange(): void;
}

export interface ControllerElements {
  corner: HTMLElement; // Auto / Manual / Start / + Indicator (top-left of the price pane)
  legends: HTMLElement; // layer holding one legend block per pane
  modal: HTMLElement; // layer for windows and dialogs
}

export class IndicatorController {
  private state = loadManualState();
  private catalog: CatalogSpec[] = [];
  private results: IndicatorResult[] = [];

  constructor(private readonly host: ControllerHost, private readonly els: ControllerElements) {
    els.modal.addEventListener("click", (event) => {
      if (event.target === els.modal) this.closeModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !els.modal.hidden) this.closeModal();
    });
  }

  get mode(): BotMode {
    return this.state.mode;
  }

  /**
   * What to ask the backend for: null = the bot's automatic list, otherwise the
   * user's list. While stopped the lines are only a preview: the bot itself
   * (market state now, signals and trades later) stays off until Start.
   */
  request(): IndicatorInstance[] | null {
    return this.state.mode === "auto" ? null : this.state.list;
  }

  /** True while the lines on the chart are a preview (stopped, before Start). */
  get isPreview(): boolean {
    return this.state.mode === "manual-stopped";
  }

  setCatalog(catalog: CatalogSpec[]): void {
    this.catalog = catalog;
    this.state.list = cleanList(this.state.list, catalog);
    this.render();
  }

  /** New results from the backend. */
  showResults(results: IndicatorResult[]): void {
    this.results = results;
    this.host.chart.setIndicators(results);
    this.render();
  }

  clearResults(): void {
    this.results = [];
    this.host.chart.setIndicators([]);
    this.render();
  }

  private spec(type: string): CatalogSpec | undefined {
    return this.catalog.find((s) => s.type === type);
  }

  private setMode(mode: BotMode): void {
    this.state.mode = mode;
    saveManualState(this.state);
    this.render();
    this.host.onModeChange(mode);
  }

  /** Any edit while running stops the bot first (the owner's rule: edit, then Start). */
  private beginEdit(): void {
    if (this.state.mode === "manual-running") this.setMode("manual-stopped");
  }

  private saveList(list: IndicatorInstance[]): void {
    this.state.list = list;
    saveManualState(this.state);
    // Drop removed indicators from the chart straight away; the new preview follows.
    const ids = new Set(list.map((i) => i.id));
    if (this.results.some((r) => !ids.has(r.id))) {
      this.results = this.results.filter((r) => ids.has(r.id));
      this.host.chart.setIndicators(this.results);
    }
    this.render();
    this.host.onListChange();
  }

  // ---------- actions ----------

  async clickManual(): Promise<void> {
    if (this.state.mode !== "auto") return;
    if (!(await this.confirm("confirm.stopAuto"))) return;
    this.state.list = cleanList(fromResults(this.results), this.catalog);
    this.setMode("manual-stopped");
  }

  async clickAuto(): Promise<void> {
    if (this.state.mode === "auto") return;
    if (!(await this.confirm("confirm.backToAuto"))) return;
    this.state.list = [];
    this.setMode("auto");
  }

  start(): void {
    if (this.state.mode !== "manual-stopped") return;
    this.setMode("manual-running");
  }

  private remove(id: string): void {
    this.beginEdit();
    this.saveList(removeIndicator(this.state.list, id));
  }

  // ---------- rendering ----------

  render(): void {
    this.renderCorner();
    this.renderLegends();
  }

  private renderCorner(): void {
    const t = this.host.t.bind(this.host);
    const mode = this.state.mode;
    const corner = this.els.corner;
    corner.replaceChildren();
    corner.dir = this.host.dir(); // button texts read in the page's language direction

    const toggle = document.createElement("div");
    toggle.className = "segmented small";
    const auto = button(t("settings.auto"), mode === "auto" ? "active" : "", () => void this.clickAuto());
    auto.title = t("settings.autoHint");
    const manual = button(t("settings.manual"), mode !== "auto" ? "active" : "", () => void this.clickManual());
    toggle.append(auto, manual);
    corner.append(toggle);

    if (mode === "manual-stopped") {
      const start = button(`▶ ${t("bot.start")}`, "start-button", () => this.start());
      start.title = t("bot.startHint");
      corner.append(start);
      const tag = document.createElement("span");
      tag.className = "preview-tag";
      tag.textContent = t("bot.preview");
      tag.title = t("bot.previewHint");
      corner.append(tag);
    }
    if (mode !== "auto") {
      corner.append(button(t("indicators.add"), "add-button", () => this.openList()));
    }
  }

  /** One legend block per pane, placed at that pane's top-left corner. */
  private renderLegends(): void {
    const layer = this.els.legends;
    layer.replaceChildren();
    const editable = this.state.mode !== "auto";

    // While stopped, until the preview for the current list arrives, the list sits in the main corner.
    const previewReady = this.state.list.length > 0 &&
      this.state.list.every((i) => this.results.some((r) => r.id === i.id));
    if (this.state.mode === "manual-stopped" && !previewReady) {
      const block = this.block(0);
      if (!this.state.list.length) {
        const empty = document.createElement("div");
        empty.className = "legend-empty";
        empty.textContent = this.host.t("indicators.empty");
        block.append(empty);
      }
      for (const inst of this.state.list) {
        const spec = this.spec(inst.type);
        block.append(this.row(inst.id, spec?.outputs[0]?.color ?? "#787b86", instanceLabel(spec, inst), "", editable, true));
      }
      layer.append(block);
      return;
    }

    const panes = paneLayout(this.results);
    const tops = this.host.chart.paneTops();
    const blocks = new Map<number, HTMLElement>();
    for (const r of this.results) {
      const pane = panes.get(r.id) ?? 0;
      let block = blocks.get(pane);
      if (!block) {
        block = this.block(tops[pane] ?? 0, pane === 0);
        blocks.set(pane, block);
        layer.append(block);
      }
      const precision = r.scale ? 2 : this.host.chart.pricePrecision;
      const values = latestValues(r).map((v) => formatPrice(v, precision)).join("  ");
      const label = this.state.list.find((i) => i.id === r.id) && this.isPreview
        ? instanceLabel(this.spec(r.type), this.state.list.find((i) => i.id === r.id)!)
        : r.label;
      block.append(this.row(r.id, r.outputs[0]?.color ?? "#787b86", label, r.type === "volume" ? "" : values, editable, false));
    }
  }

  private block(top: number, mainPane = true): HTMLElement {
    const block = document.createElement("div");
    block.className = "legend";
    // The main pane's legend sits under the Auto/Manual buttons.
    block.style.top = `${top + (mainPane ? 40 : 6)}px`;
    return block;
  }

  private row(id: string, color: string, label: string, values: string, editable: boolean, stopped: boolean): HTMLElement {
    const row = document.createElement("div");
    row.className = "legend-row" + (stopped ? " stopped" : "");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = color;
    const name = document.createElement("span");
    name.className = "legend-label";
    name.textContent = label;
    const value = document.createElement("span");
    value.className = "legend-value";
    value.textContent = values;
    row.append(dot, name, value);
    if (editable) {
      const gear = button("⚙", "legend-button", () => this.openSettings(id));
      gear.title = this.host.t("legend.settings");
      const remove = button("×", "legend-button", () => this.remove(id));
      remove.title = this.host.t("legend.remove");
      row.append(gear, remove);
    }
    return row;
  }

  // ---------- windows ----------

  private openModal(content: HTMLElement): void {
    this.els.modal.replaceChildren(content);
    content.dir = this.host.dir();
    this.els.modal.hidden = false;
  }

  closeModal(): void {
    const resolve = this.pendingConfirm;
    this.pendingConfirm = null;
    this.els.modal.hidden = true;
    this.els.modal.replaceChildren();
    resolve?.(false);
  }

  private pendingConfirm: ((answer: boolean) => void) | null = null;

  /** An in-app yes/no question (the system dialogs cannot show Persian right-to-left). */
  confirm(message: MessageKey): Promise<boolean> {
    return new Promise((resolve) => {
      const box = document.createElement("div");
      box.className = "dialog";
      const text = document.createElement("p");
      text.textContent = this.host.t(message);
      const actions = document.createElement("div");
      actions.className = "dialog-actions";
      const answer = (value: boolean) => {
        this.pendingConfirm = null;
        this.els.modal.hidden = true;
        this.els.modal.replaceChildren();
        resolve(value);
      };
      actions.append(
        button(this.host.t("confirm.yes"), "primary", () => answer(true)),
        button(this.host.t("confirm.no"), "", () => answer(false)),
      );
      box.append(text, actions);
      this.openModal(box);
      this.pendingConfirm = resolve;
      (actions.firstElementChild as HTMLElement).focus();
    });
  }

  private openList(): void {
    const t = this.host.t.bind(this.host);
    const box = document.createElement("div");
    box.className = "window indicator-list";
    box.innerHTML = `<div class="window-title"></div><input type="search" class="search" autocomplete="off" /><div class="list-body"></div><div class="list-status"></div>`;
    box.querySelector(".window-title")!.textContent = t("indicators.title");
    const search = box.querySelector("input") as HTMLInputElement;
    search.placeholder = t("indicators.search");
    const body = box.querySelector(".list-body") as HTMLElement;
    const status = box.querySelector(".list-status") as HTMLElement;

    const draw = () => {
      const q = search.value.trim().toLowerCase();
      body.replaceChildren();
      for (const [pane, heading] of [["price", "indicators.onPrice"], ["own", "indicators.ownPane"]] as const) {
        const specs = this.catalog.filter((s) => s.pane === pane && (
          !q || s.name.toLowerCase().includes(q) || s.type.includes(q) || t(`ind.${s.type}` as MessageKey).toLowerCase().includes(q)));
        if (!specs.length) continue;
        const h = document.createElement("div");
        h.className = "list-heading";
        h.textContent = t(heading);
        body.append(h);
        for (const spec of specs) {
          const item = document.createElement("button");
          item.type = "button";
          item.className = "list-item";
          item.innerHTML = `<span class="list-name" dir="ltr"></span><span class="list-desc"></span>`;
          item.querySelector(".list-name")!.textContent = spec.name;
          item.querySelector(".list-desc")!.textContent = t(`ind.${spec.type}` as MessageKey);
          item.addEventListener("click", () => {
            if (this.state.list.length >= MAX_INDICATORS) {
              status.textContent = t("indicators.max", { n: String(MAX_INDICATORS) });
              return;
            }
            this.beginEdit();
            this.saveList(addIndicator(this.state.list, spec));
            status.textContent = `${t("indicators.added")}: ${spec.name}`;
          });
          body.append(item);
        }
      }
    };
    search.addEventListener("input", draw);
    draw();
    this.openModal(box);
    search.focus();
  }

  private openSettings(id: string): void {
    // While running, result ids are the list's ids (the list was sent to the backend).
    const inst = this.state.list.find((i) => i.id === id);
    const spec = inst && this.spec(inst.type);
    if (!inst || !spec) return;
    const t = this.host.t.bind(this.host);

    const form = document.createElement("form");
    form.className = "window settings-window";
    form.noValidate = true; // our own range check shows a translated message instead of the system's
    const title = document.createElement("div");
    title.className = "window-title";
    title.textContent = `${t(`ind.${spec.type}` as MessageKey)} · ${instanceLabel(spec, inst)}`;
    form.append(title);
    for (const p of spec.params) {
      const field = document.createElement("label");
      field.className = "field";
      const name = document.createElement("span");
      name.textContent = t(`param.${p.name}` as MessageKey);
      const input = document.createElement("input");
      input.type = "number";
      input.id = `param-${p.name}`;
      input.dir = "ltr";
      input.min = String(p.min);
      input.max = String(p.max);
      input.step = String(p.step);
      input.value = String(inst.params[p.name] ?? p.default);
      const range = document.createElement("small");
      range.textContent = t("settings.range", { min: String(p.min), max: String(p.max) });
      field.append(name, input, range);
      form.append(field);
    }
    if (!spec.params.length) {
      const none = document.createElement("p");
      none.className = "muted";
      none.textContent = "—";
      form.append(none);
    }
    const error = document.createElement("div");
    error.className = "popup-error";
    error.hidden = true;
    const actions = document.createElement("div");
    actions.className = "dialog-actions";
    const apply = button(t("settings.apply"), "primary", () => undefined);
    apply.type = "submit";
    actions.append(apply, button(t("settings.cancel"), "", () => this.closeModal()));
    form.append(error, actions);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const params: Record<string, number> = {};
      for (const p of spec.params) params[p.name] = Number((form.querySelector(`#param-${p.name}`) as HTMLInputElement).value);
      const bad = invalidParams(spec, params);
      form.querySelectorAll("input").forEach((i) => i.classList.toggle("invalid", bad.includes(i.id.slice(6))));
      if (bad.length) {
        error.textContent = t("settings.invalidParam");
        error.hidden = false;
        return;
      }
      this.beginEdit();
      this.saveList(updateParams(this.state.list, inst.id, params));
      this.closeModal();
    });
    this.openModal(form);
    (form.querySelector("input") as HTMLInputElement | null)?.focus();
  }
}

function button(label: string, className: string, onClick: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  if (className) b.className = className;
  b.addEventListener("click", onClick);
  return b;
}
