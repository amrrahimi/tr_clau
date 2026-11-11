# Handoff for the next session (project status, 2026-11-02)

**Talk to the owner in Persian only.** Learning mode (VibeWise): the owner decides the design;
propose, ask for approval ("پیاده‌سازی این قدم"), then build. After every push wait for CI and send the
download links. The repository is public: never commit keys, passwords or account details.

## Where things are
- Branch `main` holds everything (desktop build runs only on `main`; Android on every branch).
- Desktop: GitHub Actions "Build desktop apps" (Artifacts). Android: release `android-latest`
  (`Leon.apk`, also published as `TradingBot.apk`; installs over the old one). The app is called **Leon** (owner, 2026-11-09). Data: `~/.trading-bot/` (paper.json,
  memory.db, settings.json, backend.log); Android keeps the same files in the app's data folder.
- Backend: `backend/app/` (paper.py bot, strategies.py 18 strategies, brain.py ML filter,
  pretrain.py, memory.py, connection.py proxy, research.py experiments).
  Tests: `cd backend && python -m unittest discover -s tests -t .`; live Toobit check in CI.

## State of the bot
- Main bot: all 18 strategies on the ticked timeframes 1m, 3m, 5m, 15m, 30m, 1h, 4h (30m and 4h added
  2026-11-02; brain signature changed, it learns again from memory); "reliable" rule + brain filter +
  smart pause (owner sets losses in a row / % fall in the panel, 0 = off; defaults 4 / 5%; 3 h; ends
  early after 2 wins; break-even is not a loss); 1% risk; break-even off on 1m-30m, 50% on 1h/4h;
  fee limit per timeframe FEE_RATIO_BY_TF (round-trip fee / stop distance: 3m 10%, others 5%; was 33%);
  half-way advice (hold / close); close buttons; optional profit cap.
- No limit on the number of open positions, per group or per direction (owner 2026-11-02; one per
  coin, stops when free margin runs out; margin per position still at most 1/6 of the money).
  Owner's brain knob in the panel: least chance 0-60% (0 = brain off) or "auto" (the model's own).
  Signals not traded because of a pause / no money are marked in memory (paused / full).
- Coins (owner 2026-11-03): panel section "The bot's coins": top 100 by 24h volume (default), the 30
  most volatile (24h high-low range, at least 1M USDT volume, list renewed hourly), or a manual list
  (search + chips). Kept on "start again" together with the manual strategy choice.
- 2026-11-03 checks: stop at the previous swing high/low raises the win rate (35% -> 46%) but not
  the result; only 16% of stopped trades later reached the target. The 4h result of 2026-11-02 did
  not hold on another top-15 coin list (-0.04 R): needs a 100-coin test. The brain model is "off"
  (it did not beat no filter on unseen signals), so the owner's brain knob has no effect for now.
- AI approval (owner 2026-11-03, backend/app/advisor.py): when on, each chosen signal on the AI's
  timeframes (default 15m-4h; 1m/3m too slow) goes to Gemini (first working of advisor.MODELS, saved as aiModel) with the
  coin on 15m/1h/4h/1d, Bitcoin 1h/4h, nearest swings, last 30 candles and the strategy's record.
  Approve -> trade; reject -> skipped with its Persian reason in the diary; no answer -> the owner is
  asked in the panel (open / skip); with no answer in 30 s it opens by itself. Keys: settings.json
  on the owner's computer only (aiKeys), next key on 429. Every decision is stored in memory
  (ai_decision / ai_confidence / ai_reason) and the panel compares approved vs rejected results.
- Barrage account: removed 2026-11-02 (owner). An old paper-fast.json on disk is no longer used.
- Only ticked timeframes are scanned; a new 1m candle may put a slower scan off once (fix of
  2026-11-02: before it, slow computers never scanned 5m-1h).
- Owner moves stop / target on the chart (2026-11-04, desktop only, mouse): the red and green lines of
  an open position are draggable; the label shows price and USDT result at that price (fees paid);
  takes effect on release (POST /api/paper/levels, PaperBot.set_levels). Rules: stop on the losing
  side of the price now and before liquidation, target on the winning side. Size stays, risk is
  counted again. Break-even trigger follows the new target (grey dashed line "break-even at"), only
  ever moves the stop toward profit; a stop dragged away from break-even re-arms it. Liquidation
  shown as an orange dashed line. Moved trades: "edited" (✎ in the table), event "levels".
