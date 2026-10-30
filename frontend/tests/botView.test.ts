import assert from "node:assert/strict";
import { test } from "node:test";
import { brainText, defaultTarget, eventText, formatMoney, paperAsTrade, statusKey } from "../src/botView.ts";
import { translate } from "../src/i18n.ts";
import type { PaperPosition, PaperState, PaperTrade } from "../src/types.ts";

const position: PaperPosition = {
  id: 7, symbol: "SOL/USDT:USDT", base: "SOL", timeframe: "5m", strategy: "supertrend", side: "long",
  entryTime: 1000, entryPrice: 100, entryCandle: 900, stopLoss: 99, stop: 99, takeProfit: 102,
  quantity: 1, notional: 100, leverage: 3, margin: 33.3, risk: 1, liquidation: 67, breakevenAt: null,
  history: { trades: 20, winRate: 45, profitFactor: 1.5 },
};

function state(over: Partial<PaperState> = {}): PaperState {
  return {
    capital: 100, balance: 100, equity: 100, status: "running", pausedUntil: null, pauseReason: null, benched: {}, memory: null, mode: "auto", strategies: [],
    positions: [], closed: [], events: [],
    stats: { trades: 0, wins: 0, winRate: null, netPnl: 0, netPercent: 0, todayPnl: 0, fees: 0, maxDrawdown: 0 },
    scanning: null, lastScan: {}, timeframes: [],
    rules: { risk: 1, maxOpen: 6, maxLeverage: 10, totalStop: 30, fees: { maker: 0.02, taker: 0.06 } },
    ...over,
  };
}

test("a bot trade becomes chart arrows and boxes on the right candles", () => {
  const open = paperAsTrade(position);
  assert.equal(open.entryTime, 900);
  assert.equal(open.result, "open");
  const closed: PaperTrade = { ...position, exitPrice: 102, exitTime: 1250, exitReason: "target", pnl: 1.9, fees: 0.1, pnlPercent: 5.7 };
  const t = paperAsTrade(closed);
  assert.equal(t.exitTime, 1200);            // the 5m candle that holds 1250
  assert.equal(t.result, "win");
  assert.ok(Math.abs((t.pnlPercent ?? 0) - 1.9) < 1e-9);   // percent of the position value
  assert.equal(paperAsTrade({ ...closed, pnl: -1.1, exitReason: "stop" }).result, "loss");
  assert.equal(paperAsTrade({ ...closed, pnl: 0, exitReason: "breakeven" }).result, "breakeven");
});

test("status line", () => {
  assert.equal(statusKey(state({ status: "stopped" })), "bot.statusStopped");
  assert.equal(statusKey(state({ status: "halted" })), "bot.halted");
  assert.equal(statusKey(state({ pausedUntil: Date.now() / 1000 + 600, pauseReason: "streak" })), "bot.paused");
  assert.equal(statusKey(state({ pausedUntil: Date.now() / 1000 - 600 })), "bot.waiting");   // pause over
  assert.equal(statusKey(state({ scanning: "5m" })), "bot.scanning");
  assert.equal(statusKey(state({ positions: [position] })), "bot.watching");
  assert.equal(statusKey(state()), "bot.waiting");
});

test("chart shows the newest open position, else the last trade, else BTC", () => {
  assert.deepEqual(defaultTarget(state()), { symbol: "BTC/USDT:USDT", timeframe: "15m", id: null });
  assert.deepEqual(defaultTarget(state({ positions: [position] })), { symbol: "SOL/USDT:USDT", timeframe: "5m", id: 7 });
});

test("money and diary texts", () => {
  assert.equal(formatMoney(1.234), "+1.23");
  assert.equal(formatMoney(-0.4), "−0.40");
  assert.equal(formatMoney(0.001), "0.00");
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  assert.equal(eventText({ time: 0, kind: "open", symbol: "BTC", side: "long", timeframe: "5m", strategy: "supertrend", leverage: 3 }, t),
    "باز شد: BTC لانگ 5m ×3 (سوپرترند)");
  assert.equal(eventText({ time: 0, kind: "close", symbol: "BTC", reason: "stop", pnl: -1 }, t), "بسته شد: BTC، −1.00 USDT (حد ضرر)");
});

test("skipped signals say why", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  assert.equal(eventText({ time: 0, kind: "skip", symbol: "LITE", timeframe: "15m", reason: "stale" }, t),
    "رد شد: LITE 15m، سیگنال کهنه بود، قیمت حرکت کرده بود");
  assert.equal(eventText({ time: 0, kind: "skip", timeframe: "5m", reason: "full", count: 4 }, t),
    "5m: 4 سیگنال قابل اعتماد دیگر بود، ولی جای خالی نبود");
});

test("pause in the diary", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  assert.equal(eventText({ time: 0, kind: "pause", reason: "streak", strategies: ["donchian"] }, t),
    "مکث ۳ ساعته: ۴ باخت پشت سر هم. کنار گذاشته شد برای ۱۲ ساعت: شکست کانال");
});

test("the brain in the panel and the diary", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  assert.equal(brainText({ state: "collecting", samples: 42, needed: 300, model: null, lastTraining: null, nextTraining: null }, t),
    "در حال جمع کردن تجربه: 42 از 300 سیگنال نتیجه‌دار. فیلتر بعد از آن شروع به کار می‌کند.");
  const model = {
    version: 2, trainedAt: 0, threshold: 0.4, on: true,
    test: { kept: { count: 40, sumR: 14, avgR: 0.35, winRate: 45 }, all: { count: 120, sumR: -6, avgR: -0.05, winRate: 30 } },
  };
  assert.equal(brainText({ state: "active", samples: 500, needed: 300, model, lastTraining: null, nextTraining: null }, t),
    "فیلتر روشن است (مدل شماره‌ی 2). روی سیگنال‌هایی که ندیده بود 40 از 120 را قبول کرد: میانگین +0.35R در برابر −0.05R برای همه، 45٪ برد.");
  assert.equal(eventText({ time: 0, kind: "skip", timeframe: "1m", reason: "brain", count: 3 }, t), "1m: هوش ربات 3 سیگنال ضعیف را رد کرد");
  assert.equal(eventText({ time: 0, kind: "brain", reason: "promoted", version: 2 }, t),
    "هوش ربات یاد گرفت: مدل جدید شماره‌ی 2 به کار افتاد");
});
