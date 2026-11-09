# Handoff for the next session (project status, 2026-11-02)

**Talk to the owner in Persian only.** Learning mode (VibeWise): the owner decides the design;
propose, ask for approval ("پیاده‌سازی این قدم"), then build. After every push wait for CI and send the
download links. The repository is public: never commit keys, passwords or account details.

## Where things are
- Branch `main` holds everything (desktop build runs only on `main`; Android on every branch).
- Desktop: GitHub Actions "Build desktop apps" (Artifacts). Android: release `android-latest`
  (`TradingBot.apk`, installs over the old one). Data: `~/.trading-bot/` (paper.json,
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

## Owner's ideas to remember (2026-11-09, not built; owner will say when)
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
