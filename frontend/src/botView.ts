// Small pieces of the automatic (bot) screen without screen code, so they can be tested.

import { pricePrecision } from "./candles.ts";
import { formatPrice } from "./format.ts";
import type { MessageKey } from "./locales/en.ts";
import type { BrainState, PaperEvent, PaperPosition, PaperState, PaperTrade, StrategyResults, Trade } from "./types.ts";

export const TIMEFRAME_SECONDS: Record<string, number> = {
  "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
};

export function candleStart(time: number, timeframe: string): number {
  const step = TIMEFRAME_SECONDS[timeframe] ?? 60;
  return Math.floor(time / step) * step;
}

/** Why a dragged stop or target cannot go there (null = fine). Same rules as the bot (paper.set_levels):
 * the stop stays on the losing side of the price now and before the liquidation price,
 * the target stays on the winning side of the price now. */
export function levelProblem(p: PaperPosition, kind: "stop" | "target", price: number, now: number):
  "stop_side" | "stop_liquidation" | "target_side" | null {
  const long = p.side === "long";
  if (kind === "target") return (long ? price > now : price < now) ? null : "target_side";
  if (!(long ? price < now : price > now)) return "stop_side";
  if (!(long ? price > p.liquidation : price < p.liquidation)) return "stop_liquidation";
  return null;
}

/** USDT result if the position closed at this price, both fees paid (feePercent: the exit fee). */
export function resultAt(p: PaperPosition, price: number, entryFeePercent: number, exitFeePercent: number): number {
  const dir = p.side === "long" ? 1 : -1;
  const gross = p.quantity * (price - p.entryPrice) * dir;
  return gross - p.notional * entryFeePercent / 100 - p.quantity * price * exitFeePercent / 100;
}

/** Price that moves the stop to break-even (part of the way to this target), or null when off or done. */
export function breakevenTrigger(p: PaperPosition, target: number = p.takeProfit): number | null {
  if (!p.breakevenPart || p.breakevenAt) return null;
  return p.entryPrice + (target - p.entryPrice) * p.breakevenPart;
}

/** Every strategy for the manual list: the catalog's order, else the bot's lists per timeframe, plus the
 * chosen ones; each once. Without the catalog the panel used to show only the ticked strategies. */
export function allStrategies(catalog: string[], byTf: Record<string, string[]>, chosen: string[]): string[] {
  const out: string[] = [];
  for (const k of [...catalog, ...Object.values(byTf).flat(), ...chosen]) if (!out.includes(k)) out.push(k);
  return out;
}

/** The chart's companion timeframe for support / resistance (about 3-4 times bigger). */
export const COMPANION_TF: Record<string, string> = {
  "1m": "5m", "3m": "15m", "5m": "15m", "15m": "1h", "30m": "4h", "1h": "4h", "4h": "1d",
};

/** Support and resistance from swing highs / lows (a candle higher or lower than `pivot` candles on each
 * side), the nearest `each` above and below the price; levels closer than `merge` (share) are one. */
export function swingLevels(candles: { high: number; low: number; close: number }[], price: number,
  pivot = 3, each = 2, merge = 0.0015, lookback = 300): { above: number[]; below: number[] } {
  const c = candles.slice(-lookback);
  const highs: number[] = [], lows: number[] = [];
  for (let i = pivot; i < c.length - pivot; i++) {
    let hi = true, lo = true;
    for (let j = i - pivot; j <= i + pivot; j++) {
      if (j === i) continue;
      if (c[j].high >= c[i].high) hi = false;
      if (c[j].low <= c[i].low) lo = false;
    }
    if (hi) highs.push(c[i].high);
    if (lo) lows.push(c[i].low);
  }
  const pick = (xs: number[], up: boolean) => {
    const out: number[] = [];
    for (const x of xs.filter((x) => (up ? x > price : x < price)).sort((a, b) => (up ? a - b : b - a))) {
      if (out.every((y) => Math.abs(y - x) / x > merge)) out.push(x);
      if (out.length >= each) break;
    }
    return out;
  };
  return { above: pick([...highs, ...lows], true), below: pick([...highs, ...lows], false) };
}

/** The profit-lock point and the stop after the lock of a position (its own setting, else the panel's);
 * null when the lock is off or already happened. */
