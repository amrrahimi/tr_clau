"""Start the backend server on this computer only (127.0.0.1).

When the desktop app starts this program, it sets EXIT_WHEN_PARENT_CLOSES=1.
The backend then watches its input pipe: when the app closes (or crashes),
the pipe closes and the backend exits too, so no hidden copy keeps running
and blocking the port the next time you open the app.
"""

import logging
import logging.handlers
import os
import sys
import threading

import uvicorn

from app import config
from app.server import app


def exit_when_parent_closes() -> None:
    def watch() -> None:
        try:
            while sys.stdin.buffer.read(1024):
                pass  # the app never writes anything; we only wait for the pipe to close
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def log_to_file() -> None:
    """Problems are written to backend.log next to the bot's data (~/.trading-bot), so a crash can be explained."""
    from app.paper import default_path

    folder = default_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / "backend.log", maxBytes=1_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)

    def unhandled(kind, value, tb):
        logging.getLogger("trading_bot").critical("crash", exc_info=(kind, value, tb))
    sys.excepthook = unhandled


if __name__ == "__main__":
    log_to_file()
    if os.environ.get("EXIT_WHEN_PARENT_CLOSES") == "1":
        exit_when_parent_closes()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning", log_config=None)
