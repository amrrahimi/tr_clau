"""The bot's learning part (step B): a signal filter that learns from the memory.

Every reliable signal the bot saw is in the memory with the conditions at that
moment and how it ended (traded or only followed). From these the brain learns
which signals tend to end in profit, and the bot then skips the weak ones.

How (in simple words):
- Model: logistic regression, written in plain Python (no big libraries, so the
  app stays small). It gives each signal a chance of ending in profit.
- Honest test: signals are sorted by time; the model learns from the older 70%
  and is judged only on the newest 30%, which it never saw ("walk-forward").
- Threshold: on the learning part, the cut that would have earned the most
  (in R = multiples of the risk) while keeping at least a quarter of signals.
- Champion / challenger: every few hours a new model (challenger) is trained.
  It replaces the working model (champion) only if, on signals neither of them
  learned from, it earned more and also beat "take every signal".
  If the champion itself does worse than "take every signal" on new data, it is
  switched off until a better one appears.
- Until there are enough finished signals the brain only collects; the bot
  works without the filter.

The brain lives in the memory file, so "start again" of the paper account
never erases it.
"""

from __future__ import annotations

import json
import math
import time
from typing import Optional

from .presets import STATES
from .strategies import STRATEGIES

TIMEFRAMES = ["1m", "3m", "5m", "15m", "1h"]
MIN_SAMPLES = 300        # finished signals needed before the first model
MIN_TEST = 60            # unseen signals needed to judge a model
MIN_KEPT = 10            # a model must let at least this many test signals through
KEEP_PART = 0.25         # the threshold keeps at least this share of signals
TRAIN_PART = 0.7
MAX_ROWS = 12000         # finished signals used for learning (all live ones first, then a sample of history)
LIVE_TEST = 200          # from this many finished live signals on, the final test uses live signals only
EPOCHS = 150
LEARNING_RATE = 0.5
L2 = 0.01
RETRAIN_SECONDS = 6 * 3600

# What the numbers of a signal mean. A model made for other numbers (for example before a
# new strategy was added) cannot be used and is made again.
SIGNATURE = "v2|" + ",".join(STATES) + "|" + ",".join(TIMEFRAMES) + "|" + ",".join(STRATEGIES)

NUMERIC = ["adx", "atrRatio", "stopPercent", "rewardRatio", "feeShare", "histTrades",
           "histWinRate", "histProfitFactor", "histNetPercent"]


def _num(value, low=None, high=None) -> Optional[float]:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return float(value)


def raw_vector(feats: dict, strategy: str, timeframe: str, side: str, history: bool = False) -> list[Optional[float]]:
    """Numbers describing one signal (None = unknown, filled with the average later)."""
    stop = _num(feats.get("stopPercent"), 1e-4)
    trades = _num(feats.get("histTrades"), 0)
    v: list[Optional[float]] = [
        _num(feats.get("adx"), 0, 100),
        _num(feats.get("atrRatio"), 0, 10),
        math.log(stop) if stop is not None else None,
        _num(feats.get("rewardRatio"), 0, 10),
        _num(feats.get("feeShare"), 0, 2),
        math.log1p(trades) if trades is not None else None,
        _num(feats.get("histWinRate"), 0, 100),
        _num(feats.get("histProfitFactor"), 0, 5),
        _num(feats.get("histNetPercent"), -100, 100),
    ]
    hour = feats.get("hourUtc")
    day = feats.get("weekday")
    v += [math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)] if hour is not None else [None, None]
    v += [math.sin(2 * math.pi * day / 7), math.cos(2 * math.pi * day / 7)] if day is not None else [None, None]
    v += [1.0 if feats.get("marketState") == s else 0.0 for s in STATES]
    v += [1.0 if timeframe == t else 0.0 for t in TIMEFRAMES]
    v += [1.0 if strategy == k else 0.0 for k in STRATEGIES]
    v.append(1.0 if side == "long" else 0.0)
    v.append(1.0 if feats.get("reliable", True) else 0.0)  # passed the cautious conditions
    v.append(1.0 if history else 0.0)                       # rebuilt from past candles (live signals: 0)
    return v


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


class Model:
    def __init__(self, weights: list[float], bias: float, mean: list[float], std: list[float],
                 threshold: float, info: dict):
        self.weights, self.bias, self.mean, self.std = weights, bias, mean, std
        self.threshold = threshold
        self.info = info   # version, trainedAt, cutoff, samples, test results ...

    def _scaled(self, raw: list[Optional[float]]) -> list[float]:
        return [0.0 if x is None else (x - m) / s for x, m, s in zip(raw, self.mean, self.std)]

    def chance_raw(self, raw: list[Optional[float]]) -> float:
        x = self._scaled(raw)
        return _sigmoid(self.bias + sum(w * a for w, a in zip(self.weights, x)))

    def chance(self, feats: dict, strategy: str, timeframe: str, side: str) -> float:
        return self.chance_raw(raw_vector(feats, strategy, timeframe, side))

    def to_json(self) -> str:
        return json.dumps({"weights": self.weights, "bias": self.bias, "mean": self.mean, "std": self.std,
                           "threshold": self.threshold, "info": self.info})

    @classmethod
    def from_json(cls, text: str) -> "Model":
        d = json.loads(text)
        return cls(d["weights"], d["bias"], d["mean"], d["std"], d["threshold"], d["info"])