export function lockPrices(p: PaperPosition, lock: { enabled: boolean; trigger: number; at: number } | undefined,
  target: number = p.takeProfit): { point: number; stopAfter: number; trigger: number; at: number } | null {
  if (!lock?.enabled || p.lockedAt) return null;
  const own = p.lockOwn;
  const trigger = own ? own.trigger : lock.trigger / 100;
  const at = own ? own.at : lock.at / 100;
  const way = target - p.entryPrice;
  return { point: p.entryPrice + way * trigger, stopAfter: p.entryPrice + way * at, trigger, at };
}

/** The bot's own words on why it entered a position (the "explanation" button). */
export function explainLines(p: PaperPosition, t: (k: MessageKey, v?: Record<string, string>) => string,
  digits: number): string[] {
  const w = p.why ?? {};
  const out: string[] = [];
  const side = t(p.side === "long" ? "strategies.long" : "strategies.short");
  out.push(t("why.head", { strategy: t(`strat.${p.strategy}` as MessageKey), tf: p.timeframe, side }));
  out.push(t(`why.rule.${p.strategy}` as MessageKey));
  if (p.history) out.push(t("why.history", { trades: String(p.history.trades),
    win: p.history.winRate == null ? "–" : String(Math.round(p.history.winRate)),
    pf: p.history.profitFactor == null ? "∞" : p.history.profitFactor.toFixed(2) }));
  if (w.marketState) out.push(t("why.state", { state: t(`state.${w.marketState}` as MessageKey) }));
  if (p.trend) out.push(t("why.trend", { tf: w.higherTf ?? "", trend: t(`bot.trend.${p.trend}` as MessageKey) }));
  if (p.btcLink != null) {
    out.push(p.btcLink >= 0.2
      ? t("why.follower", { corr: p.btcLink.toFixed(2), trend: p.btcTrend ? t(`bot.trend.${p.btcTrend}` as MessageKey) : "–" })
      : t("why.independent", { corr: p.btcLink.toFixed(2) }));
  }
  if (w.signalPrice != null) {
    const diff = (p.entryPrice - w.signalPrice) / w.signalPrice * 100 * (p.side === "long" ? 1 : -1);
    out.push(t("why.price", { signal: formatPrice(w.signalPrice, digits), entry: formatPrice(p.entryPrice, digits),
      better: diff <= 0 ? t("why.better") : t("why.later", { pct: Math.abs(diff).toFixed(2) }),
      type: t(p.entryType === "limit" ? "bot.entry.limit" : "bot.entry.market") }));
  }
  if (w.reward != null) out.push(t("why.reward", { rr: w.reward.toFixed(1) }));
  if (w.feeShare != null) out.push(t("why.fee", { pct: String(Math.round(w.feeShare * 100)) }));
  if (w.chance != null) out.push(t("why.brain", { pct: String(Math.round(w.chance * 100)) }));
  return out;
}

/** A list after ticking (on) or unticking (off) one item, in the order of `order`. Built from the latest
 * choice, so quick ticks one after another all count. */
export function toggled<T>(order: readonly T[], chosen: readonly T[], item: T, on: boolean): T[] {
  return order.filter((x) => (x === item ? on : chosen.includes(x)));
}

/** Is this focused element one the owner types in (the panel then waits with redrawing)? Checkboxes,
 * radio buttons and buttons are not: on Windows they keep the focus after a click. */
export function typingField(tag: string, inputType: string): boolean {
  if (tag.toUpperCase() === "TEXTAREA") return true;
  if (tag.toUpperCase() !== "INPUT") return false;
  return ["text", "number", "search", "password", "email", "url", "range", ""].includes(inputType.toLowerCase());
}

/** Price where the profit lock moves the stop (lock.trigger % of the way to this target), or null. */
export function lockTrigger(p: PaperPosition, lock: { enabled: boolean; trigger: number } | undefined,
  target: number = p.takeProfit): number | null {
  if (!lock?.enabled || p.lockedAt) return null;
  return p.entryPrice + (target - p.entryPrice) * lock.trigger / 100;
}

/** Is the profit lock setting valid: 0 < at < trigger < 100. */
export function lockValid(trigger: number, at: number): boolean {
  return Number.isFinite(trigger) && Number.isFinite(at) && at > 0 && at < trigger && trigger < 100;
}

