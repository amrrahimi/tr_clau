"""The indicator catalog: one "spec card" per indicator.

Each card says everything about one indicator in one place: its name, whether
it is drawn on the price chart or in its own pane, its settings (TradingView's
defaults and allowed ranges), its output lines, guide levels and its formula.
The rest of the app only reads these cards; the screen builds its indicator
list and settings windows from them. Adding an indicator = adding one card.

An "instance" is one indicator placed on the chart with its own settings.
The same indicator can be placed several times (three EMAs = three instances).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import indicators as ind

Series = list[Optional[float]]


@dataclass(frozen=True)
class Param:
    name: str           # e.g. "length"; the screen translates it
    default: float
    min: float
    max: float
    step: float = 1     # 1 = whole numbers only


@dataclass(frozen=True)
class Output:
    key: str
    color: str
    style: str = "line"  # "line" or "histogram"


@dataclass(frozen=True)
class Candles:
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]


@dataclass(frozen=True)
class Spec:
    type: str                     # id used in requests, e.g. "ema"
    name: str                     # TradingView's short name, e.g. "EMA"
    pane: str                     # "price" (on the candles) or "own" (separate pane)
    params: tuple[Param, ...]
    outputs: tuple[Output, ...]
    compute: Callable[[Candles, dict], dict[str, Series]] = field(repr=False)
    levels: tuple[float, ...] = ()            # dashed guide lines, e.g. RSI 30/70
    scale: Optional[tuple[float, float]] = None  # fixed pane range, e.g. 0-100
    candle_colors: bool = False               # histogram coloured like the candles (Volume)

    def public(self) -> dict:
        """What the screen needs (everything except the formula)."""
        data = asdict(self)
        data.pop("compute")
        return data


# Colours for several instances of the same one-line indicator (EMA 9, 21, 50...).
LINE_PALETTE = ["#f7c948", "#ab47bc", "#26c6da", "#ff7043", "#66bb6a", "#ec407a"]

UP, DOWN = "#089981", "#f23645"

LENGTH = Param("length", 9, 1, 500)


def _one(key: str, fn) -> Callable[[Candles, dict], dict[str, Series]]:
    return lambda c, p: {key: fn(c, p)}


_SPECS = [
    Spec("ema", "EMA", "price", (LENGTH,), (Output("value", LINE_PALETTE[0]),),
         _one("value", lambda c, p: ind.ema(c.closes, int(p["length"])))),
    Spec("sma", "SMA", "price", (LENGTH,), (Output("value", "#2196f3"),),
         _one("value", lambda c, p: ind.sma(c.closes, int(p["length"])))),
    Spec("wma", "WMA", "price", (LENGTH,), (Output("value", "#f06292"),),
         _one("value", lambda c, p: ind.wma(c.closes, int(p["length"])))),
    Spec("bb", "BB", "price",
         (Param("length", 20, 1, 500), Param("mult", 2, 0.1, 10, 0.1)),
         (Output("basis", "#ff6d00"), Output("upper", "#2962ff"), Output("lower", "#2962ff")),
         lambda c, p: dict(zip(("upper", "basis", "lower"),
                               ind.bollinger(c.closes, int(p["length"]), float(p["mult"]))))),
    Spec("supertrend", "SuperTrend", "price",
         (Param("atr_length", 10, 1, 500), Param("factor", 3, 0.1, 20, 0.1)),
         (Output("up", UP), Output("down", DOWN)),
         lambda c, p: _supertrend(c, p)),
    Spec("volume", "Vol", "own", (), (Output("volume", "#26a69a", "histogram"),),
         _one("volume", lambda c, p: list(c.volumes)), candle_colors=True),
    Spec("rsi", "RSI", "own", (Param("length", 14, 2, 500),), (Output("rsi", "#7e57c2"),),
         _one("rsi", lambda c, p: ind.rsi(c.closes, int(p["length"]))),
         levels=(70, 30), scale=(0, 100)),
    Spec("macd", "MACD", "own",
         (Param("fast", 12, 1, 500), Param("slow", 26, 1, 500), Param("signal", 9, 1, 500)),
         (Output("hist", "#26a69a", "histogram"), Output("macd", "#2962ff"), Output("signal", "#ff6d00")),
         lambda c, p: dict(zip(("macd", "signal", "hist"),
                               ind.macd(c.closes, int(p["fast"]), int(p["slow"]), int(p["signal"]))))),
    Spec("stoch", "Stoch", "own",
         (Param("k_length", 14, 1, 500), Param("k_smoothing", 1, 1, 100), Param("d_smoothing", 3, 1, 100)),
         (Output("k", "#2962ff"), Output("d", "#ff6d00")),
         lambda c, p: dict(zip(("k", "d"), ind.stochastic(
             c.highs, c.lows, c.closes, int(p["k_length"]), int(p["k_smoothing"]), int(p["d_smoothing"])))),
         levels=(80, 20), scale=(0, 100)),
    Spec("stochrsi", "Stoch RSI", "own",
         (Param("k", 3, 1, 100), Param("d", 3, 1, 100), Param("rsi_length", 14, 2, 500), Param("stoch_length", 14, 1, 500)),
         (Output("k", "#2962ff"), Output("d", "#ff6d00")),
         lambda c, p: dict(zip(("k", "d"), ind.stoch_rsi(
             c.closes, int(p["k"]), int(p["d"]), int(p["rsi_length"]), int(p["stoch_length"])))),
         levels=(80, 20), scale=(0, 100)),
    Spec("atr", "ATR", "own", (Param("length", 14, 1, 500),), (Output("atr", "#b71c1c"),),
         _one("atr", lambda c, p: ind.atr(c.highs, c.lows, c.closes, int(p["length"])))),
    Spec("dmi", "DMI", "own",
         (Param("length", 14, 1, 500), Param("smoothing", 14, 1, 500)),
         (Output("adx", "#ff6d00"), Output("plus", "#2962ff"), Output("minus", "#f23645")),
         lambda c, p: dict(zip(("plus", "minus", "adx"), ind.dmi(
             c.highs, c.lows, c.closes, int(p["length"]), int(p["smoothing"])))),
         levels=(25, 20)),
]


def _supertrend(c: Candles, p: dict) -> dict[str, Series]:
    line, direction = ind.supertrend(c.highs, c.lows, c.closes, int(p["atr_length"]), float(p["factor"]))
    up: Series = [v if d == -1 else None for v, d in zip(line, direction)]
    down: Series = [v if d == 1 else None for v, d in zip(line, direction)]
    return {"up": up, "down": down}


SPECS: dict[str, Spec] = {s.type: s for s in _SPECS}
MAX_INSTANCES = 20


def public_catalog() -> list[dict]:
    return [s.public() for s in _SPECS]


@dataclass(frozen=True)
class Instance:
    id: str
    type: str
    params: dict


def parse_instances(raw) -> list[Instance]:
    """Check a list like [{"id": "a", "type": "ema", "params": {"length": 21}}].

    Missing settings get TradingView's default; anything unknown or out of
    range is refused with a message naming the problem.
    """
    if not isinstance(raw, list):
        raise ValueError("indicators must be a list")
    if len(raw) > MAX_INSTANCES:
        raise ValueError(f"at most {MAX_INSTANCES} indicators")
    seen = set()
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each indicator must be an object")
        kind = item.get("type")
        spec = SPECS.get(kind)  # type: ignore[arg-type]
        if spec is None:
            raise ValueError(f"unknown indicator: {kind}")
        iid = str(item.get("id") or f"{kind}-{len(out) + 1}")[:40]
        if iid in seen:
            raise ValueError(f"duplicate indicator id: {iid}")
        seen.add(iid)
        given = item.get("params") or {}
        if not isinstance(given, dict):
            raise ValueError(f"{kind}: params must be an object")
        unknown = set(given) - {p.name for p in spec.params}
        if unknown:
            raise ValueError(f"{kind}: unknown setting {sorted(unknown)[0]}")
        params = {}
        for p in spec.params:
            value = given.get(p.name, p.default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{kind}: {p.name} must be a number")
            if p.step == 1 and value != int(value):
                raise ValueError(f"{kind}: {p.name} must be a whole number")
            if not p.min <= value <= p.max:
                raise ValueError(f"{kind}: {p.name} must be between {p.min:g} and {p.max:g}")
            params[p.name] = int(value) if p.step == 1 else float(value)
        out.append(Instance(iid, spec.type, params))
    return out


def label(instance: Instance) -> str:
    """TradingView-style name with settings, e.g. "EMA 21", "BB 20 2", "MACD 12 26 9"."""
    spec = SPECS[instance.type]
    values = " ".join(f"{instance.params[p.name]:g}" for p in spec.params)
    return f"{spec.name} {values}".strip()


def compute_instances(candles: list[dict], instances: list[Instance], keep_last: int) -> list[dict]:
    """Lines for each instance over the given (closed) candles; only the last `keep_last` points are returned."""
    data = Candles(
        opens=[c["open"] for c in candles],
        highs=[c["high"] for c in candles],
        lows=[c["low"] for c in candles],
        closes=[c["close"] for c in candles],
        volumes=[c.get("volume", 0.0) for c in candles],
    )
    cut = max(0, len(candles) - keep_last)
    per_type_count: dict[str, int] = {}
    result = []
    for inst in instances:
        spec = SPECS[inst.type]
        order = per_type_count.get(inst.type, 0)
        per_type_count[inst.type] = order + 1
        series = spec.compute(data, inst.params)
        outputs = []
        for o in spec.outputs:
            color = o.color
            # Several EMAs (or SMAs...) each get their own colour.
            if len(spec.outputs) == 1 and spec.pane == "price":
                start = LINE_PALETTE.index(o.color) if o.color in LINE_PALETTE else 0
                color = LINE_PALETTE[(start + order) % len(LINE_PALETTE)] if order else o.color
            points = []
            for i in range(cut, len(candles)):
                v = series[o.key][i]
                if v is None:
                    continue
                point = {"time": candles[i]["time"], "value": v}
                if spec.candle_colors:
                    point["color"] = UP if data.closes[i] >= data.opens[i] else DOWN
                points.append(point)
            outputs.append({"key": o.key, "color": color, "style": o.style, "points": points})
        result.append({
            "id": inst.id,
            "type": inst.type,
            "name": spec.name,
            "label": label(inst),
            "pane": spec.pane,
            "params": inst.params,
            "levels": list(spec.levels),
            "scale": list(spec.scale) if spec.scale else None,
            "outputs": outputs,
        })
    return result