def fit(raws: list[list[Optional[float]]], labels: list[int]) -> tuple[list[float], float, list[float], list[float]]:
    """Logistic regression by plain gradient descent on standardized numbers."""
    n, k = len(raws), len(raws[0])
    mean, std = [], []
    for j in range(k):
        col = [r[j] for r in raws if r[j] is not None]
        m = sum(col) / len(col) if col else 0.0
        var = sum((c - m) ** 2 for c in col) / len(col) if col else 0.0
        mean.append(m)
        std.append(math.sqrt(var) if var > 1e-12 else 1.0)
    xs = [[0.0 if x is None else (x - m) / s for x, m, s in zip(r, mean, std)] for r in raws]
    w = [0.0] * k
    base = sum(labels) / n
    b = math.log(base / (1 - base)) if 0 < base < 1 else 0.0
    for _ in range(EPOCHS):
        gw = [0.0] * k
        gb = 0.0
        for x, y in zip(xs, labels):
            err = _sigmoid(b + sum(wi * xi for wi, xi in zip(w, x))) - y
            gb += err
            for j, xj in enumerate(x):
                if xj:
                    gw[j] += err * xj
        b -= LEARNING_RATE * gb / n
        w = [wi - LEARNING_RATE * (g / n + L2 * wi) for wi, g in zip(w, gw)]
    return w, b, mean, std


def results(rs: list[float]) -> dict:
    """Summary of a set of signal results (in R)."""
    n = len(rs)
    return {"count": n, "sumR": sum(rs), "avgR": sum(rs) / n if n else None,
            "winRate": sum(1 for r in rs if r > 0) / n * 100 if n else None}


def best_threshold(chances: list[float], rs: list[float]) -> float:
    """The cut that would have earned the most, keeping at least KEEP_PART of the signals."""
    order = sorted(zip(chances, rs), key=lambda p: -p[0])
    least = max(1, math.ceil(len(order) * KEEP_PART))
    best, best_sum, total = 0.0, -math.inf, 0.0
    for i, (c, r) in enumerate(order, 1):
        total += r
        if i >= least and total > best_sum:
            best_sum, best = total, c
    return best


def judge(model: Model, rows: list[dict]) -> dict:
    """How a model would have done on these signals: the ones it lets through vs all."""
    kept = [r["r"] for r in rows if model.chance_raw(r["raw"]) >= model.threshold]
    return {"kept": results(kept), "all": results([r["r"] for r in rows])}


def training_rows(memory, limit: int = MAX_ROWS) -> list[dict]:
    out = []
    for row in memory.finished_signals(limit):
        try:
            feats = json.loads(row["features"] or "{}")
        except ValueError:
            continue
        r = row["r"]
        if r is None:
            stop = feats.get("stopPercent")
            if not stop or row["pnl_percent"] is None:
                continue
            r = row["pnl_percent"] / stop
        reliable_ = bool(row["reliable"]) if row.get("reliable") is not None else True
        feats.setdefault("reliable", reliable_)
        history = row.get("source") == "history"
        out.append({"time": row["signal_time"], "r": float(r), "label": 1 if r > 0 else 0, "reliable": reliable_,
                    "history": history,
                    "raw": raw_vector(feats, row["strategy"], row["timeframe"], row["side"], history)})
    out.sort(key=lambda r: r["time"])
    return out


def split(rows: list[dict]) -> tuple[list[dict], list[dict], str]:
    """Learning part and test part. With enough live signals the test is the newest live ones
    (and nothing from the same period is learned from); before that, the newest part of everything."""
    live = [r for r in rows if not r["history"]]
    if len(live) >= LIVE_TEST:
        test = live[int(len(live) * TRAIN_PART):]
        start = test[0]["time"]
        return [r for r in rows if r["time"] < start], test, "live"
    cut = int(len(rows) * TRAIN_PART)
    return rows[:cut], rows[cut:], "history"


