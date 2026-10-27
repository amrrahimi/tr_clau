// The strategies section without screen code, so it can be tested:
// which strategy is active, the user's changed settings, and how trades turn
// into arrows and boxes on the chart (the owner's design):
//   entry long  = green arrow up, under the candle
//   entry short = red arrow down, above the candle
//   exit        = yellow arrow with ✓ (profit), ✗ (loss) or ＝ (closed at the entry price)
//   each trade  = green box entry→take-profit, red box entry→stop-loss,
//                 from the entry candle to the exit candle (or the last candle while open)

import type { Mode, StrategyCard, Trade } from "./types.ts";

export const COLORS = {
  long: "#089981",
  short: "#f23645",
  exit: "#f7c948",
  profitBox: "rgba(8, 153, 129, 0.22)",
  lossBox: "rgba(242, 54, 69, 0.22)",
};

export interface StrategyState {
  active: string | null; // only one strategy at a time
  settings: Record<string, Record<string, number>>; // only settings the user changed, per strategy
}

const STORAGE_KEY = "trading-bot.strategies";

export function loadStrategyState(storage: Pick<Storage, "getItem"> | null = safeStorage()): StrategyState {
  const empty: StrategyState = { active: null, settings: {} };
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (!raw) return empty;
    const data = JSON.parse(raw) as Partial<StrategyState>;
    const settings: StrategyState["settings"] = {};
    if (data.settings && typeof data.settings === "object") {
      for (const [kind, params] of Object.entries(data.settings)) {
        if (!params || typeof params !== "object") continue;
        const clean = Object.fromEntries(Object.entries(params).filter(([, v]) => typeof v === "number" && Number.isFinite(v)));
        if (Object.keys(clean).length) settings[kind] = clean;
      }
    }
    return { active: typeof data.active === "string" ? data.active : null, settings };
  } catch {
    return empty;
  }
}

export function saveStrategyState(state: StrategyState, storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // storage full or blocked: the choice is simply not remembered
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Drop saved settings of strategies that no longer exist (or an unknown active one). */
export function cleanStrategyState(state: StrategyState, cards: StrategyCard[]): StrategyState {
  const known = new Set(cards.map((c) => c.type));
  const settings = Object.fromEntries(Object.entries(state.settings).filter(([kind]) => known.has(kind)));
  return { active: state.active && known.has(state.active) ? state.active : null, settings };
}

/** Clicking a row: turns that strategy on, or off if it was already on. */
export function toggleActive(state: StrategyState, kind: string): StrategyState {
  return { ...state, active: state.active === kind ? null : kind };
}

/** Default value of a setting for the trading mode (e.g. trend EMA 50 for scalping, 200 for daily). */
export function defaultValue(card: StrategyCard, name: string, mode: Mode): number {
  const byMode = card.modeDefaults[name]?.[mode];
  if (byMode !== undefined) return byMode;
  return card.params.find((p) => p.name === name)?.default ?? 0;
}

/** The settings a strategy runs with: the user's changes over the defaults. */
export function effectiveParams(card: StrategyCard, state: StrategyState, mode: Mode): Record<string, number> {
  const mine = state.settings[card.type] ?? {};
  return Object.fromEntries(card.params.map((p) => [p.name, mine[p.name] ?? defaultValue(card, p.name, mode)]));
}

/** Save only values that differ from the defaults, so a later mode switch still uses its own default. */
export function setParams(state: StrategyState, card: StrategyCard, params: Record<string, number>, mode: Mode): StrategyState {
  const changed = Object.fromEntries(
    Object.entries(params).filter(([name, value]) => value !== defaultValue(card, name, mode)),
  );
  const settings = { ...state.settings };
  if (Object.keys(changed).length) settings[card.type] = changed;
  else delete settings[card.type];
  return { ...state, settings };
}

export interface Marker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown";
  color: string;
  text: string;
  size: number;
}

/** Arrow size (1 = the chart library's normal size); a bit larger so they stand out. */
export const ARROW_SIZE = 1.5;

/** Arrows for the trades, sorted by time (the chart library needs that order). */
export function tradeMarkers(trades: Trade[]): Marker[] {
  const markers: Marker[] = [];
  for (const t of trades) {
    const long = t.side === "long";
    markers.push(long
      ? { time: t.entryTime, position: "belowBar", shape: "arrowUp", color: COLORS.long, text: "", size: ARROW_SIZE }
      : { time: t.entryTime, position: "aboveBar", shape: "arrowDown", color: COLORS.short, text: "", size: ARROW_SIZE });
    if (t.exitTime !== null && t.result !== "open") {
      // Closing a long sells (arrow down, above); closing a short buys (arrow up, below).
      markers.push({
        time: t.exitTime,
        position: long ? "aboveBar" : "belowBar",
        shape: long ? "arrowDown" : "arrowUp",
        color: COLORS.exit,
        text: t.result === "win" ? "✓" : t.result === "breakeven" ? "＝" : "✗",
        size: ARROW_SIZE,
      });
    }
  }
  return markers.sort((a, b) => a.time - b.time);
}

export interface Box {
  from: number; // time
  to: number; // time
  top: number; // price
  bottom: number; // price
  color: string;
}

/** Two boxes per trade: take-profit side (green) and stop-loss side (red). */
export function tradeBoxes(trades: Trade[], lastTime: number | null): Box[] {
  const boxes: Box[] = [];
  for (const t of trades) {
    const to = t.exitTime ?? lastTime ?? t.entryTime;
    boxes.push(
      { from: t.entryTime, to, top: Math.max(t.entryPrice, t.takeProfit), bottom: Math.min(t.entryPrice, t.takeProfit), color: COLORS.profitBox },
      { from: t.entryTime, to, top: Math.max(t.entryPrice, t.stopLoss), bottom: Math.min(t.entryPrice, t.stopLoss), color: COLORS.lossBox },
    );
  }
  return boxes;
}

/** "+4.2%", "−1.1%", "0.0%". */
export function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const fixed = Math.abs(value).toFixed(1);
  if (fixed === "0.0") return "0.0%";
  return `${value > 0 ? "+" : "−"}${fixed}%`;
}