- Limit entry (owner's switch, 2026-11-04, paper only, default off; off = exactly as before): a signal
  places a limit order LIMIT_OFFSET (0.1) of the stop distance better than the live price, margin set
  aside, one per coin. Watched on 1m candles: fills only when the price goes beyond it (touch is not
  enough); a minute that reached the target (even if it also crossed) cancels it; fill + stop in the
  same minute = loss; minutes after a late-noticed fill are checked. Expires after LIMIT_EXPIRE_CANDLES (1)
  candle of the signal's timeframe. Cancelled also by switching off, stop, reset, halt. At the fill:
  fee/reward rules again, size at the fill price, maker entry fee, break-even with the maker entry fee
  (breakeven_price(entry_fee=)). Positions keep entryType; panel compares market vs limit (trades, won %,
  average R on the opening risk, fees, fill rate). Memory skip reasons limit_expired / limit_cancelled.
- Fixes of 2026-11-04 (review list): brain champion compared by average R with at least MIN_KEPT signals
  (not the sum); paper exits past the stop at the real price (gap: candle open; live price past the stop:
  that price); one coin's network error no longer stops checking the other positions; live signals keep
  seen_price and are resolved from where and when the bot saw them (older signals: next candle's open);
  tests use a temporary TRADING_BOT_DATA folder (tests/__init__.py); README and paper.py notes updated.
- Panel shows: signals counter (seen / opened / skipped and why), scan times, entry/stop/target lines.

## Honest result so far
History tests (100 Toobit coins, after fees): no strategy has a clear edge; the best are about
break-even; shorter timeframes are worse (fees). The brain filter helps a little. Owner noticed most
signals hit the stop (reversing them would also lose: fees and the reward ratio).

## Findings of 2026-11-02 (bot memory, 169k history + 10k live signals)
- Live signals lose about twice as much as history (-0.16..-0.28 R vs -0.08..-0.15 R): signal delay
  (1m 22 s, 15m 105 s, 1h 6 min after the candle close) and a hard 3-day period.
- With stop = target distance the signals win 50-51%: no direction edge yet. Wider stops (1.5x, 2x) or
  1:1 change the shape, not the result.
- Only pattern stable in both time halves: fee share of the stop distance. Under 5% about break-even,
  above 20% strongly negative. Market state, side, hour, strategy flip between halves (noise).

## Profit cap test of 2026-11-02 (15 top coins, 18 strategies, fee limit 5%, no break-even)
- 4h (5 months, 1056 trades): normal exit +0.11 R (both halves positive), exit at +0.3 R 0.00, +0.5 R +0.04.
- 1h (6 weeks): normal -0.19 R, +0.3 R cap -0.06 R. 30m: too few trades. Owner postponed the decision.

## Untested-strategy check of 2026-11-04 (50 top coins; 5m 7 d, 15m 31 d, 1h 83 d, 4h 333 d; real fees)
- Negative on every timeframe: previous-day high/low break, NR7, RSI divergence (1h ~0), break-and-retest,
  Keltner (4h ~0), Heikin-Ashi, pin bar at swing level, follow-BTC breakout (laggard alts).
- Turtle 55/20 + EMA200 filter on 4h: +0.17 R (halves +0.12/+0.20), 29% wins, median -1 R; all of it
  from ~10 huge trades (without the best 1% ~0). Needs a trailing exit the bot lacks. Owner to decide.
- Funding / OI / long-short not testable yet: no data route.

## Built 2026-11-04 (owner's list, one update)
1. Entry type shown: "Entry" column (limit / market), "(limit)" in the open line of the diary, the chart's
   entry label "limit/market entry · margin$ xleverage".
2. Limit order price rounded to the coin's price step, read from the decimals of its candles (price_step,
   to_step: buy down, sell up); kept unrounded if rounding would reach the stop or pass the price now.
3. Trade size shown: "Money in" (margin, tooltip: loss at the stop) and "Position" (margin x leverage) columns.
4. Profit lock (owner's option, off by default; panel: on/off, trigger %, stop-to %; defaults 80 / 40): at
   trigger % of the way to the target (closed candle high/low or the live price) the stop moves to at %;
   only toward profit, once; exit reason "lock" (🔒 in the stop column); open positions too; the owner
   moving the stop re-arms it; kept on "start again". POST /api/paper/lock. Chart: purple dashed
   "profit lock at" line that follows a dragged target. Tests: 10.7k engine trades -0.103 -> -0.088 R
   (both halves better); the bot's own 27 trades +4.21 -> +7.57 USDT.
5. Ticks coming back on Windows fixed: a focused checkbox no longer counts as "typing" (Windows focuses it
   on click, so the panel stopped redrawing and later ticks undid earlier ones); ticks use the latest
   state (toggled()); a poll answer from before a button press is dropped; /limit answers at once.

## Missed candles (2026-11-05, owner's rule "like an exchange")
CLANKER 3m long lost 8.2 USDT instead of about 2.6: the bot did not watch 01:00-09:22 (computer asleep / no
connection); on waking it read only the last 60 candles, all below the stop, and the 2026-11-04 gap rule exited
at the first one's open. Now positions and limit orders load the missing candles from the long history
(_candles_since) and check them in order (stop, target, break-even, lock at the real candle). If the exchange
cannot give them, a stop/target crossed meanwhile counts at its own price (owner). Diary line "blind".

## Manual strategy list (2026-11-05)
The panel loaded the strategy catalog once at start; when the engine was busy it failed and was never asked
again, so the manual list showed only the ticked strategies (12 disappeared). Now it retries on each poll and
builds the list from the bot's per-timeframe lists meanwhile (allStrategies()).

## Owner 2026-11-05 evening
- "Stale" rule one-sided: a price that moved toward the stop since the signal is a better entry and is
  taken (short signal, price went up); only a move toward the target (late, less profit) is stale. The stop
  (past), fee and reward rules still apply at the price now. Filter on/off switches: cancelled by the owner.
- Half-way "hold or close?" advice switched off (Profile.advice False): the profit lock does its job.

## "Stay or exit?" button (owner 2026-11-06)
Under the chart (right), for each open position of the shown chart; the answer to its left. POST
/api/paper/consult {position_id} -> the bot's view (PaperBot._bot_opinion: opposite reliable signal / market
state, progress %, R now, trends 15m-1d, RSI, nearest swing high/low) and Gemini's advice (advisor.consult,
CONSULT_PROMPT: hold / exit / move_stop with newStop, confidence, Persian reason, levels; a new stop on the
wrong side becomes hold). Nothing automatic: buttons "close" / "move the stop" next to the answer. Kept on the
position (consults, last 5) and so in the closed trade in memory, to check later. Diary "consult".
The 33-min 3m scan (screenshot 07:22): no errors in the log; the computer slept during that scan (events
05:34 -> 06:36 gap); scans are 40-63 s again.