/** "12 s" / "3 min" left until a waiting limit order is cancelled. */
export function timeLeft(seconds: number): { n: string; unit: "s" | "m" } {
  const s = Math.max(0, Math.round(seconds));
  return s < 120 ? { n: String(s), unit: "s" } : { n: String(Math.round(s / 60)), unit: "m" };
}

/** A bot position or trade in the chart's format (arrows and boxes). */
export function paperAsTrade(p: PaperPosition | PaperTrade): Trade {
  const closed = "exitPrice" in p && p.exitPrice !== undefined;
  const t = closed ? (p as PaperTrade) : null;
  const percent = t ? (t.pnl / p.notional) * 100 : null; // of the position value, like the strategy results
  return {
    side: p.side,
    signalTime: p.entryCandle,
    entryTime: p.entryCandle,
    entryPrice: p.entryPrice,
    stopLoss: p.stopLoss,
    takeProfit: p.takeProfit,
    exitTime: t ? candleStart(t.exitTime, p.timeframe) : null,
    exitPrice: t ? t.exitPrice : null,
    exitReason: t ? t.exitReason : null,
    breakevenTime: p.breakevenAt,
    result: !t ? "open" : { win: "win", loss: "loss", even: "breakeven" }[tradeOutcome(t)] as Trade["result"],
    pnlPercent: percent,
    grossPercent: null,
    feePercent: null,
    r: null,
  };
}

/** Result of a closed bot trade: break-even when it closed at the break-even stop or the result is
 * practically zero (a tiny fraction of the position), else win or loss. Same rule as the backend. */
export function tradeOutcome(t: PaperTrade): "win" | "loss" | "even" {
  if (t.exitReason === "breakeven" || t.exitReason === "timeBe" || Math.abs(t.pnl) < t.notional * 1e-4) return "even";
  return t.pnl > 0 ? "win" : "loss";
}

/** What the status line says. */
export function statusKey(s: PaperState): MessageKey {
  if (s.status === "halted") return "bot.halted";
  if (s.status === "stopped") return "bot.statusStopped";
  if (s.pausedUntil !== null && s.pausedUntil > Date.now() / 1000) return "bot.paused";
  if (s.scanning) return "bot.scanning";
  return s.positions.length ? "bot.watching" : "bot.waiting";
}

/** Which chart to show when nothing was clicked: the newest open position, else the last trade. */
export function defaultTarget(s: PaperState): { symbol: string; timeframe: string; id: number | null } {
  const p = s.positions[s.positions.length - 1] ?? s.closed[0];
  return p ? { symbol: p.symbol, timeframe: p.timeframe, id: p.id } : { symbol: "BTC/USDT:USDT", timeframe: "15m", id: null };
}

/** "+1.25" / "−0.40" (USDT). */
export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const fixed = Math.abs(value).toFixed(2);
  if (fixed === "0.00") return "0.00";
  return `${value > 0 ? "+" : "−"}${fixed}`;
}

