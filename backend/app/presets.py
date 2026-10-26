"""Automatic indicator choices.

Automatic mode does not search for the "best" numbers on past data (that
tends to fit the past and fail later). It picks a well-known, conventional
list for the current market state and trading mode.
"""

from __future__ import annotations

# Moving-average lengths per trading mode, also used by market-state detection.
MODE_EMAS = {
    "scalping": (9, 21),
    "daily": (20, 50),
}

STATES = ["trend_up", "trend_down", "range", "volatile", "unknown"]

# The third, long EMA per trading mode (fast and slow come from MODE_EMAS).
LONG_EMA = {"scalping": 50, "daily": 200}


def auto_instances(state: str, trading_mode: str) -> list[dict]:
    fast, slow = MODE_EMAS[trading_mode]
    long_ = LONG_EMA[trading_mode]

    def ema(n: int) -> dict:
        return {"id": f"auto-ema-{n}", "type": "ema", "params": {"length": n}}

    rsi = {"id": "auto-rsi", "type": "rsi", "params": {"length": 14}}
    if state in ("trend_up", "trend_down"):
        # Three EMAs: in a strong trend they line up in order (short, medium, long).
        return [ema(fast), ema(slow), ema(long_), rsi]
    if state == "range":
        return [ema(slow), {"id": "auto-bb", "type": "bb", "params": {"length": 20, "mult": 2}}, rsi]
    if state == "volatile":
        return [ema(fast), ema(slow), {"id": "auto-bb", "type": "bb", "params": {"length": 20, "mult": 2.5}},
                {"id": "auto-atr", "type": "atr", "params": {"length": 14}}]
    return [ema(fast), ema(slow), {"id": "auto-bb", "type": "bb", "params": {"length": 20, "mult": 2}}, rsi]
