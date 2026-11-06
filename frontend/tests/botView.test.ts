import assert from "node:assert/strict";
import { test } from "node:test";
import { adviceText, allStrategies, brainKnobHint, brainText, breakevenTrigger, formatR, lockTrigger, lockValid, timeLeft, toggled, typingField, defaultTarget, levelProblem, resultAt, eventText, formatMoney, paperAsTrade, pauseRuleText, statusKey, strategyOrder, timeframesOf, tradeOutcome } from "../src/botView.ts";
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
    "مکث ۳ ساعته: باخت‌های پشت سر هم. کنار گذاشته شد برای ۳ ساعت: شکست کانال");
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
    "فیلتر روشن است (مدل شماره‌ی 2). روی سیگنال‌های واقعی‌ای که ندیده بود، از 120 سیگنال قابل اعتماد 40 تا را قبول کرد: میانگین +0.35R در برابر −0.05R برای همه، 45٪ برد.");
  assert.equal(eventText({ time: 0, kind: "skip", timeframe: "1m", reason: "brain", count: 3 }, t), "1m: هوش ربات 3 سیگنال ضعیف را رد کرد");
  assert.equal(eventText({ time: 0, kind: "pretrain", count: 1200 }, t), "پیش‌آموزش: 1200 سیگنال گذشته از تاریخچه به حافظه اضافه شد");
  assert.equal(eventText({ time: 0, kind: "brain", reason: "promoted", version: 2 }, t),
    "هوش ربات یاد گرفت: مدل جدید شماره‌ی 2 به کار افتاد");
});

test("break-even trades are grey, not losses", () => {
  const base = { notional: 100, exitReason: "stop" } as unknown as PaperTrade;
  assert.equal(tradeOutcome({ ...base, pnl: -1e-9 }), "even");
  assert.equal(tradeOutcome({ ...base, pnl: -0.02, exitReason: "breakeven" }), "even");
  assert.equal(tradeOutcome({ ...base, pnl: -0.5 }), "loss");
  assert.equal(tradeOutcome({ ...base, pnl: 1.05, exitReason: "target" }), "win");
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  assert.equal(eventText({ time: 0, kind: "resume", reason: "recovered" }, t), "مکث زودتر تمام شد: 2 نتیجه‌ی آخر سود بود، معامله ادامه دارد");
});

test("half-way advice in plain words", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  const p = { base: "LIT2", timeframe: "3m",
    advice: { time: 0, suggest: "close", reason: "opposite", detail: "supertrend", pnl: 0.42, answer: null } } as unknown as PaperPosition;
  assert.equal(adviceText(p, t),
    "LIT2 3m: به نیمه‌ی راه حد سود رسید (+0.42 USDT). پیشنهاد: بستن. استراتژی «سوپرترند» الان سیگنال قابل اعتماد خلاف جهت داده.");
  assert.equal(eventText({ time: 0, kind: "advice", symbol: "LIT2", timeframe: "3m", suggest: "hold" }, t),
    "LIT2 3m به نیمه‌ی راه حد سود رسید؛ پیشنهاد ربات: ادامه");
});

test("manual list: strategies with the best signal results first, unknown ones last", () => {
  const order = strategyOrder(["a", "b", "c", "d"], {
    a: { signals: { count: 10, winRate: 30, avgR: -0.3 } },
    c: { signals: { count: 5, winRate: 60, avgR: 0.2 } },
    d: { bot: { count: 2, winRate: 50, netPnl: 1 } },
  });
  assert.deepEqual(order, ["c", "a", "b", "d"]);
});

test("strategy stat lines exist in both languages", () => {
  for (const lang of ["fa", "en"] as const) {
    assert.match(translate(lang, "bot.statSignals", { n: "3", win: "50", r: "+0.20" }), /3.*50.*\+0\.20/);
    assert.match(translate(lang, "bot.statBrain", { n: "2", win: "40", r: "-0.10" }), /2.*40.*-0\.10/);
  }
});

test("bot list: the timeframes each strategy is traded on, fastest first", () => {
  assert.deepEqual(timeframesOf({ "1h": ["macd_ema"], "1m": [], "3m": ["macd_ema", "sd_zone"] }),
    { macd_ema: ["3m", "1h"], sd_zone: ["3m"] });
});

