from dataclasses import dataclass
from typing import Optional

@dataclass
class FundingRate:
    symbol: str
    rate: float
    mark_price: float
    source: str
    timestamp: int
    volume_24h: float = 0.0
    next_funding_time: int = 0
    is_active: bool = True
    taker_fee: float = 0.0
    funding_interval_hours: int = 8

@dataclass
class Signal:
    symbol: str
    direction: str  # "LONG_A_SHORT_B" or "LONG_B_SHORT_A"
    exchange_long: str
    exchange_short: str
    spread: float  # raw spread per 8h (no fee)
    projected_monthly_return: float
    timestamp: int
    next_funding_time: int
    spread_net: float = 0.0  # net per 8h after fees (one round)
    round_return_net: float = 0.0  # alias for net per round after fees
    is_watchlist: bool = False
    warning: str = ""
    break_even_rounds: int = 0
    exchange_a: str = ""
    exchange_b: str = ""
    rate_a: float = 0.0
    rate_b: float = 0.0
    next_payout_a: int = 0
    next_payout_b: int = 0
    price_a: float = 0.0
    price_b: float = 0.0
    next_aster_payout: int = 0  # Asterdex settlement time (every 8h)
    next_hl_payout: int = 0  # Hyperliquid settlement time (every 1h)
    aster_rate: float = 0.0
    hl_rate: float = 0.0
    price_spread_pct: float = 0.0  # favorable price edge relative to mid
    price_diff: float = 0.0  # HL mark - Aster mark
    aster_price: float = 0.0
    hl_price: float = 0.0

@dataclass
class Order:
    symbol: str
    side: str # "BUY" or "SELL"
    quantity: float
    price: Optional[float] = None
    type: str = "MARKET"
    leverage: float = 1.0
    reduce_only: bool = False
