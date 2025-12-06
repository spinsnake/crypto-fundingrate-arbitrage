# Configuration
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"

# Strategy Settings
MIN_MONTHLY_RETURN = 0.04  # 4%
MIN_SPREAD_PER_ROUND = 0.0005 # 0.05% per 8h
MIN_VOLUME_USDT = 1000000 # 1M Daily Volume
ESTIMATED_FEE_PER_ROTATION = 0.002 # 0.2% (Taker 0.05% x 4 legs)

# Execution Settings
ENABLE_TRADING = False # SAFETY: Start with False (Alert Mode)
POLL_INTERVAL = 60 # Check every 60 seconds

# Notification Settings
TELEGRAM_BOT_TOKEN = "" # User to fill
TELEGRAM_CHAT_ID = ""   # User to fill
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1446766608264593519/gDLfrmOsdGmfQLRjihkQjkWk0ySS7jkKcaytdaxOa64wZBdAEnoFXUtEfCxSu_OQHM0Q"

