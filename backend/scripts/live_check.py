"""Check the backend against the real Toobit exchange (needs internet).

Run from the backend folder:  python scripts/live_check.py
It prints what it found and exits with an error if something is wrong.
This is not part of the normal tests, because those must work offline.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.analysis import ANALYSIS_CANDLES, analyze  # noqa: E402
from app.catalog import SPECS, parse_instances  # noqa: E402
from app.exchange import MarketService, create_exchange  # noqa: E402


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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
