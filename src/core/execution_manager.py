from typing import Dict
from .models import Order
from ..config import SLIPPAGE_BPS, DEFAULT_LEVERAGE


class ExecutionManager:
    """Simple helper to open/close spread legs with limit price buffers."""

    def __init__(self, slippage_bps: int = SLIPPAGE_BPS, leverage: float = DEFAULT_LEVERAGE):
        self.slippage_factor = slippage_bps / 10000
        self.leverage = leverage

    def _price_with_slippage(self, ref_price: float, side: str) -> float:
        """Apply slippage buffer to ref price."""
        if ref_price <= 0:
            return 0.0
        delta = ref_price * self.slippage_factor
        if side.upper() == "BUY":
            return ref_price + delta
        return ref_price - delta

    def open_spread(
        self,
        symbol: str,
        notional: float,
        exchange_long,
        exchange_short,
    ) -> Dict:
        """
        Open long on exchange_long and short on exchange_short using limit prices with slippage buffer.
        """
        book_long = exchange_long.get_top_of_book(symbol)
        book_short = exchange_short.get_top_of_book(symbol)

        long_price = self._price_with_slippage(book_long.get("ask", 0.0), "BUY")
        short_price = self._price_with_slippage(book_short.get("bid", 0.0), "SELL")

        if long_price <= 0 or short_price <= 0:
            return {"status": "error", "reason": "Invalid book prices"}

        qty_long = notional / long_price
        qty_short = notional / short_price

        res_long = exchange_long.place_order(
            Order(symbol=symbol, side="BUY", quantity=qty_long, price=long_price, type="LIMIT", leverage=self.leverage)
        )
        res_short = exchange_short.place_order(
            Order(symbol=symbol, side="SELL", quantity=qty_short, price=short_price, type="LIMIT", leverage=self.leverage)
        )

        return {"long": res_long, "short": res_short}

    def close_spread(
        self,
        symbol: str,
        qty_long: float,
        qty_short: float,
        exchange_long,
        exchange_short,
    ) -> Dict:
        """Close existing spread positions using limit prices with slippage buffer."""
        book_long = exchange_long.get_top_of_book(symbol)
        book_short = exchange_short.get_top_of_book(symbol)

        # Closing long -> sell at bid; closing short -> buy at ask
        sell_price = self._price_with_slippage(book_long.get("bid", 0.0), "SELL")
        buy_price = self._price_with_slippage(book_short.get("ask", 0.0), "BUY")

        if sell_price <= 0 or buy_price <= 0:
            return {"status": "error", "reason": "Invalid book prices"}

        res_close_long = exchange_long.place_order(
            Order(symbol=symbol, side="SELL", quantity=qty_long, price=sell_price, type="LIMIT", leverage=self.leverage)
        )
        res_close_short = exchange_short.place_order(
            Order(symbol=symbol, side="BUY", quantity=qty_short, price=buy_price, type="LIMIT", leverage=self.leverage)
        )

        return {"close_long": res_close_long, "close_short": res_close_short}
