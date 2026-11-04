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
import threading
import time
from pathlib import Path
from typing import Optional

from .config import TIMEFRAME_SECONDS
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
CREATE TABLE IF NOT EXISTS training (  -- every learning round of the brain (step B)
    id INTEGER PRIMARY KEY,
    time REAL,
    outcome TEXT,                 -- JSON: result, version, test results
    champion TEXT                 -- the working model after this round, JSON
);
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


def _locked(method):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


def seen_entry_walk(candles: list[dict], i: int, tf_seconds: int, seen_at: float,
                    seen_price: float) -> Optional[list[dict]]:
    """Candles for the engine so that the trade enters at seen_price in the candle the bot saw the signal
    in: the signal candle, then that candle flattened to the seen price (the engine enters at its open and
    finds nothing to hit in it), then the candles after it. None while that candle has not closed."""
    start = candles[i]["time"]
    seen_start = seen_at - (seen_at - start) % tf_seconds
    if seen_start <= start:
        seen_start = start + tf_seconds
    k = next((n for n in range(i + 1, len(candles)) if candles[n]["time"] == seen_start), None)
    if k is None:
        if seen_start > candles[-1]["time"]:
            return None          # not closed yet
        return candles[i:]       # a hole in the candles: the old way (next candle's open)
    flat = {**candles[k], "open": seen_price, "high": seen_price, "low": seen_price, "close": seen_price}
    return [candles[i], flat, *candles[k + 1:]]


