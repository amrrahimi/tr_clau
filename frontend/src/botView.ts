// Small pieces of the automatic (bot) screen without screen code, so they can be tested.

import type { MessageKey } from "./locales/en.ts";
import type { PaperEvent, PaperPosition, PaperState, PaperTrade, Trade } from "./types.ts";

export const TIMEFRAME_SECONDS: Record<string, number> = {
  "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
};

function candleStart(time: number, timeframe: string): number {
  const step = TIMEFRAME_SECONDS[timeframe] ?? 60;
  return Math.floor(time / step) * step;
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
    result: !t ? "open" : t.pnl > 0 ? "win" : t.exitReason === "breakeven" && Math.abs(t.pnl) < p.notional * 1e-4 ? "breakeven" : "loss",
    pnlPercent: percent,
    grossPercent: null,
    feePercent: null,
    r: null,
  };
}

/** What the status line says. */
export function statusKey(s: PaperState): MessageKey {
  if (s.status === "halted") return "bot.halted";
  if (s.status === "stopped") return "bot.statusStopped";
  if (s.pausedToday) return "bot.pausedToday";
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
    case "open":
      return t("bot.evOpen", { coin: e.symbol ?? "", side, tf: e.timeframe ?? "", lev: String(e.leverage ?? 1),
        strategy: t(`strat.${e.strategy}` as MessageKey) });
    case "close":
      return t("bot.evClose", { coin: e.symbol ?? "", result: formatMoney(e.pnl), reason: t(`bot.reason.${e.reason}` as MessageKey) });
    case "halted":
      return t("bot.evHalted");
    case "skip":
      return e.reason === "full"
        ? t("bot.evFull", { tf: e.timeframe ?? "", n: String(e.count ?? 0) })
        : t("bot.evSkip", { coin: e.symbol ?? "", tf: e.timeframe ?? "", reason: t(`bot.skip.${e.reason}` as MessageKey) });
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