## Reliable rule removed (owner 2026-11-06)
Profile.use_reliable False: scanner.reliable no longer filters trades (still worked out and kept in memory for
every signal). Data (this Mac's memory, 30 Oct - 6 Nov, 15k live signals): passed 32.6% won -0.141 R, rejected
34.8% -0.137 R; his 7 strategies on 30m: passed +0.14 R (27), rejected +0.42 R (112); it threw away 72%.
The strict rule for slow charts was already off (STRICT_TIMEFRAMES empty). Expect about 3x more trades.
Consult window: a tab folds it to one line (verdicts) and opens it; folded state kept in the browser; a new
answer opens it; the open window is at most 28% of the height and can be resized by dragging its corner.

## Owner's 6-step design (2026-11-07)
1 coins: top 100 by volume (as before). 2 trend on a higher timeframe (HIGHER_TF: 1m-15m -> 1h, 30m/1h -> 4h,
4h -> 1d) from the efficiency ratio of 20 closed candles (>= 0.3 trend, else range): trades only with it; range ->
skip "range", other way -> "against". 3 Bitcoin link: correlation of 1h returns over 30 days per coin (worked out
once a day, only for candidates); followers (>= 0.2) need Bitcoin's trend (same higher timeframe) the same way:
"btcFlat" / "btcAgainst". Panel line: Bitcoin 1h / 4h trend. 4 strategies per timeframe: the owner's manual list
(unchanged). 5 equal risk (1%), margin at most 1/6, at most 6 open trades (MAX_POSITIONS, waiting limit orders
count). 6 entry at the signal price or better; at most 10% of the stop distance toward the target (STALE_PART);
the target stays (a late entry exits sooner) and the reward rule is checked at the price now.
Exit: after 12 candles (1m-15m) a trade still open aims at break-even (in profit: stop to break-even; in loss:
closes when the price comes back to the entry, reason "timeBe"). Tests behind each choice: see progress notes.
Range trading (owner asked): bb_reversion / vwap_reversion / sd_zone do it; -0.11 R on 91k history signals in
"range"; with Toobit fees the textbook 5m BTC example (stop $40, target $280) is about 1:1, not 1:7.

## Chart update (owner 2026-11-07 16:50-17:05) — BUILT
- For each position, on the chart: the strategy and the data that made the bot enter (the strategy's own lines,
  e.g. EMAs / bands / the FVG gap or zone, the signal candle; the higher-timeframe trend and Bitcoin's state).
- Support and resistance lines on the chart (swing highs / lows).
- An "Explanation" button per position: the bot's own words on why it entered (strategy and its condition, the
  higher-timeframe trend, Bitcoin link / trend, fee and reward checks, entry type, the price vs the signal price).
- The profit-lock line ("lock at", purple dashed) draggable on the chart, like the stop and target lines;
  per position only (owner: a); the stop-after-lock moves with it at the same ratio (80 -> 40: half the way).
- Bot chart: timeframe buttons; support / resistance from the chart's timeframe (thin) and its companion
  (bold): 1m->5m, 3m/5m->15m, 15m->1h, 30m/1h->4h, 4h->1d; 2 levels above and 2 below each.
- Owner 17:01: the profit-lock point and the stop-after-lock are drawn INSIDE the position's green / red boxes
  (short lines, no separate full-width labelled lines) and dragged there. Only the boxes carry the text:
  green: target $, reward:risk (e.g. 1:2), lock at X%; red: stop $, stop after lock Y%. Cleaner chart.
  Both lock lines sit in the green box (the stop after lock is on the profit side). Owner 17:03: every overlay
  can be hidden / shown with the eye list, the green / red boxes and entry / exit markers too.
- Top-left of the chart: a list of line groups (entry/stop/target, liquidation, break-even/lock points,
  strategy lines, S/R chart TF, S/R companion TF) each with an eye button to hide / show; kept in the browser.
- How it was built: backend stores `why` (signal price/time, market state, higher TF, fee share, reward, brain chance)
  when a position opens; `set_lock_point` (POST levels with `lock_point`) stores `lockOwn` {trigger, at} shares for
  that position only (at = trigger * lockAt/lockTrigger), errors lock_off / lock_done / lock_side. Frontend:
  botView `swingLevels` (pivot 3, 2 each side, merge 0.15%), `lockPrices`, `explainLines`, `COMPANION_TF`,
  `CHART_TFS`, `EYE_GROUPS` / `loadEye` / `saveEye` (localStorage "bot.eye"); chart.ts `BoxDecor` / `setDecor`
  (texts + short lines in the boxes, yellow signal-candle band), hidden draggable Level for the lock point;
  botApp: positions of the coin drawn on any chart timeframe (times snapped to its candles), strategy lines via
  /api/strategies/run (cached 2 min), companion candles cached 2 min, «توضیحات» button in the consult bar.

## Built 2026-11-09 (owner approved 09:51)
- Timed look at long positions (paper.py REVIEW_AFTER_CANDLES 20, REVIEW_EVERY minutes per TF 1m/3m 10, 5m-1h 15,
  4h 60; account reviewEnabled / reviewAfter / reviewEvery, POST /api/paper/review). `_review`: against = higher-TF
  trend against the side, or this TF's market state trending against; then Gemini (consult) if keys — any action
  but "exit" keeps it. In profit -> closed, reason "review". In a loss -> `reviewAsk` + Telegram message with
  buttons close:<id> / hold:<id>; `_telegram_answers` (each step, every 3 s) reads taps (only the owner's chat),
  answers them; no answer -> asked again at the next look.
- Telegram fixed keyboard (2026-11-09 11:28): «📊 وضعیت ربات» / «📈 پوزیشن‌های باز» or /status /positions; read by
  PaperBot.telegram_forever (server lifespan task, every 3 s, also while the bot is stopped); taps close/hold too.
- Chart opens zoomed on the position (botApp.zoomToPosition: 30 candles before entry, 8 after exit or the last).
- Telegram open message (short: position, state, price), sent from `_new_position` (limit orders only when filled).
- Panel sections fold (botView PanelSection / sectionOpen / loadFolds, localStorage "bot.sections"): switched
  sections (limit, ai, tg, lock, review) open while on, closed shows title + switch; turning on opens; errors open;
  timeframes open; others (incl. diary) closed. Advice / start / status always shown.
- Glass look + background (src/background.ts): galaxy canvas (stars, ~25 fps, stops when hidden / reduced motion),
  aurora (CSS bands), matte colour; 🎨 button before the language button in any top bar; localStorage "ui.background".
  Chart background transparent. 2026-11-09 10:31: natural aurora drawn on the canvas (curtains of rays, stars,
  hills); 4th mode "clear" (desktop app only): window transparent (tauri.conf transparent + macOSPrivateApi,
  Cargo feature macos-private-api, window-vibrancy 0.6, command set_glass: macOS vibrancy HudWindow, Windows
  Mica -> acrylic -> blur, only while chosen); slider 0-90% = panels' opacity (--glass-alpha).

## Study of 2026-11-09 (branch study-2026-11-09, workflow "Study", backend/scripts/study.py; 40 top coins)
All 18 strategies, bot fee/reward rules, every signal (no trend/BTC filters), R after fees, two halves.
- Two-step lock (BE at 20-50% + 80/40): no gain on any timeframe (differences ~0.01 R, not in both halves);
  80/40 alone also neutral here (4h a little worse: +0.029 none vs +0.023). Not built.
- S/R skip (1m close beyond the nearest swing level against the trade between signal close and the live-like
  late entry; 6 days of 1m): 5m crossed -0.29 R (115, both halves) vs kept +0.03; 1h crossed -0.13 (59, both
  halves); 15m crossed +0.04 (no). Promising on 5m / 1h but small samples: to be confirmed on more days.
- Turtle 55 + EMA200 4h: best exits 10/20-channel +0.13..+0.14 R but first half negative (-0.05..-0.10),
  second +0.28..+0.35: not stable. Not built.
- Limit entry: per signal about the same as market (adverse selection: the missed ones are the winners,
  +0.35 R at market). No gain.
- Crowd data on Toobit via ccxt: only funding-rate history; funding vs results: no stable effect.

## Real Toobit account (owner approved 2026-11-09 13:50) — BUILT, default off
backend/app/account.py (ExchangeAccount), settings.json "exchangeAccount" {apiKey, secret, mode, maxMargin,
maxLeverage, dailyLoss, confirm} (never shown / committed / sent to the AI; the key must have withdrawals off).
Modes: off / read (balance, positions, orders every 15 s) / shadow (for each paper open: the real order planned from
1% of the real equity, inside the caps, only recorded in `plans`) / real (needs agree_real; market entry, then
reduceOnly stopLossPrice + takeProfitPrice orders on the exchange; protection fails -> closed at once and halted;
paper stop moves -> new exchange stop, old cancelled; paper close -> real reduceOnly close; daily loss cap -> halted
until the next UTC day; optional Telegram confirm rok:/rno: buttons, 60 s; emergency: app button or Telegram
/closeall -> panic: close all, cancel all, mode back to read). PaperBot.mirror(open/close/levels) feeds it.
API: GET/POST /api/account, POST /api/account/test|panic|resume. UI: start screen "🔗 اتصال صرافی" (accountPanel.ts);
bot / semi screens: top-bar chip only when connected (opens the same panel). Live check prints ccxt's Toobit
support (has[]) for the private calls. NOT yet tried on a real account (no keys here): start with read, then shadow.

## Update 2026-11-09 15:08 (owner approved)
- Real mode uses Toobit's own API (ccxt cannot place stops on Toobit): entry POST api/v1/futures/order
  {symbol BTC-SWAP-USDT, side BUY_OPEN/SELL_OPEN, type LIMIT, priceType MARKET, quantity contracts};
  stops POST api/v1/futures/position/trading-stop {symbol, side LONG/SHORT, stopLoss, takeProfit} (also to move
  them); close POST api/v1/futures/flashClose {symbol, side}. Contracts = base amount / contractSize. Live check
  prints whether ccxt has these implicit methods and the market id / contract size. Still untried on a real key.
- Box texts on the chart: drawn by a top-z pane view on dark rounded labels (green box above its top edge, red
  below its bottom edge), numbers wrapped in LRE..PDF (U+202A/U+202C) — Chrome canvas ignores isolates.
- Liquid Glass panel style (🎨 menu "سبک پنل‌ها"; html.liquid; Chromium adds an SVG displacement lens html.lens).
- Semi-automatic screen switched off (chooser card and top-bar switch removed; app.ts kept). The strategies'
  history test moved into the bot panel: section "history" (botApp.loadHistory -> /api/strategies/overview for the
  chart's coin/timeframe, cached 5 min, only while the section is open).

## Audit + fixes (owner 2026-11-09 15:38-17:13)
- Audit of all 19 positions since 11-07 16:25 against Toobit 1m candles (local engine via the built-in browser):
  arithmetic all right; stop / lock exits seen on the live price inside the forming candle were booked at that
  price, not at the stop (EVAA #20, UAI #42, ICNT #4, IDOL #2, ON #25, JCT #30: +0.99 $ understated in total);
  late detections while the computer slept / app closed were booked at the right prices.
- Fix: paper.check_minutes reads the forming candle minute by minute (closed and forming 1m candles after the
  entry minute; stop fills at the stop, at the 1m open on a gap; target at the target; lock from 1m extremes;
  p["checkedMinute"]); the live price is used only if 1m candles cannot be had or after a hole.
- p["edits"]: time / what / old / new of every stop / target change by the owner.
- Break-even (breakeven, timeBe, ~0 result) is neither won nor lost: winRate = wins / (wins + losses);
  stats.losses / stats.evens; panel shows "x% (w won · l lost · e even)".
- Telegram management: /positions (or the fixed button) lists positions with a button each (pos:<id>); the
  position message has ✏️ stop (est:), ✏️ target (etp:) — the new price is the next message (5 min, /cancel),
  checked by set_levels — ⚖️ break-even (pbe:, only in profit), 🔄, ❌ close (pcl: then pcy: to confirm).

## Volume Profile study (2026-11-09 21:46, branch study-2026-11-09, scripts/study_vp.py, 40 coins)
Profile = 100 candles before the signal, 24 rows, VA 70%. R after fees, halves:
- B (bot signals with VP stop / target, rr>=1): 1h -0.113 and 4h -0.050 (both halves negative); 5m / 15m mixed. No.
- C (POC side filter: longs below POC, shorts above, own levels): 4h kept +0.049 (+0.064/+0.033) vs removed
  +0.011; 1h kept +0.002 (-0.037/+0.039) vs removed -0.035 (-0.106/+0.023) -> better in both halves on 1h/4h.
  5m / 15m: kept worse than removed in both halves. => candidate rule for 1h / 4h only (not built).
- D (VA edge back to POC) / E (80% rule): small samples, unstable; only 1h D long +0.117 (254, both halves +).

## Target-distance study (2026-11-10, study_targets.py + live MFE of 28 trades)
- Live (since 11-08, 1m candles): own targets median 2.55 R (up to 7.8 R; AKE #78 target below zero!) because the
  entry is often better than the signal price (limit / one-sided stale rule) while stop and target stay. Losers:
  11 of 16 never went 0.5 R in favour; 8 trades reached 1.5-2.7 R and came back. On these 28: own target -6.3 R,
  1.5 R target +7.1 R, lock 50/25 +5.8 R, lock 80/40 -3.4 R (hindsight, tiny sample).
- History (40 coins, all signals, strategies' own R:R = 2.0): closer targets / earlier locks do NOT raise avg R
  (all variants within ~0.02 R, not stable across halves); win rate goes up (lock 50/25 ~50% vs 40%).
  Lock 50/25 >= 80/40 on every timeframe (equal or a little better) -> candidate default.
  ~30% of losers went 40-100% of the way before the stop.
- Bugs: box label R:R uses the current stop (1:184); targets can be absurd (below zero) -> validate.

## 2026-11-10 10:15: fixes + study of the stopped trades
- BUILT: paper.anchor_target (target = strategy's own R:R from the real entry / order price, <= 4R, never further
  than the signal's target, None when target <= 0 -> skip "past"); box label R:R from stopLoss (first stop).
- How stops are set: per strategy, either an ATR multiple or the last 1-2 candles' extreme / an indicator line
  (+ buffer). No strategy uses swing support / resistance.
- 16 of 28 live trades hit (or would have hit) the first stop: 9 never reached 0.5R and died within 8 candles;
  10 of 16 were in three coins (UAI 4, ON 3, JCT 2+) re-entered the same way after a loss; all coins are
  BTC-independent small caps with ATR 2-25% per candle; side / strategy / market state: no pattern.
  Live: 9 of 10 trades with a swing level closer than 1 ATR behind the entry lost (11 of 12 others had none).
- History (study_stops.py, 40 coins): a stop behind the nearest swing level does NOT raise the win rate
  (35% vs 35%) or avg R on 5m / 15m / 1h; 4h a little better (+0.020 vs +0.003, not in both halves clearly);
  S/R target worse everywhere. Signals with no swing level at all behind them: -0.08..-0.35 R on every TF (few).
- Owner wants (not built, decision points sent): time break-even only on his answer; a stay / close question when
  a position gets long. Candidate to test: cooldown on a coin after a stop.

## Asked, not automatic (owner approved 2026-11-10 10:59)
- Time break-even (12 candles on 1m-15m): _maybe_time_be only marks p["timeBeAsk"]; _watch_one sends a Telegram
  question (tbe:<id> "break-even" / tgo:<id> "go on"); time_be_answer: in profit stop -> breakeven price, in a loss
  beExit. No answer: nothing changes.
- Long positions: _review asks once when the review starts (view "with") via _ask_stay (bot view + Gemini consult,
  buttons hold / close), again only when the view changes (p["reviewView"]). Trend turned + profit: closed by
  itself; + loss: asked (as before). No answer: stays.

## SP2L study (2026-11-10 13:05, owner's videos, branch study-2026-11-09, scripts/study_sp2l.py, 40 coins)
Setup: strong first leg (2-8 same-colour candles, FVG-like gap, closes in top 25%/40% of range, size >= 1.5x/1.2x
the 20 before), limit at the previous candle's low/high on the first pullback (within 3 candles), stop behind the leg,
targets 1/1.5/2R, 2R+lock 50/25, with/without EMA200. Result: negative almost everywhere. The video's 1:1 wins
only 38-49% (needs >~53% after fees). Best: 15m strict 2R+lock +0.039R (n=123), 4h loose+EMA200 2R +0.003R:
noise. The bot's own strategies on the same candles are better (5m +0.052, 15m +0.020). Not added to the bot.

## New strategy families (2026-11-10 13:40, branch study-2026-11-09, scripts/study_new.py, 40 coins)
Owner asked to find and test new methods. R after fees, two halves. Bot baseline: 5m +0.052, 15m +0.020, 4h +0.007.
- A Larry Williams volatility breakout (UTC day, entry when price passes day open +/- k x yesterday's range, stop at
  the day open, exit at day end): BEST. 1h long only k=0.7: +0.142R (+0.110 / +0.172), 772 trades, ~+1.0% net per
  trade vs +0.07% for simply holding every day; worst case (entry candle touched the stop) still +0.050 (+0.068 / +0.032).
  15m long k=0.7 +0.135 (+0.215 / +0.071). Shorts ~0. Both sides k=0.5 +0.082 but negative in the worst case.
- G cross-sectional 1d reversal "long the 5 biggest losers of the day, hold 1 day": +0.54% net per trade (+0.12 / +0.72),
  no stop; shorting winners loses. Promising but risky (no stop) and uneven halves.
- F Lance-like Fibonacci trend: small positives in many variants (15m N=50 2R +0.083/+0.053; 4h N=100 exit on flip
  +0.29 but +0.01 / +0.54). Weak.
- D RSI(2) (60% wins but negative), E exhaustion fade (bad), B hour of day (fails out of sample), C 12h sessions
  (no), H NY opening range (half 1 +, half 2 -): no.
Nothing added to the bot yet; decision point sent (A as a paper strategy needs a day-end time exit).

## Research study on our data (2026-11-10 14:30, study_research.py, top-40 + volatile-30 coins)
- Fee (0.12% round trip) as share of the median candle range: top40 5m 53%, 15m 33%, 1h 17%, 4h 7%;
  volatile30 5m 21%, 15m 15%, 1h 8%, 4h 4%. Low timeframes on top coins are mostly fee.
- No usable serial pattern: next candle reverses 50-52%; lag-1 autocorrelation ~0; after 2-3x / >3x candles the
  continuation is < 0.15% (under the fee). Matches research (15m crypto reversal ~1.3 bp gross vs costs).
- BTC -> altcoin lead-lag: +0.02% at most before fees; after fees -0.09 to -0.15% per trade. Not usable.
- CORRECTION of the volatility breakout: with consistent worst-case fills, 21-day warm-up and a 0.5% minimum stop
  it is ~0 to negative (top40 1h k=0.7 -0.07R; with "not broken down first" -0.03R; + coin above 5-day avg +0.02R
  with half 2 negative). Only volatile30 15m (1 month of data) stays positive (+0.13R). The earlier +0.14R needed
  the bot's fee filter (big-range days only) and a close-based fill. Not robust: do not add yet.
- Losers of the day (4h, top 40): 5% stop kills it (-0.07%); 10% stop +0.27%; 10% stop and BTC also fell +0.50%
  (+0.10 / +0.70). Promising but uneven halves and wide stop.

## Broad research study (2026-11-10 15:00, study_more.py, top-40 + volatile-30)
- Bot's 18 strategies (bot fee rule = stop >= 2.4%): volatile30 5m +0.045R (+0.052/+0.041), 15m +0.034 (+0.038/+0.032)
  = best and stable; top40 5m +0.039, 15m +0.013; 1h/4h ~0 or negative (volatile30 4h -0.040).
- Stop distance (top40): no clear rule; wider stops on 5m (6-10% +0.133) mostly half 2.
- Walk-forward (keep strategy x tf positive in the previous third): helps 5m/15m/1h (volatile30 15m +0.041 vs
  dropped -0.003), FAILS on 4h (picked -0.106 / -0.147). Positive in all three thirds: volume_breakout (5m/15m
  volatile, 1h/15m top), donchian 5m/15m top, inside_bar 5m/15m both, rsi_pullback 4h/1h top, ichimoku 15m vol.
- Pairs trading (1h, z>2): -0.18% per trade. No.
- Day of week (4h, ~14 months): Thursday negative in both halves (-1.07% / -0.37% day open->close, before fees);
  weak evidence (~60 Thursdays, coins move together).
- Funding extremes contrarian (Toobit funding history, hold 24h, no stop): z>2 +0.32% (short side +0.15/+0.49);
  funding beyond +/-0.05%: +1.18% per trade (+0.61 / +1.75), n=382. Most promising new signal; needs a stop test.

## Focus switch (owner approved 2026-11-10 14:58: "you decide what is better")
- Panel, timeframes section: "Focus mode (5m + 15m, volatile coins)" on/off. On: keeps chosenTimeframes / coinMode /
  coins in account["focus"]["saved"], sets 5m + 15m and coinMode volatile. Off: the kept values come back exactly.
  All 18 strategies stay on (a short list starved the bot on 11-01). Reset keeps the switch.
- Trades opened in focus mode carry focus=True; the panel shows focus vs other trades (count, won %, result).
- POST /api/paper/focus {on}; diary events focus on/off. Tests: FocusTest.

## Owner's deeper-entry idea (2026-11-10 16:37): price goes our way while the limit waits -> enter deeper,
## stop and target moved by the same amount
- Our 43 closed paper trades (1m candles from the local app; 3 oldest on 5m): plain simulation of today's entries
  -8.11$ (-5.44R); +0.5 risk deeper, 1 candle: 15 trades, +21.9$ (+8.39R) BUT one trade (#34 JCT, owner-moved far
  target, 3$ risk) gives +18.5$; without it ~+2R. 3 days, too few trades.
- Bot strategies on history (study_dip.py, 40 + 30 coins, 5m-1h, thousands of signals): every deeper variant is
  worse than today's limit (0.1 x risk, 1 candle). volatile30 5m today +1.9R per 100 signals, deeper -0.5 to -2.3;
  15m today +1.6, deeper -0.2 to -1.4. Reason: adverse selection (only the failing signals dip further; the good
  ones run off without us). Not built.

- Follow-up (study_dip2.py): (1) IF the price goes against the signal (known only afterwards) the idea is far better
  for those trades (entered as usual -0.25/-0.5/-1.0R avg for a 0.25/0.5/1 x risk dip; idea ~0R). (2) The owner's
  exact case "bot missed the entry, then the price fell": extra trades with moved levels are ~0 to negative on
  volatile 5m (-0.06 to -0.17R) and 15m (-0.01 to -0.21R); positive only on top40 5m (+0.15 to +0.25, small n).
  Adds -0.5 to +1.0R per 100 signals. Not built.

- Scale-in (study_scale.py, 2026-11-11): half at the usual limit + half 0.25/0.5/0.75 x risk lower (same or moved
  levels): about half of today's result wherever today is positive (volatile 5m +2.4 -> +0.1..+1.4; 15m +2.4 ->
  +0.7..+1.6; top40 15m +3.9 -> +1.6..+2.4 R per 100 signals); 1h less negative only because less is traded.
  Not built.

## Funding extremes with stops (study_funding.py, 2026-11-11, top 40 + volatile 30, 1h prices)
- The earlier +1.18% did not hold up: all coins, beyond 0.05%, 24h, no stop -0.22% per trade (n=1209); volatile
  coins negative in almost every setting (-0.2 to -2.3%).
- Only top coins, funding beyond 0.1%, hold 24h stay positive in both halves: stop 5% +1.17% (+0.09 / +2.29),
  R +0.23, n=307; stop 3% +0.46% (+0.13 / +0.81). Best of 120 settings -> data-snooping risk. Not built.

## Exit habits + per-coin pause (study_exits.py, 2026-11-11, bot strategies, 5m/15m, volatile 30 + top 40)
- Owner's habits as rules (target 1R, half at +0.5R, BE at +0.5R, time exits) do NOT help on history: early profit
  taking pulls avgR to ~0 (target 1R +0.003). Half at +1R then BE ~= base (+0.040/+0.044 vs +0.038/+0.037; worse
  on top 5m). Lock 50/25 = same result, win rate 51% vs 41%.
- KEY: like the bot (one trade per coin at a time), signals in time order: volatile 5m+15m -0.044R per trade (both
  halves negative) = the live losses. With a pause on the coin after a stop: 2h +0.032, 6h +0.065 (+0.055 / +0.074),
  12h +0.060, 24h -0.077. Top 40: -0.052 -> -0.020 / -0.026 (2h / 6h). Decision point: per-coin pause 6h.

## Coin pause after a stop-loss (owner approved 2026-11-11: a typed number of hours)
- account["coinPauseHours"] (default 6, 0 = off, max 168; kept on reset); account["coinPaused"] {symbol: until}.
- Only exitReason "stop" with a loss starts it (break-even, lock, manual, review do not). Paused coins are skipped
  in the scan with reason "coinPause"; event "coinPause". POST /api/paper/coin-pause {hours}. Panel: number input
  under max-open, list of waiting coins with minutes left. Tests: CoinPauseTest.
- Owner asked why so few signals (2026-11-11): the direction filter (owner's design 11-07): the coin's higher-tf
  trend must agree, never in a range, and BTC followers need BTC's trend; BTC was "range" on 1h and 4h, so most
  signals end as "range" / "btcFlat"; plus one trade per coin, max open, the brain (keeps ~half), the fee rule.
  NOTE: study_exits.py did not apply the direction filter or the brain.

## Strategy league test on the bot's own memory (2026-11-11, memory.db staged; /tmp/league*.py, not in repo)
Rule: per strategy x timeframe, signals that ENDED in the last N days (all coins); keep if >= X and avg R > 0;
evaluated on the next 6 hours' signals, walk-forward.
- LIVE (12 days, 17k signals): N=3 X=50 picked +0.156R (+0.14 / +0.20) vs dropped -0.026; 5m+15m +0.112 vs -0.081.
  BUT concentrated: donchian 3m +110R and volume_breakout 5m +81R of ~+134R; 11-05 alone +130R.
- Pretrain "history" signals in memory (324k, ~2 months): no gain (picked -0.078 vs dropped -0.083; 5m+15m worse).
- Exchange-candle study (study_more.py): picks helped 5m/15m/1h, failed on 4h.
Mixed evidence. Decision point sent: optional switch (N=3, X=50) with tagged results, default off.

## Strategy league switch (owner approved 2026-11-11 "بساز")
- account["league"] bool (default off, kept on reset). PaperBot.league_table(): Memory.league(now - 3 days) ->
  per (strategy, tf) live signals of all coins that ended (count, sum R); on = count >= 50 and avg R > 0; cached
  6 h. In _scan_and_open a strategy not "on" for that tf is not a candidate (counted "league"). Only filters the
  owner's ticked strategies. Positions carry league=True; panel shows league vs other trades (tagged_stats).
- POST /api/paper/league {on}; panel: switch + per ticked timeframe the strategies on (avg R, count) and how many
  off; diary events. Tests: LeagueTest (memory), LeagueSwitchTest.

## Four schools study (study_schools.py, 2026-11-11; owner named the authors: Hosoda, Huddleston, iFmyante, Beggs)
avg R per trade (half 1 / half 2); bot's 18 strategies same candles: vol 5m +0.039, 15m +0.064; top 5m +0.039, 15m +0.055.
- Ichimoku TK cross + cloud + Chikou: 5m top +0.131 (+0.12/+0.14, n=105), 5m vol +0.113 (+0.18/+0.08, n=272);
  15m half 1 negative. TK cross only: weak.
- YTC TST: 15m top +0.264 (+0.34/+0.23, n=238), 15m vol +0.072 (+0.23/+0.01); 1h/30m negative.
- YTC BPB: 15m vol +0.148 (+0.06/+0.19, n=311), 15m top +0.053; 30m both groups positive both halves.
- ICT BOS 5m top +0.094 (both), vol +0.035 (both); CHoCH 15m top +0.037, vol +0.053 (both halves).
- RTM QM: 30m top +0.133 (both), 1h top +0.096, 1h vol +0.111 (both); 5m negative.
- RTM FTR/FL negative almost everywhere; CAPS too few trades. YTC BOF mixed / negative on 1h.
Decision point: add the consistent ones as strategies per timeframe; the league then judges them live.

## Big test + proven set (2026-11-11, full write-up: docs/RESEARCH-2026-11-11.md)
- Data: Binance futures 5m candles 2024-07..2026-10 for Toobit's top / volatile coins (Toobit keeps only 3500
  candles per timeframe). Scripts: backend/scripts/research (numba simulator with the bot's rules).
- 28 new strategies (46 in all) + 12 indicators. Result after fees: everything on 5m-30m negative; only the
  breakout / momentum family is positive, on 1h-1d (+0.03..+0.13 R per trade, both halves, t 1-2.3). Exits and
  filters do not change the average. Portfolio (1% risk, 6 open): old 18 on 15m-4h 1.00 -> 0.29; proven set
  1h + 4h -> about 2.5 with falls of up to 39%.
- BUILT: proven-set switch (paper.PROVEN_BY_TF, account["proven"], POST /api/paper/proven, on by default from
  server.py when the key is missing; panel: timeframes section). On: only those strategies are scanned (1h, 4h),
  the manual list is ignored, the direction filter refuses only "against" / "btcAgainst". Tests: ProvenSetTest,
  EveryStrategyTest (sane signals, both sides, no look into the future), SecondSetIndicatorsTest.
- Real account: links paper <-> real kept in real-links.json (lost on restart before).
- Not built (no gain in the test): trailing exits, 2h / 1d timeframes for the bot (1d family +0.13 R, few trades:
  a candidate), filters on ADX / volume / Bitcoin.
- Toobit's top-volume list now holds many stock tokens (NVDA, SNDK, ...): they move together; four momentum
  longs opened at once in the live check. A cap per group is a candidate.

## Trend Rider (2026-11-11 evening; RESEARCH-2026-11-11.md part 2)
- Owner asked for a free search, a strategy of the author's own and 2-3% a day. Maker-limit scalping on 5m (24
  settings) and cross-sectional momentum / reversal fail; a trend portfolio on 4h holds (Sharpe about 1.2-1.3, both
  halves, about +0.2% a day, falls to 45%, 26% wins, all profit from a few huge trades). 2-3% a day: not reachable.
- BUILT, on by default: account["rider"], paper.RIDER_* constants, _rider_round after each 4h candle (and at
  start): score >= 0.6 long / <= -0.6 short, stop 4 x ATR(84), no target, exit at score <= 0 (reason "trend"),
  1% risk, 15 trades. Replaces the signal scan while on (proven set and manual list unused). Card trend_rider.
- Watch on paper: it opens up to 15 trades at once at the first start (trends already running), often mostly one
  direction. The 30% total stop can end a run that the test would have survived (falls of 40%+ happened).

## Proven set tuned + priority order (2026-11-11 night; RESEARCH part 3)
- Owner asked: tune per timeframe, give the bot an order of choice, then a download. BUILT: PROVEN_BY_TF lists
  are in priority order (pick(order=), PaperBot.priority), PROVEN_TUNING (only settings better in both halves),
  risk budget 6% / max open trades (default 12 places x 0.5% with the proven set). Account test: 1.35 (fall 58%)
  -> 3.77 (fall 27%); second half 0.90 -> 1.33. Optimistic end (chosen with both halves in view).
- Default now: proven set ON, Trend Rider OFF (switch in the panel).

## Owner's ideas to remember (2026-11-09, not built; owner will say when)
0. Known bug (owner 13:44): texts inside the green / red boxes overlap candles and each other on a narrow box;
   RTL with numbers garbled. Fix in the next update (pill background, bidi-safe, stacked, hide when too narrow).
0b. S/R skip rule (study 2026-11-09): kept for later, promising on 5m / 1h.
1. Two-step profit lock: step 1 stop to the fee break-even, step 2 to 70-80% of the way.
2. Long positions: after a set time, bot + AI review every ~15 min; close as soon as possible without a loss if the trend turned.
3. Telegram messages — BUILT 2026-11-09 for closed positions (backend/app/telegram.py; settings.json "telegram"
   {token, chatId, enabled}; POST /api/paper/telegram {token?, enabled?}, /telegram/test finds the chat from
   getUpdates after the owner's /start; PaperBot.notify() sends in the background; public shows only
   token yes/no + last 4 chars). `telegram.closing_text` is ready for idea 2 (trend changed, bot wants to close).
4. Chart line settings — BUILT 2026-11-09: gear ⚙ next to the eye; 13 groups (entry, stop, target, liquidation,
   lock point, stop after lock, break-even, orders, strategy [width/style only], resistance/support of chart TF
   and of companion TF) each with colour / solid-dashed-dotted / width 1-4; localStorage "bot.lines" (this computer).

## Next steps proposed to the owner
1. Owner's idea, designed, not built: skip a signal when a 1m candle closes beyond the resistance
   (short) / support (long) against it between signal and entry.
2. Test limit (maker) entries on the history: entry fee 0.02% instead of 0.06% (saves only ~0.02-0.05 R).
3. Crowd data (funding, open interest, long/short ratio) and later order flow as brain features.
4. VPN at home (Happ): engine needs TUN mode or the proxy address in "Connection to the exchange".
