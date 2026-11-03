"""The AI's second opinion (owner 2026-11-03): before the bot opens a trade on the chosen timeframes,
the signal and its market context go to Google's Gemini, which approves or rejects it with a short
reason. If Gemini cannot answer, the owner is asked in the panel.

The owner's API keys stay on this computer (settings.json next to the data, never in the code and
never sent back to the screen). Two keys from two Google projects double the free quota: when one
answers "too many requests" (429) the next one is tried.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Awaitable, Callable, Optional

from . import connection

# Google retires model names (owner 2026-11-03: "gemini-2.5-flash is no longer available to new
# users"). The bot tries these in order and remembers the first one the owner's key may use.
MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
MODEL = MODELS[0]
TIMEOUT_SECONDS = 40.0   # a "thinking" model through the VPN can take a while (owner saw timeouts at 25 s)
MAX_KEYS = 4
DEFAULT_TIMEFRAMES = ["15m", "30m", "1h", "4h"]   # 1m / 3m: the answer comes too late; 5m: allowed if ticked
CONTEXT_TIMEFRAMES = ["15m", "1h", "4h", "1d"]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# (url, headers, body) -> (status, text)
Post = Callable[[str, dict, dict], Awaitable[tuple[int, str]]]


class AdvisorUnavailable(Exception):
    """Gemini gave no usable answer (no key, network, quota, bad reply)."""


# ---------------------------------------------------------------- keys (on this computer only)

def load_keys() -> list[str]:
    keys = connection.load_settings().get("aiKeys") or []
    return [k for k in keys if isinstance(k, str) and k.strip()][:MAX_KEYS]


def save_keys(keys: list[str]) -> None:
    path = connection.settings_path()
    settings = connection.load_settings(path)
    settings["aiKeys"] = [k.strip() for k in keys if k and k.strip()][:MAX_KEYS]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


def load_model() -> str:
    """The model that answered last time (saved), else the first of the list."""
    saved = connection.load_settings().get("aiModel")
    return saved if isinstance(saved, str) and saved else MODEL


def save_model(model: str) -> None:
    path = connection.settings_path()
    settings = connection.load_settings(path)
    if settings.get("aiModel") == model:
        return
    settings["aiModel"] = model
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


OVERLOADED = (500, 502, 503, 504)   # "high demand, try again later" (owner saw 503 on 2026-11-03)


def with_model(body: dict, model: str) -> dict:
    """Ask for little "thinking": a yes/no on one trade does not need long reasoning, and thinking
    made the answer slow (timeouts). Gemini 3 uses thinkingLevel, 2.5 a thinking budget."""
    config = dict(body.get("generationConfig") or {})
    if model.startswith("gemini-3"):
        config["thinkingConfig"] = {"thinkingLevel": "low"}
    elif model.startswith("gemini-2.5"):
        config["thinkingConfig"] = {"thinkingBudget": 0}
    return {**body, "generationConfig": config}


def model_order(first: str) -> list[str]:
    return [first] + [m for m in MODELS if m != first]


def _model_gone(status: int, text: str) -> bool:
    """This model cannot be used with this key: retired / unknown (404) or no free quota at all."""
    if status == 404:
        return True
    lowered = (text or "").lower()
    return status == 429 and ("limit: 0" in lowered or "not available" in lowered)


def masked(keys: list[str]) -> list[str]:
    """What the screen may see of the keys: only the last 4 characters."""
    return ["…" + k[-4:] for k in keys]


# ---------------------------------------------------------------- the market context

def _ema(values: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    out, v = [], None
    for x in values:
        v = x if v is None else x * k + v * (1 - k)
        out.append(v)
    return out


def _rsi(closes: list[float], n: int = 14) -> Optional[float]:
    if len(closes) <= n:
        return None
    gain = loss = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gain, loss = gain + max(d, 0), loss + max(-d, 0)
    gain, loss = gain / n, loss / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = (gain * (n - 1) + max(d, 0)) / n
        loss = (loss * (n - 1) + max(-d, 0)) / n
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def summarize(candles: list[dict]) -> Optional[dict]:
    """Trend, momentum, volatility and volume of one chart, from its last candles."""
    if len(candles) < 30:
        return None
    closes = [c["close"] for c in candles]
    ema = _ema(closes, 50 if len(closes) >= 55 else 20)
    last = closes[-1]
    slope_up, slope_down = ema[-1] > ema[-6], ema[-1] < ema[-6]
    trend = "up" if last > ema[-1] and slope_up else "down" if last < ema[-1] and slope_down else "flat"
    trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
           for p, c in zip(candles, candles[1:])]
    atr = sum(trs[-14:]) / min(14, len(trs))
    vols = [c.get("volume") or 0 for c in candles]
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) > 21 else None
    rsi = _rsi(closes)
    return {"trend": trend, "price": last, "ema": round(ema[-1], 10),
            "rsi": None if rsi is None else round(rsi, 1),
            "atrPercent": round(atr / last * 100, 3) if last else None,
            "volumeVsAverage": round(vols[-1] / avg_vol, 2) if avg_vol else None,
            "change20Percent": round((last / closes[-21] - 1) * 100, 2) if len(closes) > 21 else None}


def swings(candles: list[dict], width: int = 3) -> dict:
    """The nearest swing high above and swing low below the last price (peaks / troughs)."""
    last = candles[-1]["close"]
    high = low = None
    for j in range(len(candles) - 1 - width, width - 1, -1):
        c = candles[j]
        around = candles[j - width:j] + candles[j + 1:j + 1 + width]
        if high is None and c["high"] > last and all(c["high"] > x["high"] for x in around):
            high = c["high"]
        if low is None and c["low"] < last and all(c["low"] < x["low"] for x in around):
            low = c["low"]
        if high is not None and low is not None:
            break
    return {"swingHighAbove": high, "swingLowBelow": low}


def brief(candidate: dict, timeframe: str, charts: dict[str, list[dict]], btc: dict[str, list[dict]]) -> dict:
    """Everything the AI sees about one signal: the bot's signal, the coin on several timeframes,
    Bitcoin (the market's direction) and the strategy's record on this coin."""
    s = candidate["signal"]
    entry, stop, target = s["entry"], s["stopLoss"], s["takeProfit"]
    own = charts.get(timeframe) or []
    stats = candidate.get("stats") or {}
    out = {
        "coin": candidate.get("base"), "timeframe": timeframe, "strategy": candidate.get("strategy"),
        "side": s["side"], "entry": entry, "stopLoss": stop, "takeProfit": target,
        "stopPercent": round(abs(entry - stop) / entry * 100, 3),
        "targetPercent": round(abs(target - entry) / entry * 100, 3),
        "rewardToRisk": round(abs(target - entry) / abs(entry - stop), 2) if entry != stop else None,
        "marketState": candidate.get("marketState"),
        "strategyHistoryOnThisCoin": {k: stats.get(k) for k in ("trades", "winRate", "profitFactor", "netPercent")},
        "timeframes": {tf: summarize(rows) for tf, rows in charts.items() if rows},
        "bitcoin": {tf: summarize(rows) for tf, rows in btc.items() if rows},
    }
    if own:
        out.update(swings(own))
        out["last30Candles"] = [[round(c["open"], 10), round(c["high"], 10), round(c["low"], 10),
                                 round(c["close"], 10), round(c.get("volume") or 0, 2)] for c in own[-30:]]
    return out


PROMPT = """You are a careful, experienced crypto futures trader reviewing a trade proposed by an
automated bot (paper trading, 1% of the account at risk). The bot found the signal below. Decide
whether to TAKE it with exactly this entry, stop-loss and take-profit, or SKIP it.

Weigh: agreement with the trend of the higher timeframes and of Bitcoin; whether the move is already
stretched (RSI extremes, a long run, fading volume) so the entry comes late; whether the stop sits
beyond the nearest swing high/low (a stop inside normal noise is easily hit); whether the target is
realistic for the recent range and volatility; the strategy's record on this coin. Most bot signals
lose money after fees, so be selective: approve only when the evidence clearly favours the trade.

Reply with JSON only: {"approve": true or false, "confidence": 0-100, "reason": "one short sentence in Persian (Farsi)"}

Signal and market data (candles are [open, high, low, close, volume], oldest first):
"""


def prompt_for(data: dict) -> str:
    return PROMPT + json.dumps(data, ensure_ascii=False, default=lambda x: None)


def parse(text: str) -> dict:
    """The model's JSON answer -> {"approve": bool, "confidence": float, "reason": str}."""
    found = re.search(r"\{.*\}", text or "", re.S)
    if not found:
        raise AdvisorUnavailable("no JSON in the answer")
    try:
        data = json.loads(found.group(0))
    except ValueError as error:
        raise AdvisorUnavailable(f"bad JSON: {error}") from error
    if not isinstance(data.get("approve"), bool):
        raise AdvisorUnavailable("no approve field")
    confidence = data.get("confidence")
    try:
        confidence = float(confidence)
        if math.isnan(confidence):
            confidence = None
    except (TypeError, ValueError):
        confidence = None
    return {"approve": data["approve"], "confidence": confidence, "reason": str(data.get("reason") or "")[:300]}


def ssl_context():
    """Trusted certificates from certifi (shipped with the app, like ccxt uses them). The packaged
    app has no system certificate list, so Google's certificate could not be checked (owner saw
    CERTIFICATE_VERIFY_FAILED on 2026-11-03)."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:   # no certifi: the system's list, as before
        return ssl.create_default_context()


async def default_post(url: str, headers: dict, body: dict) -> tuple[int, str]:
    """POST through the same proxy the bot uses for the exchange (VPN)."""
    import aiohttp
    proxy, _ = connection.current()
    connector = None
    kwargs = {}
    if proxy and proxy.startswith("socks"):
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(proxy)
    elif proxy:
        kwargs["proxy"] = proxy
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.post(url, headers=headers, json=body, ssl=ssl_context(), **kwargs) as response:
            return response.status, await response.text()


async def _call(body: dict, keys: list[str], model: Optional[str], post: Post,
                on_model: Optional[Callable[[str], None]]) -> str:
    """The model's text answer. Tries the models in order (a retired model or one with no free
    quota for this key -> the next) and the keys in order (429 / refused -> the next key)."""
    if not keys:
        raise AdvisorUnavailable("no API key")
    last = "no answer"
    for name in model_order(model or load_model()):
        gone = 0
        for key in keys:
            try:
                status, text = await _post_retry(post, URL.format(model=name),
                                                 {"x-goog-api-key": key, "Content-Type": "application/json"},
                                                 with_model(body, name))
            except (asyncio.TimeoutError, TimeoutError) as error:   # too slow: a lighter model may be quicker
                last = f"TimeoutError ({name}) after {TIMEOUT_SECONDS:.0f} s"
                gone = len(keys)
                break
            except Exception as error:   # network, proxy: another key or model will not do better
                raise AdvisorUnavailable(f"{type(error).__name__}: {error}"[:200]) from error
            if status == 400 and "thinking" in (text or "").lower():
                # This model does not take the thinking setting: ask once more without it.
                status, text = await post(URL.format(model=name), {"x-goog-api-key": key,
                                                                   "Content-Type": "application/json"}, body)
            if status == 200:
                try:
                    answer = json.loads(text)["candidates"][0]["content"]["parts"][0]["text"]
                except (ValueError, KeyError, IndexError, TypeError) as error:
                    raise AdvisorUnavailable("unexpected reply") from error
                if on_model is not None:
                    on_model(name)
                return answer
            last = f"HTTP {status} ({name}): {_message(text)}"[:200]
            if status in OVERLOADED:   # Google's servers for this model are busy: the next model
                gone = len(keys)
                break
            if _model_gone(status, text):
                gone += 1
                continue
            if status in (401, 403, 429):
                continue
            raise AdvisorUnavailable(last)
        if gone < len(keys):   # the model exists but every key is busy / refused: other models will not help
            break
    raise AdvisorUnavailable(last)


DROPPED = ("ServerDisconnectedError", "ClientOSError", "ClientConnectionError", "ClientPayloadError",
           "ConnectionResetError", "ProxyConnectionError", "ProxyError")
RETRIES = 2
RETRY_PAUSE = 1.5


async def _post_retry(post: Post, url: str, headers: dict, body: dict) -> tuple[int, str]:
    """The VPN tunnel sometimes drops a connection in the middle (owner saw "Server disconnected"):
    such a request is sent again, up to RETRIES more times. Timeouts are not retried here."""
    for attempt in range(RETRIES + 1):
        try:
            return await post(url, headers, body)
        except (asyncio.TimeoutError, TimeoutError):
            raise
        except Exception as error:
            if type(error).__name__ not in DROPPED and not isinstance(error, ConnectionError) or attempt == RETRIES:
                raise
            await asyncio.sleep(RETRY_PAUSE * (attempt + 1))
    raise AdvisorUnavailable("no answer")


def _message(text: str) -> str:
    try:
        return str(json.loads(text).get("error", {}).get("message", ""))[:150]
    except (ValueError, AttributeError):
        return (text or "")[:150]


async def ask(data: dict, keys: list[str], model: Optional[str] = None, post: Optional[Post] = None) -> dict:
    """Ask Gemini about one signal."""
    body = {"contents": [{"parts": [{"text": prompt_for(data)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    return parse(await _call(body, keys, model, post or default_post, save_model if post is None else None))


async def test_keys(keys: list[str], model: Optional[str] = None, post: Optional[Post] = None) -> list[dict]:
    """The panel's "test connection": per key, a tiny request -> [{key, ok, seconds, model, error}].
    The first model that answers is remembered for the trades."""
    import time
    body = {"contents": [{"parts": [{"text": 'Reply with the single word "OK".'}]}],
            "generationConfig": {"temperature": 0}}
    results = []
    for key in keys:
        started = time.monotonic()
        entry = {"key": masked([key])[0], "ok": False, "seconds": None, "model": None, "error": None}
        found: list[str] = []
        try:
            await _call(body, [key], model, post or default_post, found.append)
            entry.update(ok=True, model=found[0] if found else None)
            if post is None and found:
                save_model(found[0])
        except AdvisorUnavailable as error:
            entry["error"] = str(error)
        entry["seconds"] = round(time.monotonic() - started, 1)
        results.append(entry)
    return results
