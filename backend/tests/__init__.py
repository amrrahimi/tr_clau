"""Tests never read or change the owner's real data (~/.trading-bot: settings.json with the proxy,
the AI model and keys, paper.json, memory.db). Every test run gets its own empty data folder,
unless TRADING_BOT_DATA was already set to a folder on purpose."""

import atexit
import os
import shutil
import tempfile

if not os.environ.get("TRADING_BOT_DATA"):
    _folder = tempfile.mkdtemp(prefix="trading-bot-tests-")
    os.environ["TRADING_BOT_DATA"] = _folder
    atexit.register(shutil.rmtree, _folder, ignore_errors=True)
