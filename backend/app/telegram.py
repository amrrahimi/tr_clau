"""Telegram messages (owner 2026-11-09): a message for every closed position, and (later) for every
position the bot wants to close because the trend changed.

The owner's bot token stays on this computer (settings.json next to the data, never in the code and
never sent back to the screen). The chat is found by itself: the owner sends /start to his bot once,
then "test" reads the bot's updates and keeps that chat's id.
"""

from __future__ import annotations

import json
import math
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
               buttons: Optional[list] = None) -> None:
    """buttons: (label, data) shown under the message; the owner's tap comes back through answers()."""
    t = settings or load()
    if t["chatId"] is None:
        raise TelegramError("no chat")
    body: dict = {"chat_id": t["chatId"], "text": text}
    if buttons:
        rows = buttons if isinstance(buttons[0], list) else [buttons]   # one row, or rows of buttons
        body["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": data} for label, data in row]
                                                    for row in rows]}
    await _call(t["token"], "sendMessage", body, post)


# The last update read (so each tap is handled once); kept in memory, Telegram forgets read updates.
_offset: dict[str, int] = {}


# Managing one open position from Telegram (owner 2026-11-09): show it, new stop / target, break-even,
# close (asked twice).
MANAGE = ("pos", "est", "etp", "pbe", "pcl", "pcy")


def _number(text: str) -> Optional[float]:
    digits = text.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789."))
    try:
        value = float(digits)
    except ValueError:
        return None
    return value if value > 0 and math.isfinite(value) else None


def side_word(p: dict) -> str:
    return "لانگ" if p.get("side") == "long" else "شورت"


def position_buttons(rows: list[dict]) -> list[list[tuple[str, str]]]:
    """One button per open position, two in a row."""
    keys = [(f"{p['base']} {p['timeframe']} {side_word(p)}", f"pos:{p['id']}") for p in rows]
    return [keys[n:n + 2] for n in range(0, len(keys), 2)]


def manage_buttons(p: dict) -> list[list[tuple[str, str]]]:
    i = p["id"]
    return [[("✏️ حد ضرر", f"est:{i}"), ("✏️ حد سود", f"etp:{i}")],
            [("⚖️ سربه‌سر", f"pbe:{i}"), ("🔄 تازه کردن", f"pos:{i}")],
            [("❌ بستن", f"pcl:{i}")]]


STATUS_BUTTON = "📊 وضعیت ربات"
POSITIONS_BUTTON = "📈 پوزیشن‌های باز"
KEYBOARD = {"keyboard": [[{"text": STATUS_BUTTON}, {"text": POSITIONS_BUTTON}]], "resize_keyboard": True,
            "is_persistent": True}


async def answers(settings: dict, post: Post = default_post) -> list[dict]:
    """What the owner sent since the last look, from his own chat only:
    {"kind": "tap", "action": "close"|"hold", "id": position id, "query": query id} for a button under a message,
    {"kind": "ask", "what": "status"|"positions"|"start"} for the two fixed buttons or /status, /positions, /start."""
    body: dict = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
    if settings["token"] in _offset:
        body["offset"] = _offset[settings["token"]]
    answer = await _call(settings["token"], "getUpdates", body, post)
    out: list[dict] = []
    for update in answer.get("result") or []:
        _offset[settings["token"]] = int(update.get("update_id", 0)) + 1
        q = update.get("callback_query")
        if q:
            chat = ((q.get("message") or {}).get("chat") or {}).get("id")
            action, _, rest = str(q.get("data") or "").partition(":")
            if chat == settings["chatId"] and action in ("close", "hold") and rest.isdigit():
                out.append({"kind": "tap", "action": action, "id": int(rest), "query": str(q.get("id"))})
            elif chat == settings["chatId"] and action in ("rok", "rno", "panic") and rest.isdigit():
                out.append({"kind": "real", "action": action, "id": int(rest), "query": str(q.get("id"))})
            elif chat == settings["chatId"] and action in MANAGE and rest.isdigit():
                out.append({"kind": "manage", "action": action, "id": int(rest), "query": str(q.get("id"))})
            continue
        message = update.get("message") or {}
        if (message.get("chat") or {}).get("id") != settings["chatId"]:
            continue
        text = str(message.get("text") or "").strip()
        command = text.split()[0].split("@")[0].lower() if text else ""
        if text == STATUS_BUTTON or command == "/status":
            out.append({"kind": "ask", "what": "status"})
        elif text == POSITIONS_BUTTON or command == "/positions":
            out.append({"kind": "ask", "what": "positions"})
        elif command == "/closeall":
            out.append({"kind": "ask", "what": "closeall"})
        elif command == "/cancel":
            out.append({"kind": "ask", "what": "cancel"})
        elif _number(text) is not None:
            out.append({"kind": "number", "value": _number(text)})   # a new stop / target price
        elif text:
            out.append({"kind": "ask", "what": "start"})   # anything else: show the two buttons again
    return out


