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

# The local server. 127.0.0.1 means only this computer can connect.
HOST = "127.0.0.1"
PORT = 8765