/** One line of the bot's diary. */
export function eventText(e: PaperEvent, t: (key: MessageKey, p?: Record<string, string>) => string): string {
  const side = e.side ? t(e.side === "long" ? "strategies.long" : "strategies.short") : "";
  switch (e.kind) {
    case "open": {
      const line = t("bot.evOpen", { coin: e.symbol ?? "", side, tf: e.timeframe ?? "", lev: String(e.leverage ?? 1),
        strategy: t(`strat.${e.strategy}` as MessageKey) });
      return e.entryType === "limit" ? `${line} ${t("bot.entry.limitTag")}` : line;
    }
    case "close":
      return t("bot.evClose", { coin: e.symbol ?? "", result: formatMoney(e.pnl), reason: t(`bot.reason.${e.reason}` as MessageKey) });
    case "halted":
      return t("bot.evHalted");
    case "skip":
      if (e.reason === "brain") return t("bot.evBrain", { tf: e.timeframe ?? "", n: String(e.count ?? 0) });
      return e.reason === "full"
        ? t("bot.evFull", { tf: e.timeframe ?? "", n: String(e.count ?? 0) })
        : t("bot.evSkip", { coin: e.symbol ?? "", tf: e.timeframe ?? "", reason: t(`bot.skip.${e.reason}` as MessageKey) });
    case "pause":
      return t("bot.evPause", {
        reason: t(e.reason === "streak" ? "bot.pause.streak" : "bot.pause.fall"),
        left: e.strategies?.length ? t("bot.evBenched", { list: e.strategies.map((k) => t(`strat.${k}` as MessageKey)).join("، ") }) : "",
      });
    case "resume":
      return e.reason === "recovered" ? t("bot.evResumeEarly", { n: "2" }) : t("bot.evResume");
    case "advice":
      return t("bot.evAdvice", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        suggest: t(e.suggest === "close" ? "bot.advice.suggest.close" : "bot.advice.suggest.hold") });
    case "ai":
      return t(e.approve ? "bot.evAiYes" : "bot.evAiNo", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        conf: e.confidence == null ? "–" : String(Math.round(e.confidence)), text: e.text ?? "" });
    case "ask":
      return t("bot.evAsk", { coin: e.symbol ?? "", tf: e.timeframe ?? "" });
    case "askAnswer":
      return t(e.answer === "open" ? "bot.evAskOpen" : e.answer === "auto" ? "bot.evAskAuto" : "bot.evAskSkip",
        { coin: e.symbol ?? "", tf: e.timeframe ?? "" });
    case "levels": {
      const digits = pricePrecision(e.new ?? 0);
      return t(e.what === "target" ? "bot.evTargetMoved" : "bot.evStopMoved", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        old: formatPrice(e.old ?? 0, digits), new: formatPrice(e.new ?? 0, digits) });
    }
    case "reviewAsk":
      return t("bot.event.reviewAsk", { symbol: e.symbol ?? "", timeframe: e.timeframe ?? "", pnl: formatMoney(e.pnl) });
    case "timeBeAsk":
      return t("bot.event.timeBeAsk", { symbol: e.symbol ?? "", timeframe: e.timeframe ?? "", pnl: formatMoney(e.pnl) });
    case "reviewAnswer":
      return t("bot.event.reviewAnswer", { symbol: e.symbol ?? "", timeframe: e.timeframe ?? "",
        answer: (e as { answer?: string }).answer === "close" ? t("bot.review.answerClose") : t("bot.review.answerHold") });
    case "consult":
      return t("bot.evConsult", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        answer: e.suggest === "exit" ? t("consult.ai.exit") : e.suggest === "move_stop" ? t("bot.evConsultMove")
          : e.suggest === "hold" ? t("consult.ai.hold") : "–" });
    case "blind": {
      const hm = (sec: number | undefined) => new Date((sec ?? 0) * 1000).toTimeString().slice(0, 5);
      return t(e.filled ? "bot.evBlindFilled" : "bot.evBlindStop", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        from: hm(e.start), to: hm(e.end) });
    }
    case "order":
      return t("bot.evOrder", { coin: e.symbol ?? "", side, tf: e.timeframe ?? "",
        price: formatPrice(e.price ?? 0, pricePrecision(e.price ?? 0)) });
    case "orderCancel":
      return t("bot.evOrderCancel", { coin: e.symbol ?? "", tf: e.timeframe ?? "",
        why: t(`bot.orderWhy.${e.detail ?? "time"}` as MessageKey) });
    case "pretrain":
      return t("bot.evPretrain", { n: String(e.count ?? 0) });
    case "brain":
      return t(`bot.evLearn.${e.reason}` as MessageKey, { version: String(e.version ?? "") });
    case "reset":
      return t("bot.evReset", { capital: String(e.capital ?? "") });
    case "start":
      return t("bot.evStart");
    case "stop":
      return t("bot.evStop");
    case "coinPause":
      return t("bot.evCoinPause", { coin: e.symbol ?? "", hours: String(e.hours ?? "") });
    case "focus":
      return t(e.on ? "bot.evFocusOn" : "bot.evFocusOff");
    default:
      return t("bot.evError", { message: e.message ?? "" });
  }
}

/** "+0.12" / "−0.40" for an average R, "—" without a value. */
export function formatR(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;
}

