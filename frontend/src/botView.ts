// Small pieces of the automatic (bot) screen without screen code, so they can be tested.

import { pricePrecision } from "./candles.ts";
import { formatPrice } from "./format.ts";
import type { MessageKey } from "./locales/en.ts";
import type { BrainState, PaperEvent, PaperPosition, PaperState, PaperTrade, StrategyResults, Trade } from "./types.ts";

export const TIMEFRAME_SECONDS: Record<string, number> = {
  "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
};

function candleStart(time: number, timeframe: string): number {
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
  if (t.exitReason === "breakeven" || Math.abs(t.pnl) < t.notional * 1e-4) return "even";
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