class Memory:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # The bot loop and the web requests may use the memory from different threads.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.RLock()
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(signals)")}
        if "chance" not in columns:  # files from step A
            self.db.execute("ALTER TABLE signals ADD COLUMN chance REAL")  # the brain's chance of profit
        if "reliable" not in columns:  # before "remember every signal" all remembered signals were reliable
            self.db.execute("ALTER TABLE signals ADD COLUMN reliable INTEGER DEFAULT 1")
        if "source" not in columns:    # live: seen by the bot; history: rebuilt from past candles
            self.db.execute("ALTER TABLE signals ADD COLUMN source TEXT DEFAULT 'live'")
        if "seen_price" not in columns:   # price when the bot saw the signal (2026-11-04); empty on older ones
            self.db.execute("ALTER TABLE signals ADD COLUMN seen_price REAL")
        for name, kind in (("ai_decision", "TEXT"), ("ai_confidence", "REAL"), ("ai_reason", "TEXT")):
            if name not in columns:      # the AI's answer (Gemini) for the signals sent to it
                self.db.execute(f"ALTER TABLE signals ADD COLUMN {name} {kind}")
        self.db.execute("CREATE TABLE IF NOT EXISTS pretrain (chart TEXT PRIMARY KEY, done_at REAL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS signals_source ON signals(source, status)")
        self.db.commit()
        self.db.commit()

    @_locked
    def close(self) -> None:
        self.db.close()

    @staticmethod
    def key(symbol: str, timeframe: str, strategy: str, signal_time: int) -> str:
        return f"{symbol}|{timeframe}|{strategy}|{signal_time}"

    @_locked
    def record(self, entry: dict, timeframe: str, feats: dict, now: float, reliable: bool = True,
               seen_price: Optional[float] = None) -> str:
        """Remember a signal the bot saw (once). seen_price: the price at that moment (the live price);
        with it the result is worked out from when and where the bot could really have entered."""
        s = entry["signal"]
        key = self.key(entry["symbol"], timeframe, entry["strategy"], s["time"])
        self.db.execute(
            "INSERT OR IGNORE INTO signals (key, symbol, base, timeframe, strategy, side, signal_time, confirmed_at,"
            " seen_at, entry, stop, target, features, reliable, source, seen_price)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'live',?)",
            (key, entry["symbol"], entry["base"], timeframe, entry["strategy"], s["side"], s["time"],
             s.get("confirmedAt"), now, s["entry"], s["stopLoss"], s["takeProfit"], json.dumps(feats), int(reliable),
             seen_price))
        self.db.commit()
        return key

    @_locked
    def record_history(self, timeframe: str, rows: list[dict], now: float) -> int:
        """Remember past signals rebuilt from the candle history (already finished).
        A live record of the same signal always wins. Returns how many were new."""
        before = self.db.total_changes
        for row in rows:
            e, s = row["entry"], row["entry"]["signal"]
            key = self.key(e["symbol"], timeframe, e["strategy"], s["time"])
            self.db.execute(
                "INSERT OR IGNORE INTO signals (key, symbol, base, timeframe, strategy, side, signal_time, confirmed_at,"
                " seen_at, entry, stop, target, features, reliable, source, status, exit_time, exit_reason,"
                " pnl_percent, r, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'history',?,?,?,?,?,?)",
                (key, e["symbol"], e["base"], timeframe, e["strategy"], s["side"], s["time"], s["confirmedAt"], now,
                 s["entry"], s["stopLoss"], s["takeProfit"], json.dumps(row["features"]), int(row["reliable"]),
                 row["result"], row["exitTime"], row["exitReason"], row["pnlPercent"], row["r"], now))
        self.db.commit()
        return self.db.total_changes - before

    @_locked
    def pretrain_time(self, symbol: str, timeframe: str) -> Optional[float]:
        row = self.db.execute("SELECT done_at FROM pretrain WHERE chart = ?", (f"{symbol}|{timeframe}",)).fetchone()
        return row[0] if row else None

    @_locked
    def set_pretrain_time(self, symbol: str, timeframe: str, now: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO pretrain (chart, done_at) VALUES (?, ?)", (f"{symbol}|{timeframe}", now))
        self.db.commit()

    @_locked
    def mark(self, key: str, taken: bool = False, skip_reason: Optional[str] = None) -> None:
        if taken:
            self.db.execute("UPDATE signals SET taken = 1, skip_reason = NULL WHERE key = ?", (key,))
        else:
            self.db.execute("UPDATE signals SET skip_reason = ? WHERE key = ? AND taken = 0", (skip_reason, key))
        self.db.commit()

    @_locked
    def set_ai(self, key: str, decision: str, confidence: Optional[float], reason: str) -> None:
        """What the AI said about a signal: approve / reject / unavailable."""
        self.db.execute("UPDATE signals SET ai_decision = ?, ai_confidence = ?, ai_reason = ? WHERE key = ?",
                        (decision, confidence, reason[:300], key))
        self.db.commit()

    @_locked
    def ai_summary(self) -> dict:
        """Finished signals per AI decision: how the approved ones did against the rejected ones."""
        out = {}
        for decision, n, avg_r, wins in self.db.execute(
                "SELECT ai_decision, COUNT(*), AVG(r), SUM(r > 0) FROM signals"
                " WHERE ai_decision IS NOT NULL AND r IS NOT NULL GROUP BY ai_decision"):
            out[decision] = {"count": n, "avgR": avg_r, "winRate": 100.0 * (wins or 0) / n if n else None}
        return out

    @_locked
    def open_signals(self, symbol: str, timeframe: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT key, strategy, side, signal_time, stop, target, seen_at, seen_price FROM signals"
            " WHERE status = 'open' AND symbol = ? AND timeframe = ?", (symbol, timeframe)).fetchall()
        return [dict(zip(("key", "strategy", "side", "signal_time", "stop", "target", "seen_at", "seen_price"), r))
                for r in rows]

    @_locked
    def resolve(self, symbol: str, timeframe: str, candles: list[dict], params_of: dict[str, dict],
                fees: Fees = NO_FEES, now: Optional[float] = None) -> int:
        """Work out the result of open signals of this chart from its closed candles,
        with the same engine as the history test. Returns how many ended.

        With the price the bot saw the signal at (seen_price, signals from 2026-11-04 on), the entry is
        that price, in the candle the bot saw it in, as the paper bot would have entered (not at the open
        of the candle after the signal: the bot sees signals 20 s to minutes later). Like the paper bot,
        the rest of that candle is not checked (which part came after the entry is not known). A price
        already past the stop or the target means no trade (expired). Older signals: open of the next candle."""
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
            walk = candles[i:]
            if s.get("seen_price") and s.get("seen_at"):
                walk = seen_entry_walk(candles, i, TIMEFRAME_SECONDS[timeframe], s["seen_at"], s["seen_price"])
                if walk is None:
                    continue   # the candle the bot saw it in has not closed yet
            trades, _ = simulate(walk, [Signal(0, s["side"], stop_price=s["stop"], target_price=s["target"])],
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

    @_locked
    def save_trade(self, trade: dict, now: float) -> None:
        self.db.execute("INSERT INTO trades (closed_at, data) VALUES (?, ?)", (now, json.dumps(trade)))
        self.db.commit()

    @_locked
    def strategy_performance(self, brain_threshold: Optional[float] = None) -> dict[str, dict]:
        """How each strategy has really done, for the owner to compare (manual mode list).

        bot:     the paper bot's own closed trades (kept after "start again"): count, won %, net USDT.
        signals: every reliable live signal that ended, traded or not: count, won %, average R.
        brain:   the same signals that the brain's current filter lets through.
        """
        out: dict[str, dict] = {}

        def block(n, wins, avg):
            return {"count": n, "winRate": (wins or 0) / n * 100 if n else None, "avgR": avg}

        done = "source = 'live' AND reliable = 1 AND status IN ('win','loss','breakeven') AND r IS NOT NULL"
        for kind, n, wins, avg in self.db.execute(
                f"SELECT strategy, COUNT(*), SUM(status = 'win'), AVG(r) FROM signals WHERE {done} GROUP BY strategy"):
            out.setdefault(kind, {})["signals"] = block(n, wins, avg)
        if brain_threshold is not None:
            for kind, n, wins, avg in self.db.execute(
                    f"SELECT strategy, COUNT(*), SUM(status = 'win'), AVG(r) FROM signals WHERE {done}"
                    " AND chance IS NOT NULL AND chance >= ? GROUP BY strategy", (brain_threshold,)):
                out.setdefault(kind, {})["brain"] = block(n, wins, avg)
        bot: dict[str, list[float]] = {}
        for (data,) in self.db.execute("SELECT data FROM trades"):
            try:
                trade = json.loads(data)
                bot.setdefault(trade["strategy"], []).append(float(trade.get("pnl") or 0.0))
            except (ValueError, KeyError, TypeError):
                continue
        for kind, results in bot.items():
            out.setdefault(kind, {})["bot"] = {"count": len(results),
                                               "winRate": sum(1 for r in results if r > 0) / len(results) * 100,
                                               "netPnl": sum(results)}
        return out

    @_locked
    def strategy_results(self, since_exit_time: float) -> dict[str, float]:
        """Sum of results (percent) per strategy for signals that ended after a time."""
        rows = self.db.execute(
            "SELECT strategy, SUM(pnl_percent) FROM signals WHERE status IN ('win','loss','breakeven')"
            " AND source = 'live' AND reliable = 1 AND exit_time >= ? GROUP BY strategy", (since_exit_time,)).fetchall()
        return {k: v or 0.0 for k, v in rows}

    @_locked
    def strategy_counts(self, since_exit_time: float) -> dict[str, int]:
        """How many signals per strategy ended after a time (same signals as strategy_results)."""
        rows = self.db.execute(
            "SELECT strategy, COUNT(*) FROM signals WHERE status IN ('win','loss','breakeven')"
            " AND source = 'live' AND reliable = 1 AND exit_time >= ? GROUP BY strategy", (since_exit_time,)).fetchall()
        return dict(rows)

    @_locked
    def outcomes_since(self, since: float) -> list[tuple]:
        """Live reliable signals that came after a moment, were not traded and have ended:
        (end time, status, strategy). Used to see if the market fits the strategies again."""
        return self.db.execute(
            "SELECT exit_time, status, strategy FROM signals WHERE source = 'live' AND reliable = 1 AND taken = 0"
            " AND confirmed_at >= ? AND status IN ('win','loss') ORDER BY exit_time", (since,)).fetchall()

    @_locked
    def set_chance(self, key: str, chance: float) -> None:
        self.db.execute("UPDATE signals SET chance = ? WHERE key = ?", (chance, key))
        self.db.commit()

    @_locked
    def finished_signals(self, limit: int) -> list[dict]:
        """Signals that ended in a result (for learning): the newest live ones, then a sample of history."""
        names = ("signal_time", "strategy", "timeframe", "side", "features", "pnl_percent", "r", "reliable", "source")
        cols = ", ".join(names)
        done = "status IN ('win','loss','breakeven')"
        rows = self.db.execute(f"SELECT {cols} FROM signals WHERE {done} AND source = 'live'"
                               " ORDER BY signal_time DESC LIMIT ?", (limit,)).fetchall()
        # Past signals rebuilt from history: a random sample fills the rest (all coins and times mixed).
        rows += self.db.execute(f"SELECT {cols} FROM signals WHERE {done} AND source = 'history'"
                                " ORDER BY random() LIMIT ?", (max(0, limit - len(rows)),)).fetchall()
        return [dict(zip(names, r)) for r in rows]

    @_locked
    def save_training(self, outcome: dict, champion: Optional[str]) -> None:
        self.db.execute("INSERT INTO training (time, outcome, champion) VALUES (?,?,?)",
                        (outcome.get("time"), json.dumps(outcome), champion))
        self.db.commit()

    @_locked
    def last_training(self) -> Optional[dict]:
        row = self.db.execute("SELECT outcome FROM training ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    @_locked
    def load_model(self) -> Optional[str]:
        row = self.db.execute("SELECT champion FROM training WHERE champion IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    @_locked
    def summary(self) -> dict:
        """Live signals (what the bot itself saw) plus how many past ones were rebuilt."""
        total, reliable, open_, wins, losses, taken = self.db.execute(
            "SELECT COUNT(*), SUM(reliable = 1), SUM(status='open'), SUM(status='win'), SUM(status='loss'),"
            " SUM(taken = 1) FROM signals WHERE source = 'live'").fetchone()
        history = self.db.execute("SELECT COUNT(*) FROM signals WHERE source = 'history'").fetchone()[0]
        finished = self.db.execute(
            "SELECT COUNT(*) FROM signals WHERE status IN ('win','loss','breakeven')").fetchone()[0]
        trades = self.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        charts = self.db.execute("SELECT COUNT(*) FROM pretrain").fetchone()[0]
        return {"signals": total or 0, "reliable": reliable or 0, "open": open_ or 0, "wins": wins or 0,
                "losses": losses or 0, "ended": (total or 0) - (open_ or 0), "taken": taken or 0, "trades": trades,
                "history": history, "finished": finished, "charts": charts}
