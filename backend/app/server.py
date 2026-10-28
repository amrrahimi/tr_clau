"""The local server the frontend talks to.

HTTP endpoints answer one-off questions (which coins? which candles?).
The WebSocket endpoint stays open and pushes each changed candle.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .analysis import ANALYSIS_CANDLES, analyze, run_strategy, strategy_overview
from .catalog import parse_instances, public_catalog
from .history import HistoryCache
from .scanner import Scanner, run_scan
from .strategies import RULES, STRATEGIES, Fees, parse_params, public_strategies
from .exchange import MarketDataError, MarketService, create_exchange
from .live import watch_candles
from .presets import MODE_EMAS

# Pages allowed to call this server: the desktop app (Windows and macOS
# addresses) and the frontend while it is being developed.
ALLOWED_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
]


def create_app(service_factory: Callable[[str], MarketService] | None = None) -> FastAPI:
    """Build the server. Tests can pass a factory that returns a fake exchange."""

    def default_factory(market_type: str) -> MarketService:
        return MarketService(create_exchange(market_type), market_type)

    factory = service_factory or default_factory
    services: dict[str, MarketService] = {}
    services_lock = asyncio.Lock()
    history = HistoryCache()  # long candle history for the strategies table
    scanner = Scanner()

    async def get_service(market_type: str) -> MarketService:
        if market_type not in config.MARKET_TYPES:
            raise HTTPException(400, f"market_type must be one of {list(config.MARKET_TYPES)}")
        async with services_lock:
            if market_type not in services:
                try:
                    services[market_type] = factory(market_type)
                except Exception as error:
                    # Turned into a normal error answer. A raw crash would reach
                    # the screen without permission headers, the browser would
                    # hide it, and the screen would wrongly say "backend not running".
                    raise HTTPException(500, f"Could not start the exchange connection: {error}")
            return services[market_type]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        for service in services.values():
            await service.close()

    app = FastAPI(title="Trading bot backend", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "exchange": config.EXCHANGE_ID}

    @app.get("/api/options")
    async def options():
        """Choices the frontend shows: market types and timeframe groups."""
        return {
            "exchange": config.EXCHANGE_ID,
            "marketTypes": list(config.MARKET_TYPES),
            "timeframes": config.TIMEFRAME_GROUPS,
            "fees": config.DEFAULT_FEES,
        }

    @app.get("/api/indicators/catalog")
    async def indicator_catalog():
        """Every indicator the app can draw, with its settings and defaults."""
        return {"indicators": public_catalog()}

    def fees_for(market_type: str, maker: float | None, taker: float | None) -> Fees:
        """The user's fee rates (percent), or the defaults of the market type."""
        default = config.DEFAULT_FEES.get(market_type, config.DEFAULT_FEES["spot"])
        chosen = Fees(default["maker"] if maker is None else maker, default["taker"] if taker is None else taker)
        for name, value in (("maker_fee", chosen.maker), ("taker_fee", chosen.taker)):
            if not 0 <= value <= config.MAX_FEE:
                raise HTTPException(400, f"{name} must be between 0 and {config.MAX_FEE:g} (percent)")
        return chosen

    @app.get("/api/strategies/catalog")
    async def strategy_catalog():
        """Cards of all strategies (names, suited market states, settings)."""
        return {"strategies": public_strategies()}

    @app.get("/api/strategies/run")
    async def strategy_run(
        symbol: str,
        timeframe: str,
        strategy: str,
        market_type: str = "spot",
        trading_mode: str = "daily",
        # Settings as JSON, e.g. {"fast": 9, "slow": 21}; missing ones get defaults.
        params: str = "{}",
        maker_fee: float | None = None,  # percent; default: the market type's rate
        taker_fee: float | None = None,
    ):
        fees = fees_for(market_type, maker_fee, taker_fee)
        if trading_mode not in MODE_EMAS:
            raise HTTPException(400, f"trading_mode must be one of {list(MODE_EMAS)}")
        try:
            settings = parse_params(strategy, json.loads(params), trading_mode)
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(400, f"params: {error}")
        service = await get_service(market_type)
        try:
            rows = await service.fetch_candles(symbol, timeframe, ANALYSIS_CANDLES)
        except MarketDataError as error:
            raise HTTPException(400, str(error))
        except Exception as error:
            raise HTTPException(502, f"Exchange request failed: {error}")
        result = run_strategy(rows, timeframe, strategy, settings, trading_mode, fees=fees)
        return {"symbol": symbol, "timeframe": timeframe, "marketType": market_type, **result}

    @app.get("/api/strategies/overview")
    async def strategies_overview(
        symbol: str,
        timeframe: str,
        market_type: str = "spot",
        trading_mode: str = "daily",
        # The user's changed settings per strategy, as JSON: {"ema_cross": {"fast": 12}}.
        settings: str = "{}",
        # The strategy whose trades are drawn on the chart ("" = none).
        active: str = "",
        # Automatic choice by the bot: "cautious" or "max_profit" ("" = manual, use `active`).
        auto_rule: str = "",
        maker_fee: float | None = None,  # percent; default: the market type's rate
        taker_fee: float | None = None,
    ):
        fees = fees_for(market_type, maker_fee, taker_fee)
        if trading_mode not in MODE_EMAS:
            raise HTTPException(400, f"trading_mode must be one of {list(MODE_EMAS)}")
        if active and active not in STRATEGIES:
            raise HTTPException(400, f"unknown strategy: {active}")
        if auto_rule and auto_rule not in RULES:
            raise HTTPException(400, f"auto_rule must be one of {list(RULES)}")
        try:
            given = json.loads(settings)
            if not isinstance(given, dict):
                raise ValueError("settings must be an object")
            unknown = set(given) - set(STRATEGIES)
            if unknown:
                raise ValueError(f"unknown strategy: {sorted(unknown)[0]}")
            checked = {kind: parse_params(kind, given.get(kind), trading_mode) for kind in STRATEGIES}
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(400, f"settings: {error}")
        service = await get_service(market_type)
        try:
            # 5000 candles: more trades, so the table's numbers are more trustworthy.
            rows = await history.get(
                (market_type, symbol, timeframe),
                lambda limit, before: service.fetch_candles(symbol, timeframe, limit, before=before),
            )
        except MarketDataError as error:
            raise HTTPException(400, str(error))
        except Exception as error:
            raise HTTPException(502, f"Exchange request failed: {error}")
        result = strategy_overview(rows, timeframe, checked, active or None, trading_mode,
                                   auto_rule=auto_rule or None, fees=fees)
        return {"symbol": symbol, "timeframe": timeframe, "marketType": market_type, **result}

    @app.get("/api/scanner")
    async def scan(
        timeframe: str,
        market_type: str = "spot",
        trading_mode: str = "daily",
        settings: str = "{}",            # same as /api/strategies/overview
        maker_fee: float | None = None,
        taker_fee: float | None = None,
    ):
        """Every strategy on every coin of the top list. Starts a scan in the
        background (or a new one after a candle closed) and answers at once
        with its progress; ask again until `running` is false."""
        if trading_mode not in MODE_EMAS:
            raise HTTPException(400, f"trading_mode must be one of {list(MODE_EMAS)}")
        if timeframe not in config.ALL_TIMEFRAMES:
            raise HTTPException(400, f"Unsupported timeframe: {timeframe}")
        fees = fees_for(market_type, maker_fee, taker_fee)
        try:
            given = json.loads(settings)
            if not isinstance(given, dict):
                raise ValueError("settings must be an object")
            unknown = set(given) - set(STRATEGIES)
            if unknown:
                raise ValueError(f"unknown strategy: {sorted(unknown)[0]}")
            checked = {kind: parse_params(kind, given.get(kind), trading_mode) for kind in STRATEGIES}
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(400, f"settings: {error}")
        service = await get_service(market_type)

        async def coins():
            return [(m.symbol, m.base) for m in await service.top_markets()]

        async def candles(symbol):
            return await history.get(
                (market_type, symbol, timeframe),
                lambda limit, before: service.fetch_candles(symbol, timeframe, limit, before=before),
            )

        key = Scanner.key(market_type, timeframe, trading_mode, checked, fees)
        current = scanner.get_or_start(
            key, timeframe, lambda job: run_scan(job, coins, candles, timeframe, trading_mode, checked, fees))
        return {"marketType": market_type, "timeframe": timeframe, **current.public()}

    @app.get("/api/markets")
    async def markets(market_type: str = "spot", query: str = ""):
        service = await get_service(market_type)
        try:
            if query.strip():
                infos = await service.search_markets(query)
            else:
                infos = await service.top_markets()
        except MarketDataError as error:
            raise HTTPException(400, str(error))
        except Exception as error:
            raise HTTPException(502, f"Exchange request failed: {error}")
        return {"marketType": market_type, "markets": [info.to_dict() for info in infos]}

    @app.get("/api/candles")
    async def candles(
        symbol: str,
        timeframe: str,
        market_type: str = "spot",
        limit: int = Query(config.DEFAULT_CANDLE_LIMIT),
        before: int | None = None,
    ):
        service = await get_service(market_type)
        try:
            rows = await service.fetch_candles(symbol, timeframe, limit, before=before)
        except MarketDataError as error:
            raise HTTPException(400, str(error))
        except Exception as error:
            raise HTTPException(502, f"Exchange request failed: {error}")
        return {"symbol": symbol, "timeframe": timeframe, "marketType": market_type, "candles": rows}

    @app.get("/api/analysis")
    async def analysis(
        symbol: str,
        timeframe: str,
        market_type: str = "spot",
        trading_mode: str = "scalping",
        auto: bool = True,
        # The user's indicator list (used when auto is false), as JSON:
        # [{"id": "a", "type": "ema", "params": {"length": 21}}, ...]
        indicators: str = "[]",
    ):
        if trading_mode not in MODE_EMAS:
            raise HTTPException(400, f"trading_mode must be one of {list(MODE_EMAS)}")
        instances = None
        if not auto:
            try:
                instances = parse_instances(json.loads(indicators))
            except (ValueError, json.JSONDecodeError) as error:
                raise HTTPException(400, f"indicators: {error}")
        service = await get_service(market_type)
        try:
            rows = await service.fetch_candles(symbol, timeframe, ANALYSIS_CANDLES)
        except MarketDataError as error:
            raise HTTPException(400, str(error))
        except Exception as error:
            raise HTTPException(502, f"Exchange request failed: {error}")
        result = analyze(rows, timeframe, trading_mode, instances)
        return {"symbol": symbol, "timeframe": timeframe, "marketType": market_type, **result}

    @app.websocket("/ws/candles")
    async def live_candles(websocket: WebSocket, symbol: str, timeframe: str, market_type: str = "spot"):
        await websocket.accept()
        try:
            service = await get_service(market_type)
            await service.ensure_symbol(symbol)
            if timeframe not in config.ALL_TIMEFRAMES:
                raise MarketDataError(f"Unsupported timeframe: {timeframe}")
            async for candle in watch_candles(service, symbol, timeframe):
                await websocket.send_json({"type": "candle", "candle": candle})
        except WebSocketDisconnect:
            return  # the user switched coin or closed the app
        except (MarketDataError, HTTPException) as error:
            detail = getattr(error, "detail", None) or str(error)
            await websocket.send_json({"type": "error", "message": detail})
            await websocket.close()
        except Exception as error:
            await websocket.send_json({"type": "error", "message": f"Live updates stopped: {error}"})
            await websocket.close()

    return app


app = create_app()
