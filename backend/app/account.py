"""The owner's real Toobit account (owner 2026-11-09), in stages he chooses:

- off:    nothing.
- read:   reads balance, positions and orders; never sends anything.
- shadow: as read, and for every position the paper bot opens it works out the real order it would send
          (size from the real balance, leverage, stop, target) and only records it.
- real:   sends those orders. Safety rules:
          * the stop-loss and take-profit sit on the exchange itself (so a sleeping computer is still protected);
            if they cannot be placed, the position is closed at once;
          * the owner's caps: margin per trade, leverage, loss per day (reached -> no new real trades);
          * optional confirmation on Telegram before each trade (no answer in CONFIRM_SECONDS -> not opened);
          * an emergency button (app, Telegram /closeall) closes every real position and stops real trading.
          Real positions follow the paper ones: a moved stop is moved on the exchange too, and a paper
          position closed for any reason closes the real one.

The API key and secret stay on this computer (settings.json, "exchangeAccount"); they are never shown on the
screen, written to the repository, or sent to the AI. The key should have withdrawals switched OFF.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

from . import config, connection

log = logging.getLogger("trading_bot")

MODES = ("off", "read", "shadow", "real")
REFRESH_SECONDS = 15.0
CONFIRM_SECONDS = 60.0
RISK = 0.01                  # of the real balance per trade, like the paper bot
KEEP_PLANS = 50
DEFAULTS = {"mode": "off", "maxMargin": 10.0, "maxLeverage": 5, "dailyLoss": 5.0, "confirm": True}
LIMITS = {"maxMargin": (1.0, 100000.0), "maxLeverage": (1, 20), "dailyLoss": (0.5, 100000.0)}

Factory = Callable[[str, str], Any]   # (api key, secret) -> ccxt async exchange


def default_factory(key: str, secret: str):
    import ccxt.async_support as ccxt_async
    exchange = getattr(ccxt_async, config.EXCHANGE_ID)({
        "apiKey": key, "secret": secret, "enableRateLimit": True, "timeout": config.EXCHANGE_TIMEOUT_MS,
        "options": {"defaultType": config.MARKET_TYPES["futures"]},
    })
    proxy, _ = connection.current()
    if proxy:
        if proxy.startswith("socks"):
            exchange.socks_proxy = proxy
        else:
            exchange.http_proxy = proxy
    return exchange


def load() -> dict:
    x = connection.load_settings().get("exchangeAccount") or {}
    out = {**DEFAULTS, **{k: x[k] for k in DEFAULTS if k in x}}
    out["apiKey"] = x.get("apiKey") or ""
    out["secret"] = x.get("secret") or ""
    return out


def save(**changes) -> dict:
    path = connection.settings_path()
    settings = connection.load_settings(path)
    current = settings.get("exchangeAccount") or {}
    current.update(changes)
    settings["exchangeAccount"] = current
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")
    return load()


class AccountError(Exception):
    pass


def _num(x) -> Optional[float]:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


class ExchangeAccount:
    def __init__(self, factory: Factory = default_factory, clock: Callable[[], float] = time.time,
                 notify: Optional[Callable[..., None]] = None):
        self.factory = factory
        self.now = clock
        self.notify = notify or (lambda *a, **k: None)
        self._exchange = None
        self._key = None
        self.snapshot: dict = {}
        self.error: Optional[str] = None
        self.refreshed: Optional[float] = None
        self.capabilities: dict = {}
        self.plans: list[dict] = []          # shadow / real order plans, newest last
        self.links: dict[int, dict] = {}     # paper position id -> real position record
        self.waiting: dict[int, dict] = {}   # paper position id -> plan waiting for the owner's Telegram answer
        self.halted: Optional[str] = None    # why real trading stopped (daily loss, emergency, protection failed)
        self.day: Optional[int] = None
        self.day_start: Optional[float] = None
        self.lock = asyncio.Lock()
        self._load_links()

    # Real positions the bot opened are remembered in a file (2026-11-11): before, closing the app forgot them,
    # so a paper close or a moved stop after a restart never reached the exchange (the position then lived
    # on with only its first stop and target).
    @staticmethod
    def _links_path():
        return connection.settings_path().with_name("real-links.json")

    def _load_links(self) -> None:
        try:
            data = json.loads(self._links_path().read_text(encoding="utf-8"))
            self.links = {int(k): v for k, v in data.items() if isinstance(v, dict) and v.get("status") == "open"}
        except (OSError, ValueError, AttributeError):
            self.links = {}

    def _save_links(self) -> None:
        try:
            path = self._links_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({str(k): v for k, v in self.links.items() if v.get("status") == "open"}),
                            encoding="utf-8")
        except OSError:
            log.warning("could not save the real position links", exc_info=True)

    # ------------------------------------------------------------ settings

    def settings(self) -> dict:
        return load()

    def set(self, key: Optional[str] = None, secret: Optional[str] = None, mode: Optional[str] = None,
            limits: Optional[dict] = None, confirm: Optional[bool] = None, agree_real: bool = False) -> None:
        changes: dict = {}
        if key is not None or secret is not None:
            key, secret = (key or "").strip(), (secret or "").strip()
            if len(key) > 300 or len(secret) > 300:
                raise AccountError("bad key")
            changes.update(apiKey=key, secret=secret)
            self._drop_exchange()
            self.snapshot, self.error, self.capabilities = {}, None, {}
        if mode is not None:
            if mode not in MODES:
                raise AccountError("bad mode")
            if mode == "real" and not agree_real:
                raise AccountError("agree_real")
            changes["mode"] = mode
            if mode != "real":
                self.waiting.clear()
        for name, value in (limits or {}).items():
            if name in LIMITS and value is not None:
                low, high = LIMITS[name]
                value = float(value)
                if not low <= value <= high:
                    raise AccountError(f"bad {name}")
                changes[name] = int(value) if name == "maxLeverage" else value
        if confirm is not None:
            changes["confirm"] = bool(confirm)
        if changes:
            save(**changes)

    def public(self) -> dict:
        s = load()
        key = s["apiKey"]
        return {"mode": s["mode"], "key": bool(key and s["secret"]), "keyHint": f"…{key[-4:]}" if key else "",
                "maxMargin": s["maxMargin"], "maxLeverage": s["maxLeverage"], "dailyLoss": s["dailyLoss"],
                "confirm": s["confirm"], "snapshot": self.snapshot, "error": self.error, "refreshed": self.refreshed,
                "capabilities": self.capabilities, "plans": self.plans[-20:], "halted": self.halted,
                "waiting": len(self.waiting), "dayStart": self.day_start,
                "linked": [{"paperId": k, **{x: v.get(x) for x in ("symbol", "side", "amount", "status")}}
                           for k, v in self.links.items()]}

    # ------------------------------------------------------------ talking to the exchange

    def _drop_exchange(self) -> None:
        ex, self._exchange, self._key = self._exchange, None, None
        if ex is not None:
            try:
                asyncio.get_running_loop().create_task(ex.close())
            except RuntimeError:
                pass

    def _client(self):
        s = load()
        if not (s["apiKey"] and s["secret"]):
            raise AccountError("no key")
        if self._exchange is None or self._key != s["apiKey"]:
            self._drop_exchange()
            self._exchange = self.factory(s["apiKey"], s["secret"])
            self._key = s["apiKey"]
        return self._exchange

    async def refresh(self) -> dict:
        """Balance, open positions and open orders (read only)."""
        ex = self._client()
        try:
            balance = await ex.fetch_balance()
            positions = await ex.fetch_positions() if ex.has.get("fetchPositions") else []
            orders = await ex.fetch_open_orders() if ex.has.get("fetchOpenOrders") else []
        except Exception as error:
            self.error = f"{type(error).__name__}: {str(error)[:200]}"
            raise AccountError(self.error) from None
        usdt = balance.get("USDT") or {}
        self.snapshot = {
            "total": _num(usdt.get("total")), "free": _num(usdt.get("free")), "used": _num(usdt.get("used")),
            "positions": [{"symbol": p.get("symbol"), "side": p.get("side"), "contracts": _num(p.get("contracts")),
                           "entryPrice": _num(p.get("entryPrice")), "markPrice": _num(p.get("markPrice")),
                           "pnl": _num(p.get("unrealizedPnl")), "leverage": _num(p.get("leverage")),
                           "liquidation": _num(p.get("liquidationPrice")), "notional": _num(p.get("notional"))}
                          for p in positions if _num(p.get("contracts"))],
            "orders": [{"symbol": o.get("symbol"), "side": o.get("side"), "type": o.get("type"),
                        "amount": _num(o.get("amount")), "price": _num(o.get("price")),
                        "trigger": _num(o.get("triggerPrice") or o.get("stopPrice"))} for o in orders],
        }
        self.error = None
        self.refreshed = self.now()
        self._daily_check()
        return self.snapshot

    def equity(self) -> Optional[float]:
        s = self.snapshot
        if s.get("total") is None:
            return None
        return s["total"] + sum(p.get("pnl") or 0.0 for p in s.get("positions", []))

    def _daily_check(self) -> None:
        equity = self.equity()
        if equity is None:
            return
        day = int(self.now() // 86400)
        if day != self.day:
            self.day, self.day_start = day, equity
            if self.halted and self.halted.startswith("daily"):
                self.halted = None   # a new day
        limit = load()["dailyLoss"]
        if self.day_start is not None and equity <= self.day_start - limit and not self.halted:
            self.halted = f"daily loss {self.day_start - equity:.2f}$"
            self.notify(f"🛑 حساب واقعی: ضرر امروز به سقف {limit}$ رسید؛ ربات واقعی تا فردا معامله‌ی تازه باز نمی‌کند.")

    async def test(self) -> dict:
        """Owner's "test": one read, and what this exchange lets the bot do."""
        ex = self._client()
        await self.refresh()
        self.capabilities = {k: bool(ex.has.get(k)) for k in (
            "fetchBalance", "fetchPositions", "fetchOpenOrders", "createOrder", "setLeverage",
            "createOrderWithTakeProfitAndStopLoss", "createStopLossOrder", "createTakeProfitOrder",
            "cancelOrder", "cancelAllOrders")}
        return self.public()

    async def forever(self) -> None:
        while True:
            try:
                s = load()
                if s["mode"] != "off" and s["apiKey"] and s["secret"]:
                    await self.refresh()
                    self._expire_waiting()
            except asyncio.CancelledError:
                raise
            except AccountError:
                pass
            except Exception:
                log.warning("real account round failed", exc_info=True)
            await asyncio.sleep(REFRESH_SECONDS)

    # ------------------------------------------------------------ following the paper bot

    def plan(self, p: dict, price: Optional[float] = None) -> dict:
        """The real order for a paper position: risk 1% of the real balance, inside the owner's caps."""
        s = load()
        price = price or p["entryPrice"]
        plan = {"time": self.now(), "paperId": p["id"], "symbol": p["symbol"], "base": p.get("base"),
                "side": p["side"], "price": price, "stop": p["stop"], "target": p["takeProfit"], "status": None}
        equity = self.equity()
        long_ = p["side"] == "long"
        distance = (price - p["stop"]) if long_ else (p["stop"] - price)
        if equity is None or equity <= 0:
            return {**plan, "status": "skip: no balance read"}
        if distance <= 0 or ((p["takeProfit"] - price) if long_ else (price - p["takeProfit"])) <= 0:
            return {**plan, "status": "skip: price already past the stop or target"}
        amount = equity * RISK / distance
        leverage = max(1, min(int(p.get("leverage") or 1), int(s["maxLeverage"])))
        margin = amount * price / leverage
        if margin > s["maxMargin"]:
            amount *= s["maxMargin"] / margin
            margin = s["maxMargin"]
        free = self.snapshot.get("free")
        if free is not None and margin > free:
            return {**plan, "status": "skip: not enough free margin", "margin": margin}
        return {**plan, "amount": amount, "leverage": leverage, "margin": margin,
                "risk": amount * distance, "status": "planned"}

    def _remember(self, plan: dict) -> dict:
        self.plans.append(plan)
        del self.plans[:-KEEP_PLANS]
        return plan

    async def on_open(self, p: dict, price: Optional[float] = None) -> None:
        s = load()
        if s["mode"] not in ("shadow", "real") or not s["apiKey"]:
            return
        try:
            if not self.snapshot or self.refreshed is None or self.now() - self.refreshed > 60:
                await self.refresh()
        except AccountError:
            pass
        plan = self.plan(p, price)
        if s["mode"] == "shadow" or plan["status"] != "planned":
            if plan["status"] == "planned":
                plan["status"] = "shadow"
            self._remember(plan)
            return
        if self.halted:
            self._remember({**plan, "status": f"skip: stopped ({self.halted})"})
            return
        if s["confirm"]:
            plan["status"] = "waiting"
            self.waiting[p["id"]] = plan
            self._remember(plan)
            side = "لانگ" if p["side"] == "long" else "شورت"
            self.notify(f"❓ معامله‌ی واقعی باز کنم؟ {p.get('base')} {p.get('timeframe')} {side}\n"
                        f"مارجین {plan['margin']:.2f}$ · اهرم {plan['leverage']}x · ریسک {plan['risk']:.2f}$\n"
                        f"حد ضرر {p['stop']} · حد سود {p['takeProfit']}\n"
                        f"بی‌جواب تا {int(CONFIRM_SECONDS)} ثانیه: باز نمی‌شود.",
                        buttons=[("باز کن", f"rok:{p['id']}"), ("نه", f"rno:{p['id']}")])
            return
        self._remember(plan)
        await self._open(plan)

    def _expire_waiting(self) -> None:
        for pid, plan in list(self.waiting.items()):
            if self.now() - plan["time"] > CONFIRM_SECONDS:
                plan["status"] = "skip: no answer"
                self.waiting.pop(pid, None)

    async def answer(self, paper_id: int, yes: bool, still_open: bool) -> str:
        """The owner's Telegram answer to "open a real trade?"."""
        plan = self.waiting.pop(paper_id, None)
        if plan is None:
            return "دیر شد یا دیگر منتظر نیست."
        if not yes:
            plan["status"] = "skip: owner said no"
            return "باز نشد."
        if not still_open:
            plan["status"] = "skip: paper position already closed"
            return "پوزیشن پیپر بسته شده؛ باز نشد."
        await self._open(plan)
        return "باز شد." if plan["status"] == "open" else f"باز نشد: {plan['status']}"

    # Toobit's own futures API (ccxt's unified calls cannot place a stop-loss on Toobit, CI 2026-11-09):
    #   POST api/v1/futures/order                  {symbol: BTC-SWAP-USDT, side: BUY_OPEN|SELL_OPEN,
    #                                               type: LIMIT, priceType: MARKET, quantity (contracts)}
    #   POST api/v1/futures/position/trading-stop  {symbol, side: LONG|SHORT, stopLoss, takeProfit}
    #   POST api/v1/futures/flashClose             {symbol, side: LONG|SHORT}  (market close of the position)

    @staticmethod
    def _contracts(ex, symbol: str, base_amount: float) -> float:
        size = _num((ex.market(symbol) or {}).get("contractSize")) or 1.0
        return float(ex.amount_to_precision(symbol, base_amount / size))

    @staticmethod
    async def _set_stops(ex, symbol: str, long_: bool, stop: float, target: float) -> None:
        answer = await ex.privatePostApiV1FuturesPositionTradingStop({
            "symbol": ex.market(symbol)["id"], "side": "LONG" if long_ else "SHORT",
            "stopLoss": ex.price_to_precision(symbol, stop), "takeProfit": ex.price_to_precision(symbol, target)})
        if isinstance(answer, dict) and answer.get("code") not in (None, 0, 200, "0", "200"):
            raise AccountError(f"trading-stop: {answer.get('msg') or answer.get('code')}")

    @staticmethod
    async def _flash_close(ex, symbol: str, long_: bool) -> None:
        await ex.privatePostApiV1FuturesFlashClose({"symbol": ex.market(symbol)["id"],
                                                    "side": "LONG" if long_ else "SHORT"})

    async def _open(self, plan: dict) -> None:
        """Market entry, then the stop-loss and take-profit on the exchange. No protection -> closed at once."""
        async with self.lock:
            ex = self._client()
            symbol, long_ = plan["symbol"], plan["side"] == "long"
            try:
                await ex.load_markets()
                contracts = self._contracts(ex, symbol, plan["amount"])
                if contracts <= 0:
                    raise AccountError("amount below the exchange minimum")
                if ex.has.get("setLeverage"):
                    try:
                        await ex.set_leverage(plan["leverage"], symbol)
                    except Exception as error:
                        log.warning("set leverage: %r", error)
                order = await ex.privatePostApiV1FuturesOrder({
                    "symbol": ex.market(symbol)["id"], "side": "BUY_OPEN" if long_ else "SELL_OPEN",
                    "type": "LIMIT", "priceType": "MARKET", "quantity": str(contracts),
                    "newClientOrderId": f"leon{plan['paperId']}t{int(self.now())}"})
                plan.update(contracts=contracts, orderId=(order or {}).get("orderId"))
            except Exception as error:
                plan["status"] = f"error: {type(error).__name__}: {str(error)[:150]}"
                self.notify(f"⚠️ معامله‌ی واقعی {plan.get('base')} باز نشد: {plan['status']}")
                return
            record = {"symbol": symbol, "side": plan["side"], "amount": contracts, "status": "open"}
            self.links[plan["paperId"]] = record
            self._save_links()
            try:
                await self._set_stops(ex, symbol, long_, plan["stop"], plan["target"])
            except Exception as error:
                # never leave a real position without its stop
                plan["status"] = f"error: protection failed ({type(error).__name__}); closed"
                await self._close_market(ex, record)
                self._save_links()
                self.halted = "protection failed"
                self.notify(f"🛑 حد ضرر روی صرافی ثبت نشد؛ پوزیشن واقعی {plan.get('base')} فوراً بسته شد و "
                            "ربات واقعی متوقف شد. ({})".format(str(error)[:120]))
                return
            plan["status"] = "open"
            self.notify(f"✅ معامله‌ی واقعی باز شد: {plan.get('base')} {'لانگ' if long_ else 'شورت'} "
                        f"{contracts} قرارداد · مارجین {plan['margin']:.2f}$ · حد ضرر روی صرافی {plan['stop']}")

    async def _close_market(self, ex, record: dict) -> None:
        try:
            await self._flash_close(ex, record["symbol"], record["side"] == "long")
        except Exception as error:
            log.warning("real close %s: %r", record["symbol"], error)
            self.notify(f"⚠️ بستن پوزیشن واقعی {record['symbol']} انجام نشد: {str(error)[:120]} — در Toobit بررسی کنید.")
            return
        record["status"] = "closed"

    async def on_close(self, p: dict, reason: str) -> None:
        """The paper position closed: the real one follows (it may already be closed by its own stop / target)."""
        record = self.links.get(p["id"])
        self.waiting.pop(p["id"], None)
        if record is None or record["status"] != "open" or load()["mode"] != "real":
            return
        async with self.lock:
            ex = self._client()
            still = True
            try:
                positions = await ex.fetch_positions([record["symbol"]])
                still = any(_num(x.get("contracts")) for x in positions if x.get("symbol") == record["symbol"])
            except Exception:
                pass
            if still:
                await self._close_market(ex, record)
            else:
                record["status"] = "closed"   # its own stop / target on the exchange closed it
            self._save_links()

    async def on_levels(self, p: dict) -> None:
        """The paper stop / target moved (lock, break-even, the owner's drag): move them on the exchange."""
        record = self.links.get(p["id"])
        if record is None or record["status"] != "open" or load()["mode"] != "real":
            return
        async with self.lock:
            ex = self._client()
            try:
                await self._set_stops(ex, record["symbol"], record["side"] == "long", p["stop"], p["takeProfit"])
            except Exception as error:
                log.warning("real stop move failed: %r", error)
                self.notify(f"⚠️ جابه‌جایی حد ضرر واقعی {record['symbol']} انجام نشد؛ حد ضرر قبلی سر جایش است.")

    async def panic(self) -> str:
        """Emergency: close every real position, cancel every order, stop real trading."""
        self.halted = "emergency"
        self.waiting.clear()
        ex = self._client()
        closed = 0
        async with self.lock:
            try:
                positions = await ex.fetch_positions()
            except Exception as error:
                return f"خطا در خواندن پوزیشن‌ها: {str(error)[:120]}"
            for x in positions:
                amount = _num(x.get("contracts"))
                if not amount:
                    continue
                record = {"symbol": x["symbol"], "side": x.get("side"), "amount": amount, "status": "open"}
                await self._close_market(ex, record)
                closed += record["status"] == "closed"
            try:
                if ex.has.get("cancelAllOrders"):
                    await ex.cancel_all_orders()
            except Exception:
                pass
            for record in self.links.values():
                record["status"] = "closed"
            self._save_links()
        save(mode="read")
        return f"{closed} پوزیشن واقعی بسته شد؛ حالت به «فقط خواندن» برگشت."

    def resume(self) -> None:
        self.halted = None

    def summary_line(self) -> Optional[str]:
        s = load()
        if s["mode"] == "off" or not s["apiKey"]:
            return None
        names = {"read": "فقط خواندن", "shadow": "سایه", "real": "واقعی"}
        equity = self.equity()
        text = f"حساب واقعی ({names[s['mode']]}): " + (f"{equity:.2f}$" if equity is not None else "خوانده نشده")
        text += f" · پوزیشن {len(self.snapshot.get('positions', []))}"
        if self.halted:
            text += f" · متوقف ({self.halted})"
        return text
