// The bot's mode and the user's indicator list. No screen code, so it can be tested.
//
// Three modes (the owner's design):
//   auto            the bot chooses indicators from the market state and keeps analysing
//   manual-stopped  the user is editing their own list; the bot does not analyse
//   manual-running  the bot analyses with the user's list (after pressing Start)
//
//   auto --(Manual, "are you sure?" yes)--> manual-stopped --(Start)--> manual-running
//   manual-running --(any edit)--> manual-stopped
//   manual-* --(Auto, confirm)--> auto            (the user's list is dropped)

import type { CatalogSpec, IndicatorInstance, IndicatorResult } from "./types.ts";

export type BotMode = "auto" | "manual-stopped" | "manual-running";

export interface ManualState {
  mode: BotMode;
  list: IndicatorInstance[];
}

export const MAX_INDICATORS = 20;

let counter = 0;
/** A short id that is unique within the list. */
export function newId(type: string, existing: IndicatorInstance[]): string {
  const taken = new Set(existing.map((i) => i.id));
  let id: string;
  do {
    counter += 1;
    id = `${type}-${Date.now().toString(36)}-${counter}`;
  } while (taken.has(id));
  return id;
}

export function defaultParams(spec: CatalogSpec): Record<string, number> {
  return Object.fromEntries(spec.params.map((p) => [p.name, p.default]));
}

/** A new instance with TradingView's default settings, added at the end. */
export function addIndicator(list: IndicatorInstance[], spec: CatalogSpec): IndicatorInstance[] {
  if (list.length >= MAX_INDICATORS) return list;
  return [...list, { id: newId(spec.type, list), type: spec.type, params: defaultParams(spec) }];
}

export function removeIndicator(list: IndicatorInstance[], id: string): IndicatorInstance[] {
  return list.filter((i) => i.id !== id);
}

export function updateParams(list: IndicatorInstance[], id: string, params: Record<string, number>): IndicatorInstance[] {
  return list.map((i) => (i.id === id ? { ...i, params: { ...params } } : i));
}

/** Names of settings that are missing, not numbers, out of range, or decimals where whole numbers are needed. */
export function invalidParams(spec: Pick<CatalogSpec, "params">, params: Record<string, number>): string[] {
  return spec.params
    .filter((p) => {
      const v = params[p.name];
      return typeof v !== "number" || !Number.isFinite(v) || v < p.min || v > p.max || (p.step === 1 && !Number.isInteger(v));
    })
    .map((p) => p.name);
}

/** TradingView-style name with settings, e.g. "EMA 21", "BB 20 2" (same rule as the backend). */
export function instanceLabel(spec: CatalogSpec | undefined, instance: IndicatorInstance): string {
  if (!spec) return instance.type;
  const values = spec.params.map((p) => String(instance.params[p.name] ?? p.default));
  return [spec.name, ...values].join(" ");
}

/** The bot's current automatic list, as a starting point for the user's own list. */
export function fromResults(results: IndicatorResult[]): IndicatorInstance[] {
  return results.map((r, n) => ({ id: `${r.type}-start-${n}`, type: r.type, params: { ...r.params } }));
}

/** Keep only instances the catalog knows, with valid settings (e.g. after an update removed one). */
export function cleanList(list: IndicatorInstance[], catalog: CatalogSpec[]): IndicatorInstance[] {
  const byType = new Map(catalog.map((s) => [s.type, s]));
  return list.filter((i) => {
    const spec = byType.get(i.type);
    return spec !== undefined && invalidParams(spec, i.params).length === 0;
  }).slice(0, MAX_INDICATORS);
}

/** Latest value of each output, for the legend. */
export function latestValues(result: IndicatorResult): (number | null)[] {
  return result.outputs.map((o) => (o.points.length ? o.points[o.points.length - 1].value : null));
}

// ---------- remembering the user's choice ----------

const STORAGE_KEY = "trading-bot.manual";
const OLD_KEY = "trading-bot.manualSettings"; // the earlier fixed-settings version

export function loadManualState(storage: Pick<Storage, "getItem"> | undefined = safeStorage()): ManualState {
  const auto: ManualState = { mode: "auto", list: [] };
  try {
    const text = storage?.getItem(STORAGE_KEY);
    if (text) {
      const data = JSON.parse(text);
      const mode: BotMode = data.mode === "manual-running" ? "manual-running" : "manual-stopped";
      const list = Array.isArray(data.list)
        ? data.list.filter((i: unknown): i is IndicatorInstance =>
            typeof i === "object" && i !== null && typeof (i as IndicatorInstance).id === "string" &&
            typeof (i as IndicatorInstance).type === "string" && typeof (i as IndicatorInstance).params === "object")
        : [];
      return { mode, list };
    }
    const old = storage?.getItem(OLD_KEY);
    if (old) return { mode: "manual-stopped", list: convertOldSettings(JSON.parse(old)) };
  } catch {
    // broken or blocked storage: start in automatic mode
  }
  return auto;
}

export function saveManualState(state: ManualState, storage: Pick<Storage, "setItem" | "removeItem"> | undefined = safeStorage()): void {
  try {
    storage?.removeItem(OLD_KEY);
    if (state.mode === "auto") storage?.removeItem(STORAGE_KEY);
    else storage?.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // not being able to remember is not worth an error message
  }
}

/** The earlier version stored fixed fields (ema_fast, bb_on...); turn them into a list. */
export function convertOldSettings(old: Record<string, unknown>): IndicatorInstance[] {
  const num = (k: string, d: number) => (typeof old[k] === "number" ? (old[k] as number) : d);
  const list: IndicatorInstance[] = [];
  if (old.ema_fast_on !== false) list.push({ id: "ema-old-fast", type: "ema", params: { length: num("ema_fast", 20) } });
  if (old.ema_slow_on !== false) list.push({ id: "ema-old-slow", type: "ema", params: { length: num("ema_slow", 50) } });
  if (old.bb_on !== false) list.push({ id: "bb-old", type: "bb", params: { length: num("bb_period", 20), mult: num("bb_mult", 2) } });
  if (old.rsi_on !== false) list.push({ id: "rsi-old", type: "rsi", params: { length: num("rsi_period", 14) } });
  return list;
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}
