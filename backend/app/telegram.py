"""Telegram messages (owner 2026-11-09): a message for every closed position, and (later) for every
position the bot wants to close because the trend changed.

The owner's bot token stays on this computer (settings.json next to the data, never in the code and
never sent back to the screen). The chat is found by itself: the owner sends /start to his bot once,
then "test" reads the bot's updates and keeps that chat's id.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable, Optional

from . import connection

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_SECONDS = 20.0

# (url, body) -> (status, text)
Post = Callable[[str, dict], Awaitable[tuple[int, str]]]

REASONS = {"target": "حد سود", "stop": "حد ضرر", "breakeven": "سربه‌سر", "lock": "قفل سود",
           "timeBe": "سربه‌سر زمانی", "manual": "بستن دستی", "gap": "گپ قیمت", "trend": "تغییر روند",
           "review": "تغییر روند (بررسی دوره‌ای)", "cap": "سقف سود"}


class TelegramError(Exception):
    """Telegram did not take the message (no token, no chat, network, refused)."""


# ---------------------------------------------------------------- settings (on this computer only)

def load() -> dict:
    t = connection.load_settings().get("telegram") or {}
    return {"token": t.get("token") or "", "chatId": t.get("chatId"), "enabled": t.get("enabled", True)}


def save(**changes) -> dict:
    path = connection.settings_path()
    settings = connection.load_settings(path)
    t = {**load(), **changes}
    settings["telegram"] = t
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")
    return t


def public() -> dict:
    """What the screen may see: never the token itself."""
    t = load()
    token = t["token"]
    return {"token": bool(token), "tokenHint": f"…{token[-4:]}" if token else "", "chat": t["chatId"] is not None,
            "enabled": bool(t["enabled"])}


# ---------------------------------------------------------------- talking to Telegram

async def default_post(url: str, body: dict) -> tuple[int, str]:
    """POST through the same proxy the bot uses for the exchange (VPN)."""
    import aiohttp
    from .advisor import ssl_context
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
        async with session.post(url, json=body, ssl=ssl_context(), **kwargs) as response:
            return response.status, await response.text()


async def _call(token: str, method: str, body: dict, post: Post) -> dict:
    if not token:
        raise TelegramError("no token")
    try:
        status, text = await post(API.format(token=token, method=method), body)
    except Exception as error:   # network / proxy
        raise TelegramError(f"network: {type(error).__name__}") from None
    try:
        answer = json.loads(text)
    except ValueError:
        raise TelegramError(f"HTTP {status}") from None
    if status != 200 or not answer.get("ok"):
        raise TelegramError(str(answer.get("description") or f"HTTP {status}"))
    return answer


async def find_chat(token: str, post: Post) -> Optional[int]:
    """The chat of the last message sent to the bot (the owner's /start)."""
    answer = await _call(token, "getUpdates", {"limit": 20}, post)
    for update in reversed(answer.get("result") or []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            return int(chat["id"])
    return None


async def send(text: str, post: Post = default_post, settings: Optional[dict] = None,
               buttons: Optional[list[tuple[str, str]]] = None) -> None:
    """buttons: (label, data) shown under the message; the owner's tap comes back through answers()."""
    t = settings or load()
    if t["chatId"] is None:
        raise TelegramError("no chat")
    body: dict = {"chat_id": t["chatId"], "text": text}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in buttons]]}
    await _call(t["token"], "sendMessage", body, post)


# The last update read (so each tap is handled once); kept in memory, Telegram forgets read updates.
_offset: dict[str, int] = {}


async def answers(settings: dict, post: Post = default_post) -> list[tuple[str, int, str]]:
    """The owner's taps since the last look: (action "close"|"hold", position id, query id).
    Only taps from the owner's own chat count."""
    body: dict = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
    if settings["token"] in _offset:
        body["offset"] = _offset[settings["token"]]
    answer = await _call(settings["token"], "getUpdates", body, post)
    out = []
    for update in answer.get("result") or []:
        _offset[settings["token"]] = int(update.get("update_id", 0)) + 1
        q = update.get("callback_query")
        if not q:
            continue
        chat = ((q.get("message") or {}).get("chat") or {}).get("id")
        action, _, rest = str(q.get("data") or "").partition(":")
        if chat != settings["chatId"] or action not in ("close", "hold") or not rest.isdigit():
            continue
        out.append((action, int(rest), str(q.get("id"))))
    return out


async def reply(settings: dict, query_id: str, text: str, post: Post = default_post) -> None:
    """A short note on the owner's tap (shown at the top of Telegram)."""
    await _call(settings["token"], "answerCallbackQuery", {"callback_query_id": query_id, "text": text}, post)


async def test(post: Post = default_post) -> dict:
    """Finds the chat if it is not known yet (after the owner's /start), then sends a test message."""
    t = load()
    if not t["token"]:
        raise TelegramError("no token")
    if t["chatId"] is None:
        chat = await find_chat(t["token"], post)
        if chat is None:
            raise TelegramError("no chat: send /start to your bot first")
        t = save(chatId=chat)
    await send("✅ ربات معامله‌گر به تلگرام وصل شد.", post, t)
    return public()


# ---------------------------------------------------------------- the words

def _money(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}{abs(x):.2f}$"


def closed_text(trade: dict, balance: float) -> str:
    pnl = trade.get("pnl") or 0.0
    mark = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪️"
    side = "لانگ" if trade.get("side") == "long" else "شورت"
    reason = REASONS.get(trade.get("exitReason") or "", trade.get("exitReason") or "")
    risk = trade.get("risk") or 0
    r = f" ({pnl / risk:+.2f}R)" if risk else ""
    return (f"{mark} پوزیشن بسته شد: {trade.get('base')} {trade.get('timeframe')} {side}\n"
            f"استراتژی: {trade.get('strategy')}\n"
            f"دلیل: {reason}\n"
            f"نتیجه: {_money(pnl)}{r}\n"
            f"ورود {trade.get('entryPrice')} ← خروج {trade.get('exitPrice')}\n"
            f"موجودی: {balance:.2f}$")


def closing_text(p: dict, why: str, price: Optional[float]) -> str:
    """The bot wants to close a position because the trend changed (used by the timed review)."""
    side = "لانگ" if p.get("side") == "long" else "شورت"
    at = f"\nقیمت فعلی: {price}" if price is not None else ""
    return f"⚠️ روند عوض شد، ربات می‌خواهد ببندد: {p.get('base')} {p.get('timeframe')} {side}\nدلیل: {why}{at}"


def opened_text(p: dict) -> str:
    """Short (owner 2026-11-09): position, state, price."""
    side = "لانگ" if p.get("side") == "long" else "شورت"
    kind = "لیمیت پر شد" if p.get("entryType") == "limit" else "ورود بازار"
    return (f"🔵 پوزیشن باز شد: {p.get('base')} {p.get('timeframe')} {side}\n"
            f"وضعیت: {kind} · اهرم {p.get('leverage')}x\n"
            f"قیمت: {p.get('entryPrice')} · حد ضرر {p.get('stopLoss')} · حد سود {p.get('takeProfit')}")
