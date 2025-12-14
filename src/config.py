# Configuration
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"

# Strategy Settings
MIN_MONTHLY_RETURN = 0.02  # (break even in 1 round)
TARGET_MONTHLY_RETURN = 0.04  # Used by funding_scanner (default 4% goal)
MIN_SPREAD_PER_ROUND = 0.002 # 0.2% per 8h
MIN_VOLUME_USDT = 5.00000 # Daily Volume (increased for safer slippage)
ESTIMATED_FEE_PER_ROTATION = 0.002 # Fallback if fee data missing
ASTERDEX_TAKER_FEE = 0.0005  # 0.05% base taker
HYPERLIQUID_TAKER_FEE = 0.00045  # 0.045% base taker
SLIPPAGE_BPS = 15  # per leg slippage allowance in bps (0.015%); buffer for altcoins
DEFAULT_LEVERAGE = 2  # desired leverage per leg
MAX_BREAK_EVEN_ROUNDS = 1 # Max rounds (8h each) to wait for break-even. 1 = must profit in 1st round.

# Filter Settings
ENABLE_VOLUME_FILTER = True
ENABLE_DELIST_FILTER = True
WATCHLIST = [] # Symbols to monitor regardless of profit (e.g. ["HEMI", "ETH"])

# Execution Settings
ENABLE_TRADING = False # SAFETY: Start with False (Alert Mode)
POLL_INTERVAL = 60 # Check every 60 seconds

# Notification Settings
TELEGRAM_BOT_TOKEN = "" # User to fill
TELEGRAM_CHAT_ID = ""   # User to fill
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1446766608264593519/gDLfrmOsdGmfQLRjihkQjkWk0ySS7jkKcaytdaxOa64wZBdAEnoFXUtEfCxSu_OQHM0Q"

# Debugging
DEBUG_FILTER_LOG = False  # Set True to print why symbols are filtered out (volume, inactive, net<=0, etc.)

