"""The bot's memory (owner's idea): every reliable signal the bot saw, with the
conditions at that moment and how it ended. It is kept in its own file and
is never cleared by "start again" of the paper account, so the bot keeps
learning from all its experience.

Signals the bot did not trade (no free place, stale, ...) are followed too:
"shadow trades". Their result is worked out with the same engine as the
history test, on the candles the bot fetches anyway, so following them costs
no extra requests. Later the learning part (step B) trains on this.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .strategies import NO_FEES, Fees, Signal, simulate

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE,              -- symbol|timeframe|strategy|signal candle time
    symbol TEXT, base TEXT, timeframe TEXT, strategy TEXT, side TEXT,
    signal_time INTEGER, confirmed_at INTEGER, seen_at REAL,
    entry REAL, stop REAL, target REAL,
    features TEXT,                -- conditions at the signal, JSON
    taken INTEGER DEFAULT 0,      -- 1: the paper bot traded it
    skip_reason TEXT,             -- why not (full, stale, fee, past)
    status TEXT DEFAULT 'open',   -- open | win | loss | breakeven | expired
    exit_time INTEGER, exit_reason TEXT, pnl_percent REAL, r REAL, resolved_at REAL
);
CREATE INDEX IF NOT EXISTS signals_open ON signals(status, symbol, timeframe);
CREATE TABLE IF NOT EXISTS trades (    -- every closed paper trade, kept after "start again"
    id INTEGER PRIMARY KEY,
    closed_at REAL,
    data TEXT
);
"""

MAX_OPEN_CANDLES = 2000  # a shadow trade still open after this many candles is given up ("expired")


def features(entry: dict, overview_extra: dict, fees: Fees) -> dict:
    """Conditions at the moment of the signal (what the learning part will look at)."""
    s = entry["signal"]
    risk = abs(s["entry"] - s["stopLoss"]) / s["entry"] * 100 if s["entry"] else 0
    reward = abs(s["takeProfit"] - s["entry"]) / s["entry"] * 100 if s["entry"] else 0
    when = time.gmtime(s["confirmedAt"])
    stats = entry["stats"]
    return {
        "marketState": entry["marketState"],
        "adx": overview_extra.get("adx"),
        "atrRatio": overview_extra.get("atrRatio"),
        "stopPercent": risk,
        "rewardRatio": reward / risk if risk else None,
        "feeShare": 2 * fees.taker / risk if risk else None,
        "hourUtc": when.tm_hour,
        "weekday": when.tm_wday,
        "histTrades": stats.get("trades"),
        "histWinRate": stats.get("winRate"),
        "histProfitFactor": stats.get("profitFactor"),
        "histNetPercent": stats.get("netPercent"),
    }


class Memory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    @staticmethod
    def key(symbol: str, timeframe: str, strategy: str, signal_time: int) -> str:
        return f"{symbol}|{timeframe}|{strategy}|{signal_time}"

    def record(self, entry: dict, timeframe: str, feats: dict, now: float) -> str:
        """Remember a reliable signal (once)."""
        s = entry["signal"]
        key = self.key(entry["symbol"], timeframe, entry["strategy"], s["time"])
        self.db.execute(
            "INSERT OR IGNORE INTO signals (key, symbol, base, timeframe, strategy, side, signal_time, confirmed_at,"
            " seen_at, entry, stop, target, features) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, entry["symbol"], entry["base"], timeframe, entry["strategy"], s["side"], s["time"],
             s.get("confirmedAt"), now, s["entry"], s["stopLoss"], s["takeProfit"], json.dumps(feats)))
        self.db.commit()
        return key

    def mark(self, key: str, taken: bool = False, skip_reason: Optional[str] = None) -> None:
        if taken:
            self.db.execute("UPDATE signals SET taken = 1, skip_reason = NULL WHERE key = ?", (key,))
        else:
            self.db.execute("UPDATE signals SET skip_reason = ? WHERE key = ? AND taken = 0", (skip_reason, key))
        self.db.commit()

    def open_signals(self, symbol: str, timeframe: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT key, strategy, side, signal_time, stop, target FROM signals"
            " WHERE status = 'open' AND symbol = ? AND timeframe = ?", (symbol, timeframe)).fetchall()
        return [dict(zip(("key", "strategy", "side", "signal_time", "stop", "target"), r)) for r in rows]

    def resolve(self, symbol: str, timeframe: str, candles: list[dict], params_of: dict[str, dict],
                fees: Fees = NO_FEES, now: Optional[float] = None) -> int:
        """Work out the result of open signals of this chart from its closed candles,
        with the same engine as the history test. Returns how many ended."""
        if not candles:
            return 0
        index = {c["time"]: i for i, c in enumerate(candles)}
        ended = 0
        for s in self.open_signals(symbol, timeframe):
            i = index.get(s["signal_time"])
            if i is None:
                if candles[0]["time"] > s["signal_time"]:   # fell out of the history we keep
                    self._finish(s["key"], "expired", None, None, None, None, now)
                    ended += 1
                continue
            if i + 1 >= len(candles):
                continue  # the entry candle has not closed yet
            params = params_of.get(s["strategy"], {})
            trades, _ = simulate(candles[i:], [Signal(0, s["side"], stop_price=s["stop"], target_price=s["target"])],
                                 params.get("breakeven", 0), int(params.get("max_candles", 0)), fees)
            if not trades:
                # The levels did not make sense with the real entry price: nothing to learn.
                self._finish(s["key"], "expired", None, None, None, None, now)
                ended += 1
                continue
            t = trades[0]
            if t["result"] == "open":
                if len(candles) - i > MAX_OPEN_CANDLES:
                    self._finish(s["key"], "expired", None, None, None, None, now)
                    ended += 1
                continue
            self._finish(s["key"], t["result"], t["exitTime"], t["exitReason"], t["pnlPercent"], t["r"], now)
            ended += 1
        self.db.commit()
        return ended

    def _finish(self, key, status, exit_time, reason, pnl, r, now) -> None:
        self.db.execute(
            "UPDATE signals SET status = ?, exit_time = ?, exit_reason = ?, pnl_percent = ?, r = ?, resolved_at = ?"
            " WHERE key = ?", (status, exit_time, reason, pnl, r, now if now is not None else time.time(), key))

    def save_trade(self, trade: dict, now: float) -> None:
        self.db.execute("INSERT INTO trades (closed_at, data) VALUES (?, ?)", (now, json.dumps(trade)))
        self.db.commit()

    def strategy_results(self, since_exit_time: float) -> dict[str, float]:
        """Sum of results (percent) per strategy for signals that ended after a time."""
        rows = self.db.execute(
            "SELECT strategy, SUM(pnl_percent) FROM signals WHERE status IN ('win','loss','breakeven')"
            " AND exit_time >= ? GROUP BY strategy", (since_exit_time,)).fetchall()
        return {k: v or 0.0 for k, v in rows}

    def summary(self) -> dict:
        total, open_, wins, losses = self.db.execute(
            "SELECT COUNT(*), SUM(status='open'), SUM(status='win'), SUM(status='loss') FROM signals").fetchone()
        taken = self.db.execute("SELECT COUNT(*) FROM signals WHERE taken = 1").fetchone()[0]
        trades = self.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        return {"signals": total or 0, "open": open_ or 0, "wins": wins or 0, "losses": losses or 0,
                "ended": (total or 0) - (open_ or 0), "taken": taken, "trades": trades}