class Brain:
    def __init__(self, memory, now=time.time):
        self.memory = memory
        self.now = now
        self.champion: Optional[Model] = None
        self.last: Optional[dict] = None  # last training: time and outcome
        text = memory.load_model()
        if text:
            try:
                self.champion = Model.from_json(text)
            except (ValueError, KeyError):
                self.champion = None
        if self.champion is not None and self.champion.info.get("signature") != SIGNATURE:
            self.champion = None   # made for other numbers (e.g. before new strategies): learn again
        self.last = memory.last_training()

    # ---- the bot asks

    def active(self) -> bool:
        return self.champion is not None and self.champion.info.get("on", True)

    def chance(self, feats: dict, strategy: str, timeframe: str, side: str) -> Optional[float]:
        if self.champion is None:
            return None
        return self.champion.chance(feats, strategy, timeframe, side)

    def allows(self, chance: Optional[float]) -> bool:
        return not self.active() or chance is None or chance >= self.champion.threshold

    def due(self, now: float) -> bool:
        return (self.last is None or now - self.last.get("time", 0) >= RETRAIN_SECONDS
                or (self.champion is None and self.last.get("result") == "few"
                    and self.memory.summary()["finished"] >= MIN_SAMPLES))

    # ---- learning

    def train(self) -> dict:
        """One learning round: train a challenger, compare with the champion, keep the better."""
        now = self.now()
        rows = training_rows(self.memory)
        outcome = self._train(rows, now)
        outcome["time"] = now
        outcome["samples"] = len(rows)
        self.last = outcome
        self.memory.save_training(outcome, self.champion.to_json() if self.champion else None)
        return outcome

    def _train(self, rows: list[dict], now: float) -> dict:
        if len(rows) < MIN_SAMPLES:
            return {"result": "few"}
        train, test, tested_on = split(rows)
        # The bot trades only reliable signals, so the filter is judged on those.
        exam = [r for r in test if r["reliable"]]
        if len(exam) < MIN_TEST or len(train) < MIN_TEST or len({r["label"] for r in train}) < 2:
            return {"result": "few"}
        w, b, mean, std = fit([r["raw"] for r in train], [r["label"] for r in train])
        challenger = Model(w, b, mean, std, 0.0, {})
        pool = [r for r in train if r["reliable"]]
        if len(pool) < MIN_TEST:
            pool = train
        challenger.threshold = best_threshold([challenger.chance_raw(r["raw"]) for r in pool], [r["r"] for r in pool])
        mine = judge(challenger, exam)
        version = (self.champion.info.get("version", 0) if self.champion else 0) + 1
        challenger.info = {"version": version, "trainedAt": now, "cutoff": train[-1]["time"],
                           "samples": len(train), "test": mine, "testedOn": tested_on, "on": True,
                           "signature": SIGNATURE}

        # Judge the champion only on signals it never learned from.
        old = None
        if self.champion is not None:
            unseen = [r for r in exam if r["time"] > self.champion.info.get("cutoff", 0)]
            if len(unseen) < MIN_TEST:
                unseen = exam
            old = judge(self.champion, unseen)
            mine_same = judge(challenger, unseen)
        beats_all = mine["kept"]["count"] >= MIN_KEPT and mine["kept"]["avgR"] > (mine["all"]["avgR"] or 0)
        if beats_all and (old is None or mine_same["kept"]["sumR"] > old["kept"]["sumR"]):
            self.champion = challenger
            return {"result": "promoted", "version": version, "test": mine, "testedOn": tested_on}
        if old is not None:
            champion_ok = (old["kept"]["count"] >= MIN_KEPT
                           and old["kept"]["avgR"] is not None and old["kept"]["avgR"] > (old["all"]["avgR"] or 0))
            self.champion.info["on"] = champion_ok
            self.champion.info["recent"] = old
            self.champion.info["recentOn"] = tested_on
            return {"result": "kept" if champion_ok else "off", "version": self.champion.info.get("version"),
                    "test": old, "challenger": mine, "testedOn": tested_on}
        return {"result": "weak", "challenger": mine, "testedOn": tested_on}

    # ---- the screen

    def public(self, summary: Optional[dict] = None) -> dict:
        finished = (summary or self.memory.summary())["finished"]
        c = self.champion
        model = None
        if c is not None:
            test = c.info.get("recent") or c.info.get("test") or {}
            tested_on = c.info.get("recentOn") if c.info.get("recent") else c.info.get("testedOn")
            model = {"version": c.info.get("version"), "trainedAt": c.info.get("trainedAt"),
                     "threshold": c.threshold, "on": c.info.get("on", True), "test": test,
                     "testedOn": tested_on or "live"}
        state = "active" if self.active() else ("off" if c is not None else "collecting")
        last_time = self.last.get("time") if self.last else None
        return {"state": state, "samples": finished, "needed": MIN_SAMPLES, "model": model,
                "lastTraining": self.last, "nextTraining": (last_time + RETRAIN_SECONDS) if last_time else None}
