from abc import ABC, abstractmethod

class ExchangeInterface(ABC):
    @abstractmethod
    def get_funding_rates(self):
        """
        Fetch funding rates for all symbols.
        Returns: Dict {symbol: {'rate': float, 'price': float}}
        """
        pass

    @abstractmethod
    def get_balance(self):
        """
        Fetch account balance.
        Returns: float (USDT equivalent)
        """
        pass
