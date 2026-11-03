"""Settings shared across the backend.

Every value here was agreed in the phase 1 design. Changing one of them
changes the app's behavior everywhere, which is why they live in one place.
"""

# The exchange the app connects to (ccxt's id for Toobit).
EXCHANGE_ID = "toobit"

# Market types the user can choose. The key is what the frontend sends;
# the value is ccxt's name for that kind of market.
# Futures on most exchanges are "perpetual swaps", which ccxt calls "swap".
MARKET_TYPES = {
    "spot": "spot",
    "futures": "swap",
}

# Only pairs priced in this currency are listed, so volumes are comparable.
QUOTE_CURRENCY = "USDT"

# How many coins the default list shows, ranked by 24h volume.
TOP_MARKETS_LIMIT = 50
SCANNER_COINS = 100  # the scanner looks at the 100 coins with the highest 24h volume (owner's choice)
# The bot's coins (owner 2026-11-03): "top" = SCANNER_COINS by volume, "volatile" = the coins that moved
# most in 24h among those with enough volume (thin coins fill at bad prices), "manual" = the owner's list.
VOLATILE_COINS = 30
VOLATILE_MIN_VOLUME = 1_000_000.0   # USDT traded in 24h
VOLATILE_REFRESH_SECONDS = 3600.0
MAX_MANUAL_COINS = 100

# Timeframes the user can pick, grouped by trading mode.
TIMEFRAME_GROUPS = {
    "scalping": ["1m", "3m", "5m", "15m"],
    "daily": ["15m", "30m", "1h", "2h", "4h", "6h", "1d"],
}
# Every timeframe once (15m is in both groups).
ALL_TIMEFRAMES = list(dict.fromkeys(tf for group in TIMEFRAME_GROUPS.values() for tf in group))

# Length of one candle in seconds, used to ask for older history.
TIMEFRAME_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
}

# How many past candles the chart loads.
DEFAULT_CANDLE_LIMIT = 500
MAX_CANDLE_LIMIT = 1000

# Seconds between requests for the latest candle (live updates).
POLL_INTERVAL_SECONDS = 2.0

# Seconds a ticker snapshot (24h volumes) is reused before asking again.
TICKER_CACHE_SECONDS = 60.0

# How long one request to the exchange may take. ccxt's own default (10 s) is
# too short through a VPN: the full futures ticker list is a large answer and
# often arrived after 10 s, so the bot round failed with "RequestTimeout".
EXCHANGE_TIMEOUT_MS = 30000

# A ticker request that fails because of the network is tried this many times
# in total, with a short pause between tries.
TICKER_ATTEMPTS = 3
TICKER_RETRY_PAUSE_SECONDS = 2.0

# If the exchange still cannot be reached, the last good ticker snapshot keeps
# being used for at most this long, so a short VPN drop does not stop the bot.
TICKER_STALE_MAX_SECONDS = 15 * 60.0

# The local server. 127.0.0.1 means only this computer can connect.
HOST = "127.0.0.1"
PORT = 8765

# Trading fees in percent of the order's value (Toobit, regular user, checked
# 2026-10-27 on toobit.com/en-US/support/fee-rate and the zero-fee announcement).
# Spot is 0% for website trading until 2026-12-26, but that campaign excludes
# API users, and the bot trades through the API, so the standard spot rate is used.
# The user can change these in the app.
DEFAULT_FEES = {
    "spot": {"maker": 0.075, "taker": 0.1},
    "futures": {"maker": 0.02, "taker": 0.06},
}
MAX_FEE = 1.0  # percent; anything above is surely a typing mistake

# A trade must be able to win at least as much as it can lose, after the taker fee on the way in
# and out: (target distance - fees) / (stop distance + fees) >= this. Reversion strategies aim
# back at an average (VWAP, Bollinger middle) that is often much closer than their stop; without
# this rule they won often but lost more on each stop than they made on each target.
MIN_REWARD_RISK = 1.0
