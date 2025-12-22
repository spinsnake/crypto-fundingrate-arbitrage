import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
LIGHTER_API_URL = "https://mainnet.zklighter.elliot.ai"

# Strategy Settings (percent scale, e.g., 2 = 2%)
LIGHTER_MARKET_STYLE = "mid"  # "major", "mid", "alt", "micro"
LIGHTER_VOLUME_PRESETS = {
    "major": 1000000,  # focus on majors only
    "mid": 250000,     # mid-cap liquidity
    "alt": 50000,      # higher risk/altcoins
    "micro": 10000,    # long tail / experimental
}
# Scan thresholds (JSON-like dict for readability)
SCAN_THRESHOLDS = {
    "min_24h_funding_pct": -2.0,  # 24h funding % of equity (net of 1-time cost)
    "min_7d_funding_pct": 1.0,  # 7d funding % of equity (net of 1-time cost)
    "min_30d_funding_pct": 2.0,  # 30d funding % of equity (net of 1-time cost)
    "min_spread_per_round_pct": 0.2,  # 0.2% per round (max interval)
    "min_volume_aster_usdt": 1000,  # Daily volume filter for Asterdex
    "min_volume_hl_usdt": 500000,  # Daily volume filter for Hyperliquid
    "min_volume_lighter_usdt": LIGHTER_VOLUME_PRESETS.get(LIGHTER_MARKET_STYLE, 50000),
    "min_price_spread_pct": 0.01,  # Minimum favorable price edge between exchanges (%)
    "max_break_even_rounds": 100,  # Max rounds (based on max interval) to break even
}

# Backward-compatible aliases
MIN_24H_FUNDING_PCT = SCAN_THRESHOLDS["min_24h_funding_pct"]
MIN_7D_FUNDING_PCT = SCAN_THRESHOLDS["min_7d_funding_pct"]
MIN_30D_FUNDING_PCT = SCAN_THRESHOLDS["min_30d_funding_pct"]
MIN_MONTHLY_RETURN = MIN_30D_FUNDING_PCT
TARGET_MONTHLY_RETURN = MIN_30D_FUNDING_PCT
MIN_SPREAD_PER_ROUND = SCAN_THRESHOLDS["min_spread_per_round_pct"]
MIN_VOLUME_ASTER_USDT = SCAN_THRESHOLDS["min_volume_aster_usdt"]
MIN_VOLUME_HL_USDT = SCAN_THRESHOLDS["min_volume_hl_usdt"]
MIN_VOLUME_LIGHTER_USDT = SCAN_THRESHOLDS["min_volume_lighter_usdt"]
MIN_PRICE_SPREAD_PCT = SCAN_THRESHOLDS["min_price_spread_pct"]
MAX_BREAK_EVEN_ROUNDS = SCAN_THRESHOLDS["max_break_even_rounds"]
ESTIMATED_FEE_PER_ROTATION = 0.2 # Fallback if fee data missing (% per rotation)
ASTERDEX_TAKER_FEE = 0.05  # 0.05% base taker
HYPERLIQUID_TAKER_FEE = 0.045  # 0.045% base taker
LIGHTER_TAKER_FEE = 0.0  # Fallback if API fee missing (percent)
SLIPPAGE_BPS = 15  # per leg slippage allowance in bps (0.015%); buffer for altcoins
DEFAULT_LEVERAGE = 2  # desired leverage per leg
SAFETY_BUFFER = 0.9  # use 90% of min equity to leave margin buffer
REBALANCE_FIXED_COST_USDC = 1.6  # Flat cost per rebalance transfer (withdraw+gas+deposit)


# Filter Settings
ENABLE_VOLUME_FILTER = True
ENABLE_DELIST_FILTER = True
ENABLE_PRICE_SPREAD_FILTER = True
WATCHLIST = ["RESOLV"] # Symbols to monitor regardless of profit (e.g. ["RESOLV", "ETH"])
SCAN_EXCHANGES = ["hyperliquid", "lighter"]  # Options: "hyperliquid", "asterdex", "lighter"

# Execution Settings
ENABLE_TRADING = True # SAFETY: Start with False (Alert Mode)
# Auto-close thresholds use integer percent scale (e.g., 20 = 20%)
AUTO_CLOSE_RET_PCT = 20  # Auto-close if portfolio return >= this percent (0 = disabled)
AUTO_CLOSE_SIDE_DD_PCT = 10  # Auto-close if any single leg drawdown <= -this percent
POLL_INTERVAL = 60 # Check every 60 seconds
DISCORD_ALERT_INTERVAL = 300  # seconds between Discord alerts (throttled); scan still runs every POLL_INTERVAL

# Notification Settings
TELEGRAM_BOT_TOKEN = "" # User to fill
TELEGRAM_CHAT_ID = ""   # User to fill
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Debugging
DEBUG_FILTER_LOG = False  # Set True to print why symbols are filtered out (volume, inactive, net<=0, etc.)
