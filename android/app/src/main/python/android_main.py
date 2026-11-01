"""The engine on Android: the same backend as the desktop app, started by EngineService.

The service passes two folders: where the bot keeps its data (paper.json, memory.db, settings)
and where the built screen is. The engine serves both the API and the screen on
http://127.0.0.1:8765, so the app's WebView simply opens that address.
"""

import logging
import logging.handlers
import os


def run(data_dir: str, web_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    os.environ["TRADING_BOT_DATA"] = data_dir
    os.environ["TRADING_BOT_WEB"] = web_dir

    handler = logging.handlers.RotatingFileHandler(os.path.join(data_dir, "backend.log"),
                                                   maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    import uvicorn

    from app import config
    from app.server import app

    # asyncio + h11 + wsproto: the pure-Python choices that work on Android.
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning", log_config=None,
                loop="asyncio", http="h11", ws="wsproto")
