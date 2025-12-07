from abc import ABC, abstractmethod
from typing import List, Dict, Any
from .models import FundingRate, Signal, Order

class ExchangeInterface(ABC):
    @abstractmethod
    def get_name(self) -> str:
        pass

    @abstractmethod
    def get_all_funding_rates(self) -> Dict[str, FundingRate]:
        """Fetch funding rates for all supported symbols"""
        pass

    @abstractmethod
    def get_balance(self) -> float:
        """Get total account value in USDT"""
        pass

    @abstractmethod
    def place_order(self, order: Order) -> Dict:
        """Place an order on the exchange"""
        pass

    @abstractmethod
    def is_symbol_active(self, symbol: str) -> bool:
        """Check if the symbol is currently trading and not delisted"""
        pass

    def get_top_of_book(self, symbol: str) -> Dict[str, Any]:
        """Get best bid/ask for a symbol. Returns {'bid': float, 'ask': float}"""
        pass

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """
        Return a list of open positions.
        Expected keys: symbol, side ("LONG"/"SHORT"), quantity (base units)
        """
        pass

class StrategyInterface(ABC):
    @abstractmethod
    def analyze(self, market_data: Dict[str, Dict[str, FundingRate]]) -> List[Signal]:
        """
        Analyze market data and return a list of actionable signals.
        market_data format: { 'BTC': { 'Asterdex': FundingRate(...), 'Hyperliquid': FundingRate(...) } }
        """
        pass
