# Configuration
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"

# Strategy Settings (percent scale, e.g., 2 = 2%)
MIN_MONTHLY_RETURN = 2.0  # (break even in 1 round)
TARGET_MONTHLY_RETURN = 4.0  # Used by funding_scanner (default 4% goal)
MIN_SPREAD_PER_ROUND = 0.2 # 0.2% per 8h
MIN_VOLUME_ASTER_USDT = 1000 # Daily Volume filter for Asterdex
MIN_VOLUME_HL_USDT = 500000    # Daily Volume filter for Hyperliquid
ESTIMATED_FEE_PER_ROTATION = 0.2 # Fallback if fee data missing
ASTERDEX_TAKER_FEE = 0.05  # 0.05% base taker
HYPERLIQUID_TAKER_FEE = 0.045  # 0.045% base taker
SLIPPAGE_BPS = 15  # per leg slippage allowance in bps (0.015%); buffer for altcoins
DEFAULT_LEVERAGE = 2  # desired leverage per leg
MAX_BREAK_EVEN_ROUNDS = 2 # Max rounds (8h each) to wait for break-even. 1 = must profit in 1st round.
MIN_PRICE_SPREAD_PCT = 0.2  # Minimum favorable price edge between exchanges (0.2%)
REBALANCE_FIXED_COST_USDC = 1.6  # Flat cost per rebalance transfer (withdraw+gas+deposit)


# Filter Settings
ENABLE_VOLUME_FILTER = True
ENABLE_DELIST_FILTER = True
ENABLE_PRICE_SPREAD_FILTER = True
WATCHLIST = ["HEMI"] # Symbols to monitor regardless of profit (e.g. ["HEMI", "ETH"])

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
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1450348767164502058/JBmAhwoHfTilBfyt-FYD2YpJJpioxJNaDV7Bdde6idS31DQwD_ee6pt9hZhYrqQVq3bZ"

# Debugging
DEBUG_FILTER_LOG = False  # Set True to print why symbols are filtered out (volume, inactive, net<=0, etc.)
