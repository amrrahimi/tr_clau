"""Check the backend against the real Toobit exchange (needs internet).

Run from the backend folder:  python scripts/live_check.py
It prints what it found and exits with an error if something is wrong.
This is not part of the normal tests, because those must work offline.
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.analysis import ANALYSIS_CANDLES, analyze, run_strategy  # noqa: E402
from app.catalog import SPECS, parse_instances  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402
from app import config  # noqa: E402
from app.strategies import STRATEGIES, Fees, parse_params  # noqa: E402
from app.history import STRATEGY_CANDLES, HistoryCache, fetch_history  # noqa: E402
from app.scanner import Scan, run_scan  # noqa: E402


async def check(market_type: str) -> None:
    service = MarketService(create_exchange(market_type), market_type)
    try:
        top = await service.top_markets(limit=5)
        assert top, f"{market_type}: no markets returned"
        print(f"{market_type}: top 5 by 24h volume:")
        for info in top:
            print(f"  {info.symbol:<20} volume {info.volume_24h:>18,.0f} USDT   last {info.last_price}")
        assert top[0].volume_24h > 0, f"{market_type}: top market has zero volume"

        symbol = top[0].symbol
        candles = await service.fetch_candles(symbol, "5m", limit=20)
        assert len(candles) >= 10, f"{market_type}: only {len(candles)} candles for {symbol}"
        times = [c["time"] for c in candles]
        assert times == sorted(times), f"{market_type}: candles not in time order"
        assert all(times[i + 1] - times[i] == 300 for i in range(len(times) - 1)), \
            f"{market_type}: gaps between 5m candles"
        last = candles[-1]
        assert last["low"] <= last["close"] <= last["high"], f"{market_type}: candle prices inconsistent"
        print(f"  {symbol}: {len(candles)} candles, last close {last['close']}")

        older = await service.fetch_candles(symbol, "5m", limit=10, before=candles[0]["time"])
        assert older and older[-1]["time"] < candles[0]["time"], f"{market_type}: older candles not returned"
        print(f"  older history: {len(older)} candles before the first one")

        # Phase 2: analysis needs 1000 candles in one request.
        history = await service.fetch_candles(symbol, "15m", limit=ANALYSIS_CANDLES)
        assert len(history) >= 900, f"{market_type}: only {len(history)} of {ANALYSIS_CANDLES} candles"
        for trading_mode in ("scalping", "daily"):
            result = analyze(history, "15m", trading_mode)
            state = result["state"]
            assert state["current"] != "unknown", f"{market_type}: market state still unknown after {len(history)} candles"
            assert result["indicators"], f"{market_type}: automatic list is empty"
            print(f"  analysis 15m {trading_mode}: state {state['current']}, ADX {state['adx']:.1f}, "
                  f"indicators {[i['label'] for i in result['indicators']]}")

        # Phase 2b: every indicator in the catalog on real data.
        everything = parse_instances([{"type": t} for t in SPECS])
        result = analyze(history, "15m", "daily", everything)
        rsi = next(i for i in result["indicators"] if i["type"] == "rsi")["outputs"][0]["points"]
        assert 0 <= rsi[-1]["value"] <= 100, f"{market_type}: RSI out of range"
        for item in result["indicators"]:
            for output in item["outputs"]:
                assert output["points"], f"{market_type}: {item['label']} {output['key']} has no values"
        latest = ", ".join(f"{i['label']} {i['outputs'][0]['points'][-1]['value']:.4g}" for i in result["indicators"])
        print(f"  all {len(everything)} indicators: {latest}")

        # Strategies table: 5000 candles fetched page by page, without gaps.
        pages = []

        async def page(limit, before):
            rows = await service.fetch_candles(symbol, "5m", limit, before=before)
            pages.append(len(rows))
            return rows

        long_history = await fetch_history(page, STRATEGY_CANDLES)
        times = [c["time"] for c in long_history]
        # The exchange may keep less history than we ask for; then we use what there is.
        print(f"  long history pages: {pages}")
        # Shown as a note on GitHub's run page.
        print(f"::notice title=Long history {market_type}::pages {pages}, total {len(times)} candles")
        assert len(times) >= 1000, f"{market_type}: only {len(times)} candles of long history"
        steps = [b - a for a, b in zip(times, times[1:])]
        assert all(step > 0 for step in steps), f"{market_type}: repeated or unordered candles in long history"
        missing = sum(1 for step in steps if step != 300)
        # The exchange itself may lack a few candles (maintenance); page joins must not.
        assert missing <= len(steps) // 100, f"{market_type}: {missing} gaps in long history"
        print(f"  long history: {len(times)} candles of 5m, {missing} gaps")

        # Strategies: every one runs on real data and gives sensible trades.
        for kind in STRATEGIES:
            result = run_strategy(long_history, "5m", kind, parse_params(kind, {}, "scalping"), "scalping",
                                  fees=Fees(**config.DEFAULT_FEES[market_type]))
            for t in result["trades"]:
                direction = 1 if t["side"] == "long" else -1
                assert (t["entryPrice"] - t["stopLoss"]) * direction > 0, f"{market_type}: {kind} stop on wrong side"
                assert (t["takeProfit"] - t["entryPrice"]) * direction > 0, f"{market_type}: {kind} target on wrong side"
            s = result["stats"]
            rate = f"{s['winRate']:.0f}%" if s["winRate"] is not None else "-"
            pf = f"{s['profitFactor']:.2f}" if s["profitFactor"] is not None else "-"
            print(f"  strategy {kind:<13} trades {s['trades']:>3}  win {rate:>4}  PF {pf:>5}  "
                  f"total {s['netPercent']:+.1f}% after fees ({s['feePercent']:.1f}% paid)")

        # Scanner: every strategy on all 50 coins, timed.
        cache = HistoryCache()

        async def coins():
            return [(m.symbol, m.base) for m in await service.top_markets(config.SCANNER_COINS)]

        async def candles(sym):
            return await cache.get((market_type, sym, "15m"),
                                   lambda limit, before: service.fetch_candles(sym, "15m", limit, before=before))

        settings = {k: parse_params(k, {}, "daily") for k in STRATEGIES}
        job = Scan(key="live", period=0)
        started = time.time()
        await run_scan(job, coins, candles, "15m", "daily", settings, Fees(**config.DEFAULT_FEES[market_type]))
        took = time.time() - started
        assert job.error is None, f"{market_type}: scan failed: {job.error}"
        assert job.done == job.total >= 40, f"{market_type}: scanned {job.done} of {job.total}"
        assert len(job.failed) <= 5, f"{market_type}: {len(job.failed)} coins failed: {job.failed}"
        tables = job.public()
        best = ", ".join(f"{e['base']} {e['strategy']} {e['stats']['netPercent']:+.1f}%" for e in tables["maxProfit"][:3])
        print(f"  scanner: {job.total} coins in {took:.1f}s, failed {job.failed}; best: {best}; "
              f"cautious rows {len(tables['cautious'])}")
        print(f"::notice title=Scanner {market_type}::{job.total} coins in {took:.1f}s; failed {len(job.failed)}; "
              f"max-profit rows {len(tables['maxProfit'])}, cautious rows {len(tables['cautious'])}, "
              f"signals {len(tables['signals'])}")
    finally:
        await service.close()


async def check_paper_bot() -> None:
    """One full round of the paper bot on real futures data (virtual money, a temporary file)."""
    import tempfile
    from pathlib import Path
    from app.paper import TIMEFRAMES, PaperBot, Store

    service = MarketService(create_exchange("futures"), "futures")
    cache = HistoryCache(max_charts=600)
    try:
        async def coins():
            return [(m.symbol, m.base) for m in await service.top_markets(config.SCANNER_COINS)]

        async def history_of(sym, tf):
            return await cache.get(("futures", sym, tf),
                                   lambda limit, before: service.fetch_candles(sym, tf, limit, before=before))

        async def recent(sym, tf):
            return await service.fetch_candles(sym, tf, 60)

        with tempfile.TemporaryDirectory() as folder:
            from app.memory import Memory
            from app.brain import Brain
            memory = Memory(Path(folder) / "memory.db")
            brain = Brain(memory)
            bot = PaperBot(Store(Path(folder) / "paper.json"), coins, history_of, recent, memory=memory, brain=brain)
            bot.reset(100)
            bot.start()
            started = time.time()
            await bot.step()
            took = time.time() - started
            state = bot.public()
            errors = [e for e in state["events"] if e["kind"] == "error"]
            assert not errors, f"paper bot errors: {errors}"
            assert set(state["lastScan"]) == set(TIMEFRAMES), f"not all timeframes scanned: {state['lastScan']}"
            for p in state["positions"]:
                assert p["leverage"] <= 10 and p["risk"] <= 1.0001, f"position too risky: {p}"
                beyond = p["liquidation"] < p["stopLoss"] if p["side"] == "long" else p["liquidation"] > p["stopLoss"]
                assert beyond, f"liquidation not beyond the stop: {p}"
            opened = ", ".join(f"{p['base']} {p['timeframe']} {p['strategy']} {p['side']} x{p['leverage']}"
                               for p in state["positions"]) or "none"
            print(f"paper bot: one round in {took:.1f}s, positions opened: {opened}")
            mem = memory.summary()
            print(f"::notice title=Paper bot::one round (5 timeframes x {config.SCANNER_COINS} coins) in {took:.1f}s; "
                  f"opened: {opened}; memory: {mem['signals']} signals, {mem['ended']} finished; brain: {brain.public()['state']}")
            # Pre-training from the history the round just loaded, then one learning round.
            started = time.time()
            added = await bot.pretrain_round()
            took = time.time() - started
            assert added > 0, "pre-training found no past signals"
            started = time.time()
            outcome = brain.train()
            learn = time.time() - started
            test = outcome.get("test") or outcome.get("challenger") or {}
            kept, every = test.get("kept", {}), test.get("all", {})
            print(f"::notice title=Pre-training::{added} past signals from {bot.pretrain_progress['done']} charts "
                  f"in {took:.1f}s; learning {learn:.1f}s -> {outcome['result']} (tested on {outcome.get('testedOn')}); "
                  f"kept {kept.get('count')} of {every.get('count')}, avgR {kept.get('avgR')} vs {every.get('avgR')}")
            # The barrage account: one 1-minute round on real data.
            from app.paper import FAST
            fast = PaperBot(Store(Path(folder) / "paper-fast.json"), coins, history_of, recent, profile=FAST)
            fast.start()
            started = time.time()
            await fast.step()
            flow = fast.public()["flow"]
            assert not [e for e in fast.public()["events"] if e["kind"] == "error"], "barrage errors"
            print(f"::notice title=Barrage::one 1m round in {time.time() - started:.1f}s; signals {flow['seen']}, "
                  f"opened {flow['opened']}, skipped {flow['skipped']}")
            # Owner's questions: break-even off / at 50% / at 80%, and the "+$0.1 profit cap", per timeframe.
            from app.research import add, compare_exits
            from app.paper import MODE_OF, SCAN_ORDER
            from app.strategies import STRATEGIES, parse_params
            started = time.time()
            coins_list = await coins()
            for tf in SCAN_ORDER:
                settings = {k: parse_params(k, {}, MODE_OF[tf]) for k in STRATEGIES}
                total: dict = {}
                for sym, _ in coins_list:
                    rows = await history_of(sym, tf)
                    add(total, await asyncio.to_thread(compare_exits, rows[:-1], settings, MODE_OF[tf], bot.fees))
                parts = [f"{v}: {r['count']} trades, avg {r['sumR'] / r['count']:+.3f}R, win {r['wins'] / r['count'] * 100:.0f}%"
                         for v, r in total.items() if r["count"]]
                print(f"::notice title=Exits {tf}::" + " | ".join(parts))
            print(f"exit comparison took {time.time() - started:.1f}s")
            memory.close()
    finally:
        await service.close()


async def main() -> int:
    failed = False
    for market_type in ("spot", "futures"):
        try:
            await check(market_type)
        except Exception as error:  # report every market type, then fail
            failed = True
            message = f"{market_type}: {type(error).__name__}: {error}".replace("\n", " ")[:900]
            print(f"FAILED {message}")
            # A line in this form shows up as an error note on GitHub's run page.
            print(f"::error title=Live Toobit check::{message}")
    try:
        await check_paper_bot()
    except Exception as error:
        failed = True
        message = f"paper bot: {type(error).__name__}: {error}".replace("\n", " ")[:900]
        print(f"FAILED {message}")
        print(f"::error title=Live Toobit check::{message}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
