# Handoff for the next session (project status, 2026-11-02)

**Talk to the owner in Persian only.** Learning mode (VibeWise): the owner decides the design;
propose, ask for approval ("پیاده‌سازی این قدم"), then build. After every push wait for CI and send the
download links. The repository is public: never commit keys, passwords or account details.

## Where things are
- Branch `main` holds everything (desktop build runs only on `main`; Android on every branch).
- Desktop: GitHub Actions "Build desktop apps" (Artifacts). Android: release `android-latest`
  (`TradingBot.apk`, installs over the old one). Data: `~/.trading-bot/` (paper.json, paper-fast.json,
  memory.db, settings.json, backend.log); Android keeps the same files in the app's data folder.
- Backend: `backend/app/` (paper.py bot, strategies.py 18 strategies, brain.py ML filter,
  pretrain.py, memory.py, scalp.py barrage signals, connection.py proxy, research.py experiments).
  Tests: `cd backend && python -m unittest discover -s tests -t .`; live Toobit check in CI.

## State of the bot
- Main bot: all 18 strategies on the ticked timeframes; "reliable" rule + brain filter + smart pause
  (4 losses / 5% fall -> 3 h, ends early after 2 wins; break-even is not a loss); 1% risk; break-even
  off on 1m-15m, 50% on 1h; half-way advice (hold / close); close buttons; optional profit cap.
- Barrage account (high risk, own money): 1m scalp signals + loose main signals, no position limit,
  closes at +0.05 USDT.
- Only ticked timeframes are scanned; a new 1m candle may put a slower scan off once (fix of
  2026-11-02: before it, slow computers never scanned 5m-1h).
- Panel shows: signals counter (seen / opened / skipped and why), scan times, entry/stop/target lines.

## Honest result so far
History tests (100 Toobit coins, after fees): no strategy has a clear edge; the best are about
break-even; shorter timeframes are worse (fees). The brain filter helps a little. Owner noticed most
signals hit the stop (reversing them would also lose: fees and the reward ratio).

## Next steps proposed to the owner
1. Test limit (maker) entries on the history: entry fee 0.02% instead of 0.06%.
2. Focus on 15m / 1h.
3. Crowd data (funding, open interest, long/short ratio) and later order flow as brain features.
4. VPN at home (Happ): engine needs TUN mode or the proxy address in "Connection to the exchange".
