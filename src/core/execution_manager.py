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

        # Log the trade
        self._log_trade(symbol, "OPEN", exchange_long.get_name(), long_price, qty_long, res_long, exchange_short.get_name(), short_price, qty_short, res_short)

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
        
        # Calculate Realized Funding
        try:
            start_time = self._find_trade_start_time(symbol)
            if start_time:
                now_ms = int(time.time() * 1000)
                # Funding history
                aster_fund = exchange_long.get_funding_history(symbol, start_time, now_ms)
                # Note: exchange_long might be HL if direction was swapped, but here variable is just 'exchange_long' object
                # We need to call it on both objects passed.
                
                # Check which is which is tricky if we don't know names here, but objects have get_name()
                # Actually, simply call on both objects.
                fund_1 = exchange_long.get_funding_history(symbol, start_time, now_ms)
                fund_2 = exchange_short.get_funding_history(symbol, start_time, now_ms)
                
                net_funding = fund_1 + fund_2
                
                print(f"\n💰 [Funding Realized] {symbol}")
                print(f"   {exchange_long.get_name()}: {fund_1:+.4f} USDT")
                print(f"   {exchange_short.get_name()}: {fund_2:+.4f} USDT")
                print(f"   NET TOTAL: {net_funding:+.4f} USDT\n")
            else:
                 print(f"[Funding] Could not find OPEN time in logs for {symbol}")
        except Exception as e:
            print(f"[Funding] Error calculating realized funding: {e}")
        
        # Log the close trade
        self._log_trade(symbol, "CLOSE", exchange_long.get_name(), sell_price, qty_long, res_close_long, exchange_short.get_name(), buy_price, qty_short, res_close_short)

        return {"close_long": res_close_long, "close_short": res_close_short}

    def _log_trade(self, symbol, action, ex_long, px_long, qty_long, res_long, ex_short, px_short, qty_short, res_short):
        import csv
        import time
        from datetime import datetime
        
        file_exists = False
        try:
            with open("trade_log.csv", "r") as f:
                file_exists = True
        except FileNotFoundError:
            pass
            
        with open("trade_log.csv", "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "Timestamp", "Symbol", "Action", 
                    "Long_Exchange", "Long_Price", "Long_Qty", "Long_Status",
                    "Short_Exchange", "Short_Price", "Short_Qty", "Short_Status",
                    "Est_Total_Notional", "Est_Fee_Cost"
                ])
                
            # Calculate rough estimates
            notional = (px_long * qty_long) + (px_short * qty_short)
            # Rough fee estimate (0.1% total)
            fee = notional * 0.001 
            
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol, action,
                ex_long, f"{px_long:.6f}", f"{qty_long:.6f}", res_long.get("status", "unknown"),
                ex_short, f"{px_short:.6f}", f"{qty_short:.6f}", res_short.get("status", "unknown"),
                f"{notional:.2f}", f"{fee:.4f}"
            ])
            print(f"[Log] Recorded {action} trade for {symbol} to trade_log.csv")

    def _find_trade_start_time(self, symbol: str) -> int:
        import csv
        from datetime import datetime
        try:
            with open("trade_log.csv", "r") as f:
                # Read all lines to handle reversing
                lines = f.readlines()
                if not lines:
                     return 0
                
                # Parse header
                header = lines[0].strip().split(',')
                
                # Iterate backwards
                for line in reversed(lines[1:]):
                    row = dict(zip(header, line.strip().split(',')))
                    if row.get('Symbol') == symbol and row.get('Action') == 'OPEN':
                        # Timestamp format: 2024-12-14 16:35:00
                        ts_str = row.get('Timestamp')
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        return int(dt.timestamp() * 1000)
        except Exception as e:
            print(f"[Funding] Error searching logs: {e}")
        return 0

    def get_last_open_trade(self, symbol: str) -> dict:
        """
        Check if the last logged action for this symbol is OPEN.
        Returns dict with trade details if open, else None.
        """
        import csv
        from datetime import datetime
        try:
            with open("trade_log.csv", "r") as f:
                lines = f.readlines()
                if not lines:
                     return None
                
                header = lines[0].strip().split(',')
                
                # Search backwards for the symbol
                for line in reversed(lines[1:]):
                    row = dict(zip(header, line.strip().split(',')))
                    if row.get('Symbol') == symbol:
                        # Found the last action for this symbol
                        if row.get('Action') == 'OPEN':
                            return row
                        else:
                            # Last action was CLOSE (or other), so no open position
                            return None
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"[Exec] Error reading log: {e}")
            return None
        return None