test("pause rule text follows the owner's numbers (0 = off)", () => {
  const tr = (key: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("en", key, p);
  const rules = state().rules;
  assert.match(pauseRuleText({ ...rules, pauseLosses: 6, pauseFall: 8 }, tr), /after 6 losses in a row or a 8% fall/);
  assert.match(pauseRuleText({ ...rules, pauseLosses: 0, pauseFall: 5 }, tr), /^3-hour pause after a 5% fall/);
  assert.match(pauseRuleText({ ...rules, pauseLosses: 4, pauseFall: 0 }, tr), /after 4 losses in a row \(/);
  assert.equal(pauseRuleText({ ...rules, pauseLosses: 0, pauseFall: 0 }, tr), "automatic pause off");
  assert.match(pauseRuleText(rules, tr), /after 4 losses in a row or a 5% fall/);   // defaults
});

test("brain knob hint: auto, owner's number, off", () => {
  const tr = (key: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("en", key, p);
  assert.match(brainKnobHint(null, 34, tr), /^Auto: the brain's own threshold \(34%\)/);
  assert.match(brainKnobHint(0.25, 34, tr), /^Your threshold: 25% \(the brain's own is 34%\)/);
  assert.match(brainKnobHint(0, 34, tr), /^0%: the brain filter is off/);
});

test("AI events in the diary", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("en", k, p);
  assert.equal(eventText({ time: 0, kind: "ai", symbol: "RLC", timeframe: "1h", approve: false, confidence: 35, text: "late entry" }, t),
    "The AI rejected RLC (1h) (confidence 35%): late entry");
  assert.equal(eventText({ time: 0, kind: "ask", symbol: "RLC", timeframe: "1h" }, t), "The AI did not answer for RLC (1h); waiting for you");
  assert.equal(eventText({ time: 0, kind: "askAnswer", symbol: "RLC", timeframe: "1h", answer: "open" }, t), "RLC (1h) opened by your choice");
});

test("a dragged stop or target is checked like the bot does", () => {
  // long at 100, liquidation 67, price now 101
  assert.equal(levelProblem(position, "stop", 99.5, 101), null);
  assert.equal(levelProblem(position, "stop", 101.2, 101), "stop_side");
  assert.equal(levelProblem(position, "stop", 66, 101), "stop_liquidation");
  assert.equal(levelProblem(position, "target", 100.5, 101), "target_side");
  assert.equal(levelProblem(position, "target", 103, 101), null);
  const short = { ...position, side: "short" as const, liquidation: 133 };
  assert.equal(levelProblem(short, "stop", 100.5, 101), "stop_side");
  assert.equal(levelProblem(short, "stop", 134, 99), "stop_liquidation");
  assert.equal(levelProblem(short, "target", 98, 99), null);
});

test("the label shows the USDT result at the dragged price, fees paid", () => {
  // 1 coin at 100: stop 98 loses 2 + 0.06 in + 0.0588 out
  assert.ok(Math.abs(resultAt(position, 98, 0.06, 0.06) - (-2.1188)) < 1e-9);
  assert.ok(Math.abs(resultAt(position, 103, 0.06, 0.02) - (3 - 0.06 - 0.0206)) < 1e-9);
});

test("the break-even point follows the target and goes away when off or done", () => {
  const p = { ...position, breakevenPart: 0.5 };
  assert.equal(breakevenTrigger(p), 101);
  assert.equal(breakevenTrigger(p, 104), 102);
  assert.equal(breakevenTrigger({ ...p, breakevenAt: 5 }), null);
  assert.equal(breakevenTrigger(position), null);
});

test("the owner's moved line is in the diary", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  const text = eventText({ time: 1, kind: "levels", symbol: "BTC", timeframe: "1h", what: "stop", old: 1, new: 1.2 }, t);
  assert.ok(text.includes("1.2") && text.includes("BTC"));
});

test("waiting limit orders: time left and the diary lines", () => {
  assert.deepEqual(timeLeft(42.4), { n: "42", unit: "s" });
  assert.deepEqual(timeLeft(600), { n: "10", unit: "m" });
  assert.deepEqual(timeLeft(-5), { n: "0", unit: "s" });
  assert.equal(formatR(-0.123), "−0.12");
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  const placed = eventText({ time: 1, kind: "order", symbol: "SOL", timeframe: "15m", side: "long", price: 99.9 }, t);
  assert.ok(placed.includes("SOL") && placed.includes("99.9"));
  for (const why of ["time", "target", "stop", "off", "botStop", "reset", "halted", "fee", "reward", "full"]) {
    const text = eventText({ time: 1, kind: "orderCancel", symbol: "SOL", timeframe: "15m", detail: why }, t);
    assert.ok(!text.includes("bot.orderWhy"), `missing text for ${why}`);
  }
  for (const reason of ["limit_expired", "limit_cancelled"]) {
    assert.notEqual(translate("fa", `bot.skip.${reason}` as Parameters<typeof translate>[1]), `bot.skip.${reason}`);
  }
});

test("quick ticks one after another all count (the Windows bug)", () => {
  const all = ["1m", "3m", "5m", "15m", "30m", "1h", "4h"];
  let chosen = ["5m", "15m", "30m", "1h"];
  chosen = toggled(all, chosen, "5m", false);     // untick 5m
  chosen = toggled(all, chosen, "30m", false);    // then 30m: built on the first change, 5m stays off
  chosen = toggled(all, chosen, "4h", true);
  assert.deepEqual(chosen, ["15m", "1h", "4h"]);
});

test("a ticked checkbox is not typing; text boxes and the slider are", () => {
  assert.equal(typingField("INPUT", "checkbox"), false);
  assert.equal(typingField("INPUT", "radio"), false);
  assert.equal(typingField("BUTTON", ""), false);
  assert.equal(typingField("INPUT", "number"), true);
  assert.equal(typingField("INPUT", "search"), true);
  assert.equal(typingField("INPUT", "range"), true);
  assert.equal(typingField("TEXTAREA", ""), true);
});

test("profit lock point follows the target; off or done shows none; settings checked", () => {
  // entry 100, target 102: 80% of the way is 101.6
  assert.equal(lockTrigger(position, { enabled: true, trigger: 80 }), 101.6);
  assert.equal(lockTrigger(position, { enabled: true, trigger: 80 }, 110), 108);
  assert.equal(lockTrigger(position, { enabled: false, trigger: 80 }), null);
  assert.equal(lockTrigger({ ...position, lockedAt: 5 }, { enabled: true, trigger: 80 }), null);
  assert.equal(lockValid(80, 40), true);
  assert.equal(lockValid(40, 80), false);
  assert.equal(lockValid(100, 40), false);
  assert.equal(lockValid(80, 0), false);
});

test("a limit entry says so in the diary; the lock exit has its words", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  const e = { time: 1, kind: "open" as const, symbol: "AGT", side: "short" as const, timeframe: "3m", strategy: "donchian", leverage: 4 };
  assert.ok(eventText({ ...e, entryType: "limit" }, t).endsWith("(لیمیت)"));
  assert.ok(!eventText(e, t).includes("لیمیت"));
  assert.equal(translate("fa", "bot.reason.lock"), "قفل سود");
});

test("the diary says when the bot did not see the prices", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  const filled = eventText({ time: 1, kind: "blind", symbol: "CLANKER", timeframe: "3m", start: 0, end: 3600, filled: true }, t);
  const stop = eventText({ time: 1, kind: "blind", symbol: "CLANKER", timeframe: "3m", start: 0, end: 3600, filled: false }, t);
  assert.ok(filled.includes("CLANKER") && filled.includes("صرافی خوانده"));
  assert.ok(stop.includes("همان قیمت"));
});

test("the manual list keeps the unticked strategies when the catalog did not load", () => {
  const byTf = { "15m": ["ema_cross", "supertrend", "fvg_retest"], "1h": ["supertrend", "ichimoku"] };
  assert.deepEqual(allStrategies([], byTf, ["supertrend"]), ["ema_cross", "supertrend", "fvg_retest", "ichimoku"]);
  assert.deepEqual(allStrategies(["ichimoku", "ema_cross"], byTf, []), ["ichimoku", "ema_cross", "supertrend", "fvg_retest"]);
});

test("the diary line of a stay-or-exit question", () => {
  const t = (k: Parameters<typeof translate>[1], p?: Record<string, string>) => translate("fa", k, p);
  for (const [suggest, word] of [["exit", "خارج"], ["move_stop", "حد ضرر"], ["hold", "بمان"]] as const) {
    assert.ok(eventText({ time: 1, kind: "consult", symbol: "ON", timeframe: "30m", suggest }, t).includes(word));
  }
});
