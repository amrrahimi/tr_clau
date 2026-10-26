// Manual indicator settings: checking them, sending them, remembering them,
// and the legend shown in the chart's corner. No screen code here, so it can be tested.

import type { Analysis, IndicatorSettings, LineName } from "./types.ts";

// Same limits as backend/app/presets.py.
export const PERIOD_MIN = 2;
export const PERIOD_MAX = 400;
export const MULT_MIN = 0.5;
export const MULT_MAX = 5;

export const PERIOD_FIELDS = ["ema_fast", "ema_slow", "bb_period", "rsi_period", "atr_period"] as const;

/** Standard values, used when nothing better is known. */
export const DEFAULT_SETTINGS: IndicatorSettings = {
  ema_fast_on: true, ema_fast: 20,
  ema_slow_on: true, ema_slow: 50,
  bb_on: true, bb_period: 20, bb_mult: 2,
  rsi_on: true, rsi_period: 14,
  atr_period: 14,
};

/** Names of fields that are out of range (empty = all fine). */
export function invalidFields(s: IndicatorSettings): string[] {
  const bad: string[] = PERIOD_FIELDS.filter(
    (f) => !Number.isInteger(s[f]) || s[f] < PERIOD_MIN || s[f] > PERIOD_MAX,
  );
  if (!Number.isFinite(s.bb_mult) || s.bb_mult < MULT_MIN || s.bb_mult > MULT_MAX) bad.push("bb_mult");
  return bad;
}

/** Query parameters for /api/analysis. `null` settings = automatic. */
export function analysisParams(settings: IndicatorSettings | null): Record<string, string> {
  if (!settings) return { auto: "true" };
  const params: Record<string, string> = { auto: "false" };
  for (const [key, value] of Object.entries(settings)) params[key] = String(value);
  return params;
}

// ---------- remembering manual settings ----------
// Kept only while Manual is chosen; choosing Auto removes them (agreed rule).

const STORAGE_KEY = "trading-bot.manualSettings";

export function loadManual(storage: Pick<Storage, "getItem"> | undefined = safeStorage()): IndicatorSettings | null {
  try {
    const text = storage?.getItem(STORAGE_KEY);
    if (!text) return null;
    const parsed = { ...DEFAULT_SETTINGS, ...JSON.parse(text) } as IndicatorSettings;
    return invalidFields(parsed).length ? null : parsed;
  } catch {
    return null;
  }
}

export function saveManual(settings: IndicatorSettings, storage: Pick<Storage, "setItem"> | undefined = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // not being able to remember is not worth an error message
  }
}

export function clearManual(storage: Pick<Storage, "removeItem"> | undefined = safeStorage()): void {
  try {
    storage?.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

// ---------- legend ----------

export interface LegendItem {
  id: "emaFast" | "emaSlow" | "bb" | "rsi";
  label: string; // e.g. "EMA 9", "BB 20 2", "RSI 14" — the way TradingView names them
  values: (number | null)[]; // latest value(s); Bollinger has three
}

function lastValue(analysis: Analysis, name: LineName): number | null {
  const line = analysis.lines[name];
  return line && line.length ? line[line.length - 1].value : null;
}

export function legendItems(analysis: Analysis): LegendItem[] {
  const s = analysis.settings;
  const items: LegendItem[] = [];
  if (s.ema_fast_on) items.push({ id: "emaFast", label: `EMA ${s.ema_fast}`, values: [lastValue(analysis, "emaFast")] });
  if (s.ema_slow_on) items.push({ id: "emaSlow", label: `EMA ${s.ema_slow}`, values: [lastValue(analysis, "emaSlow")] });
  if (s.bb_on) {
    items.push({
      id: "bb",
      label: `BB ${s.bb_period} ${s.bb_mult}`,
      values: [lastValue(analysis, "bbMiddle"), lastValue(analysis, "bbUpper"), lastValue(analysis, "bbLower")],
    });
  }
  if (s.rsi_on) items.push({ id: "rsi", label: `RSI ${s.rsi_period}`, values: [lastValue(analysis, "rsi")] });
  return items;
}