async def send_menu(text: str, settings: dict, post: Post = default_post) -> None:
    """A message with the two fixed buttons under the chat."""
    await _call(settings["token"], "sendMessage", {"chat_id": settings["chatId"], "text": text,
                                                   "reply_markup": KEYBOARD}, post)


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
    await send("✅ Leon به تلگرام وصل شد.", post, t)
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


STATES = {"running": "🟢 روشن", "stopped": "⚪️ خاموش", "paused": "⏸ متوقف", "halted": "🛑 متوقف (حد ضرر کل)"}
TRENDS = {"up": "صعودی", "down": "نزولی", "range": "رنج", None: "نامعلوم"}


def status_text(s: dict) -> str:
    """The owner asked "how is the bot?" (s: what the bot shows on its panel)."""
    state = STATES.get(s.get("status"), str(s.get("status")))
    if s.get("status") == "paused" and s.get("pauseReason"):
        state += f" ({s['pauseReason']})"
    total = s["equity"] - s["capital"]
    btc = s.get("btc") or {}
    lines = [f"وضعیت: {state}",
             f"موجودی: {s['equity']:.2f}$ · نتیجه‌ی کل: {_money(total)}",
             f"امروز: {_money(s.get('today') or 0.0)}",
             f"پوزیشن باز: {s['open']} · سفارش لیمیت منتظر: {s['orders']}",
             f"بیت‌کوین: ۱ ساعته {TRENDS.get(btc.get('1h'), '؟')} · ۴ ساعته {TRENDS.get(btc.get('4h'), '؟')}",
             f"قفل سود: {'روشن' if s.get('lock') else 'خاموش'} · بررسی دوره‌ای: {'روشن' if s.get('review') else 'خاموش'}"]
    return "\n".join(lines)


def positions_text(rows: list[dict], now: float) -> str:
    """Each open position: coin, timeframe, side, strategy; entry and price now; result now in $ and R;
    stop and target; lock / break-even; how long it has been open."""
    if not rows:
        return "هیچ پوزیشن بازی نیست."
    out = []
    for p in rows:
        side = "لانگ" if p["side"] == "long" else "شورت"
        price = p.get("price")
        result = p.get("pnl")
        risk = p.get("risk") or 0
        r = f" ({result / risk:+.2f}R)" if result is not None and risk else ""
        mark = "🟢" if (result or 0) > 0 else "🔴" if (result or 0) < 0 else "⚪️"
        extra = " · 🔒 قفل سود" if p.get("lockedAt") else " · سربه‌سر" if p.get("breakevenAt") else ""
        hours = max(0.0, now - p["entryTime"]) / 3600
        age = f"{hours * 60:.0f} دقیقه" if hours < 1 else f"{hours:.1f} ساعت" if hours < 48 else f"{hours / 24:.1f} روز"
        out.append(f"{mark} {p['base']} {p['timeframe']} {side} · {p['strategy']}\n"
                   f"ورود {p['entryPrice']} ← الان {price if price is not None else '؟'}: "
                   f"{_money(result) if result is not None else '؟'}{r}\n"
                   f"حد ضرر {p['stop']} · حد سود {p['takeProfit']}{extra}\n"
                   f"باز از {age} پیش")
    return "\n\n".join(out)
