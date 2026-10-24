"""The local server the frontend talks to.

HTTP endpoints answer one-off questions (which coins? which candles?).
The WebSocket endpoint stays open and pushes each changed candle.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .exchange import MarketDataError, MarketService, create_exchange
from .live import watch_candles

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

    async def get_service(market_type: str) -> MarketService:
        if market_type not in config.MARKET_TYPES:
            raise HTTPException(400, f"market_type must be one of {list(config.MARKET_TYPES)}")
        async with services_lock:
            if market_type not in services:
                services[market_type] = factory(market_type)
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
        }

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
