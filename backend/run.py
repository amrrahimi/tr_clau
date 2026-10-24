"""Start the backend server on this computer only (127.0.0.1).

When the desktop app starts this program, it sets EXIT_WHEN_PARENT_CLOSES=1.
The backend then watches its input pipe: when the app closes (or crashes),
the pipe closes and the backend exits too, so no hidden copy keeps running
and blocking the port the next time you open the app.
"""

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


if __name__ == "__main__":
    if os.environ.get("EXIT_WHEN_PARENT_CLOSES") == "1":
        exit_when_parent_closes()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")
