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

@dataclass
class Signal:
    symbol: str
    direction: str  # "LONG_A_SHORT_B" or "LONG_B_SHORT_A"
    exchange_long: str
    exchange_short: str
    spread: float
    projected_monthly_return: float
    timestamp: int
    next_funding_time: int
    is_watchlist: bool = False
    warning: str = ""
    break_even_rounds: int = 0

@dataclass
class Order:
    symbol: str
    side: str # "BUY" or "SELL"
    quantity: float
    price: Optional[float] = None
    type: str = "MARKET"
