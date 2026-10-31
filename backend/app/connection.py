"""How the engine reaches the exchange: directly or through a proxy.

Many VPN apps work in "proxy mode": only programs that use the computer's
proxy setting go through the VPN. A browser does; our engine did not, so at
home the exchange site opened in the browser while the engine got no answer.
Now the engine uses, in this order:
1. the proxy the owner typed in the app (kept in settings.json next to the data);
2. the computer's own proxy setting (Windows / macOS / environment);
3. a direct connection.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Optional


def data_folder() -> Path:
    custom = os.environ.get("TRADING_BOT_DATA")
    return Path(custom) if custom else Path.home() / ".trading-bot"


def settings_path() -> Path:
    return data_folder() / "settings.json"


def load_settings(path: Optional[Path] = None) -> dict:
    try:
        return json.loads((path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_proxy(proxy: str, path: Optional[Path] = None) -> None:
    path = path or settings_path()
    settings = load_settings(path)
    settings["proxy"] = proxy.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


def normalize(proxy: str) -> Optional[str]:
    """'127.0.0.1:10809' -> 'http://127.0.0.1:10809'. Empty -> None."""
    proxy = (proxy or "").strip()
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = "http://" + proxy
    return proxy


def system_proxy() -> Optional[str]:
    """The computer's proxy setting for https (or http), if any."""
    try:
        found = urllib.request.getproxies()
    except Exception:
        return None
    return normalize(found.get("https") or found.get("http") or "")


def current(path: Optional[Path] = None) -> tuple[Optional[str], str]:
    """(proxy url or None, where it came from: 'app' | 'system' | 'direct')."""
    typed = normalize(load_settings(path).get("proxy", ""))
    if typed:
        return typed, "app"
    found = system_proxy()
    if found:
        return found, "system"
    return None, "direct"
