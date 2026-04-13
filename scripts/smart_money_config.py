#!/usr/bin/env python3
"""Configuration for smart-money research system."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.home() / '.hermes' / '.env')

# Default channel list from your specification
DEFAULT_CHANNELS = [
    -1002611628536, -1003544951490, 777000, 5667863958,
    -1001927494975, -1001758611100, -1003435139579, -1001523523939,
    -1001810124798, -1001578710430, -1001697697574, -1001164734593,
    5434266369, 259643624, -1002587001587, -4990162550,
    -1002176880533, 8068490135, -1001214026963, -1001197297384,
    -1001763265784, -1001863620956, -1002080773882, -1001541757109,
    -1001609073900, -1001662041785, -1002032946187, -1001903316574,
    -1001198046393, -1001979271631
]

# Get channels from env (semicolon-separated) or use default list
env_channels = os.getenv('SMART_MONEY_CHANNELS')
if env_channels:
    SMART_MONEY_CHANNELS = [ch.strip() for ch in env_channels.split(';') if ch.strip()]
else:
    SMART_MONEY_CHANNELS = DEFAULT_CHANNELS

# Polling interval (seconds)
SMART_MONEY_POLL_INTERVAL = int(os.getenv('SMART_MONEY_POLL_INTERVAL', '60'))

# Cache TTL (seconds)
SMART_MONEY_CACHE_TTL = int(os.getenv('SMART_MONEY_CACHE_TTL', '3600'))

# Dexscreener
DEXSCREENER_BASE = 'https://api.dexscreener.com/latest/dex'
DEXSCREENER_RATE_LIMIT_DELAY = float(os.getenv('DEXSCREENER_RATE_LIMIT_DELAY', '1.0'))

# GMGN
GMGN_API_ENDPOINT = os.getenv('GMGN_API_ENDPOINT', 'https://api.gmgn.ai/v1')
GMGN_RATE_LIMIT_DELAY = float(os.getenv('GMGN_RATE_LIMIT_DELAY', '2.0'))
GMGN_WEBSOCKET_ENABLED = os.getenv('GMGN_WEBSOCKET_ENABLED', 'true').lower() == 'true'

# Optional proxy (for networks blocking GMGN)
HTTP_PROXY = os.getenv('HTTP_PROXY')
HTTPS_PROXY = os.getenv('HTTPS_PROXY')

# Data directories
DATA_DIR = Path.home() / '.hermes' / 'data' / 'smart_money'
WALLET_PROFILES_PATH = DATA_DIR / 'wallet_profiles.jsonl'
COMPOSITE_PATTERNS_PATH = DATA_DIR / 'composite_patterns.json'
TOKEN_CACHE_PATH = DATA_DIR / 'token_cache.jsonl'
INSIGHTS_OUTPUT_PATH = DATA_DIR / 'latest_insights.json'
LEADERBOARD_OUTPUT_PATH = DATA_DIR / 'leaderboard.json'
LOGS_DIR = Path.home() / '.hermes' / 'logs'
SMART_MONEY_LOG = LOGS_DIR / 'smart_money.log'

# Ensure data dir exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Smart-wallet discovery thresholds
MIN_TRADES_PER_TOKEN = 5
MIN_WIN_RATE = 0.60
MIN_REALIZED_PNL = 0  # positive only

# Pattern learning
PATTERN_UPDATE_INTERVAL_HOURS = 6

print(f"[CONFIG] Channels: {len(SMART_MONEY_CHANNELS)} configured")
print(f"[CONFIG] Data dir: {DATA_DIR}")
