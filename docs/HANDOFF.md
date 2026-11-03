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
  timeframes (default 15m-4h; 1m/3m too slow) goes to Gemini (gemini-2.5-flash, free tier) with the
  coin on 15m/1h/4h/1d, Bitcoin 1h/4h, nearest swings, last 30 candles and the strategy's record.
  Approve -> trade; reject -> skipped with its Persian reason in the diary; no answer -> the owner is
  asked in the panel (open / skip, expires after a quarter candle, max 15 min). Keys: settings.json
  on the owner's computer only (aiKeys), next key on 429. Every decision is stored in memory
  (ai_decision / ai_confidence / ai_reason) and the panel compares approved vs rejected results.
- Barrage account: removed 2026-11-02 (owner). An old paper-fast.json on disk is no longer used.
- Only ticked timeframes are scanned; a new 1m candle may put a slower scan off once (fix of
  2026-11-02: before it, slow computers never scanned 5m-1h).
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

## Next steps proposed to the owner
1. Owner's idea, designed, not built: skip a signal when a 1m candle closes beyond the resistance
   (short) / support (long) against it between signal and entry.
2. Test limit (maker) entries on the history: entry fee 0.02% instead of 0.06% (saves only ~0.02-0.05 R).
3. Crowd data (funding, open interest, long/short ratio) and later order flow as brain features.
4. VPN at home (Happ): engine needs TUN mode or the proxy address in "Connection to the exchange".