/** The brain's status line. */
export function brainText(b: BrainState, t: (key: MessageKey, p?: Record<string, string>) => string): string {
  const m = b.model;
  if (b.state === "collecting" || !m) {
    return t("bot.brain.collecting", { samples: String(b.samples), needed: String(b.needed) });
  }
  if (b.state === "off") return t("bot.brain.off", { version: String(m.version) });
  const { kept, all } = m.test;
  return t("bot.brain.active", {
    version: String(m.version), kept: String(kept.count), all: String(all.count),
    on: t(m.testedOn === "history" ? "bot.brain.onHistory" : "bot.brain.onLive"),
    keptR: formatR(kept.avgR), allR: formatR(all.avgR), win: kept.winRate === null ? "—" : kept.winRate.toFixed(0),
  });
}

/** The bot's half-way advice for one position, as one line. */
export function adviceText(p: PaperPosition, t: (key: MessageKey, p?: Record<string, string>) => string): string {
  const a = p.advice;
  if (!a) return "";
  const detail = a.reason === "opposite" ? t(`strat.${a.detail}` as MessageKey)
    : a.reason === "state" ? t(`state.${a.detail}` as MessageKey) : "";
  return t("bot.advice.line", {
    coin: p.base, tf: p.timeframe, pnl: formatMoney(a.pnl),
    suggest: t(a.suggest === "close" ? "bot.advice.suggest.close" : "bot.advice.suggest.hold"),
    why: t(`bot.advice.why.${a.reason}` as MessageKey, { detail }),
  });
}


/** Strategies with the best average result of their signals first; those without results keep their place at the end. */
export function strategyOrder(kinds: string[], stats: Record<string, StrategyResults>): string[] {
  const score = (k: string) => stats[k]?.signals?.avgR;
  return [...kinds].sort((a, b) => {
    const sa = score(a), sb = score(b);
    if (sa == null && sb == null) return 0;
    if (sa == null) return 1;
    if (sb == null) return -1;
    return sb - sa;
  });
}

/** Timeframes each strategy is traded on, from the bot's list (timeframe -> strategies). */
export function timeframesOf(botStrategies: Record<string, string[]>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const tf of Object.keys(TIMEFRAME_SECONDS)) {
    for (const kind of botStrategies[tf] ?? []) (out[kind] ??= []).push(tf);
  }
  return out;
}

/** The smart-pause part of the rules line; a rule set to 0 by the owner is off. */
export function pauseRuleText(
  rules: PaperState["rules"], t: (key: MessageKey, p?: Record<string, string>) => string,
): string {
  const losses = rules.pauseLosses ?? 4;
  const fall = rules.pauseFall ?? 5;
  const p = { losses: String(losses), fall: String(fall), hours: String(rules.pauseHours ?? 3),
    wins: String(rules.recoverWins ?? 2) };
  if (losses > 0 && fall > 0) return t("bot.pauseRule.both", p);
  if (losses > 0) return t("bot.pauseRule.losses", p);
  if (fall > 0) return t("bot.pauseRule.fall", p);
  return t("bot.pauseRule.off");
}

/** The line under the brain knob: what the bot uses now. */
export function brainKnobHint(
  set: number | null | undefined, own: number | null, t: (key: MessageKey, p?: Record<string, string>) => string,
): string {
  if (set == null) return t("bot.brainHint.auto", { own: own == null ? "–" : String(own) });
  if (set <= 0) return t("bot.brainHint.off");
  return t("bot.brainHint.set", { value: String(Math.round(set * 100)), own: own == null ? "–" : String(own) });
}

/** Timeframes offered above the bot's chart. */
export const CHART_TFS = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"];

/** Groups of things drawn on the bot's chart, each with its own eye button. */
export const EYE_GROUPS = ["boxes", "markers", "levels", "lock", "liquidation", "orders", "strategy", "srChart", "srHigher"] as const;
export type EyeGroup = (typeof EYE_GROUPS)[number];
const EYE_KEY = "bot.eye";

/** Which groups are shown; all on unless the owner hid them (kept in this browser). */
export function loadEye(read: () => string | null = () => localStorage.getItem(EYE_KEY)): Record<EyeGroup, boolean> {
  const eye = Object.fromEntries(EYE_GROUPS.map((g) => [g, true])) as Record<EyeGroup, boolean>;
  try {
    const saved = JSON.parse(read() ?? "{}") as Record<string, unknown>;
    for (const g of EYE_GROUPS) if (saved[g] === false) eye[g] = false;
  } catch {
    // all shown
  }
  return eye;
}

export function saveEye(eye: Record<EyeGroup, boolean>): void {
  try {
    localStorage.setItem(EYE_KEY, JSON.stringify(eye));
  } catch {
    // not kept
  }
}

/** Lines of the bot's chart whose colour, style and width the owner sets (gear next to the eye). */
export const LINE_GROUPS = ["entry", "stop", "target", "liquidation", "lockPoint", "lockStop", "breakeven", "orders",
  "strategy", "resChart", "supChart", "resHigher", "supHigher"] as const;
export type LineGroup = (typeof LINE_GROUPS)[number];
export type LineStyleName = "solid" | "dashed" | "dotted";
export interface LineLook { color: string; style: LineStyleName; width: number }
export const LINE_DEFAULTS: Record<LineGroup, LineLook> = {
  entry: { color: "#2962ff", style: "dotted", width: 1 },
  stop: { color: "#f23645", style: "dotted", width: 1 },
  target: { color: "#089981", style: "dotted", width: 1 },
  liquidation: { color: "#ff9800", style: "dashed", width: 1 },
  lockPoint: { color: "#b388ff", style: "solid", width: 2 },
  lockStop: { color: "#b388ff", style: "dashed", width: 2 },
  breakeven: { color: "#787b86", style: "dashed", width: 2 },
  orders: { color: "#2962ff", style: "dashed", width: 1 },
  strategy: { color: "", style: "solid", width: 2 },   // colours come from the strategy
  resChart: { color: "#f23645", style: "dashed", width: 1 },
  supChart: { color: "#089981", style: "dashed", width: 1 },
  resHigher: { color: "#f23645", style: "dashed", width: 2 },
  supHigher: { color: "#089981", style: "dashed", width: 2 },
};
const LINES_KEY = "bot.lines";

/** The owner's line settings on this computer; anything missing or broken -> the default. */
export function loadLines(read: () => string | null = () => localStorage.getItem(LINES_KEY)): Record<LineGroup, LineLook> {
  const out = Object.fromEntries(LINE_GROUPS.map((g) => [g, { ...LINE_DEFAULTS[g] }])) as Record<LineGroup, LineLook>;
  let saved: Record<string, Partial<LineLook>> = {};
  try {
    saved = JSON.parse(read() ?? "{}") ?? {};
  } catch {
    return out;
  }
  for (const g of LINE_GROUPS) {
    const x = saved[g];
    if (!x || typeof x !== "object") continue;
    if (typeof x.color === "string" && /^#[0-9a-f]{6}$/i.test(x.color)) out[g].color = x.color;
    if (x.style === "solid" || x.style === "dashed" || x.style === "dotted") out[g].style = x.style;
    if (typeof x.width === "number" && x.width >= 1 && x.width <= 4) out[g].width = Math.round(x.width);
  }
  return out;
}

export function saveLines(lines: Record<LineGroup, LineLook>): void {
  try {
    localStorage.setItem(LINES_KEY, JSON.stringify(lines));
  } catch {
    // not kept
  }
}

/** Sections of the bot's settings panel that open and close. */
export type PanelSection = "timeframes" | "limit" | "ai" | "tg" | "coins" | "strategies" | "lock" | "review" | "memory"
  | "brain" | "connection" | "history" | "diary";
const FOLDS_KEY = "bot.sections";
/** Open at first (owner 2026-11-09): the timeframes; a section with a switch while it is on. */
const OPEN_FIRST: PanelSection[] = ["timeframes"];

export function sectionOpen(id: PanelSection, folds: Partial<Record<PanelSection, boolean>>, on?: boolean): boolean {
  if (folds[id] !== undefined) return folds[id]!;
  if (on !== undefined) return on;
  return OPEN_FIRST.includes(id);
}

export function loadFolds(read: () => string | null = () => localStorage.getItem(FOLDS_KEY)): Partial<Record<PanelSection, boolean>> {
  try {
    const x = JSON.parse(read() ?? "{}") as Record<string, unknown>;
    return Object.fromEntries(Object.entries(x).filter(([, v]) => typeof v === "boolean")) as Partial<Record<PanelSection, boolean>>;
  } catch {
    return {};
  }
}

export function saveFolds(folds: Partial<Record<PanelSection, boolean>>): void {
  try {
    localStorage.setItem(FOLDS_KEY, JSON.stringify(folds));
  } catch {
    // not kept
  }
}
