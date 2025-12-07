import sys
from pathlib import Path
from dotenv import load_dotenv

# Make src importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from src.core.execution_manager import ExecutionManager  # noqa: E402
from src.core.models import Order  # noqa: E402


def main():
    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()
    execu = ExecutionManager()

    positions = []
    positions.extend([{"exchange": "Asterdex", **p} for p in aster.get_open_positions()])
    positions.extend([{"exchange": "Hyperliquid", **p} for p in hyper.get_open_positions()])

    if not positions:
        print("[Close] No open positions found on either exchange.")
        return

    for pos in positions:
        symbol = pos.get("symbol")
        side = pos.get("side", "").upper()
        qty = float(pos.get("quantity", 0))
        if qty <= 0 or not symbol:
            continue

        if pos["exchange"] == "Asterdex":
            # Close both LONG and SHORT
            book = aster.get_top_of_book(symbol)
            if side == "LONG":
                price = execu._price_with_slippage(book.get("bid", 0.0), "SELL")
                res = aster.place_order(
                    Order(symbol=symbol, side="SELL", quantity=qty, price=price, type="LIMIT")
                )
                print(f"[Close] Asterdex LONG {symbol} qty={qty} price={price} -> {res}")
            elif side == "SHORT":
                price = execu._price_with_slippage(book.get("ask", 0.0), "BUY")
                res = aster.place_order(
                    Order(symbol=symbol, side="BUY", quantity=qty, price=price, type="LIMIT")
                )
                print(f"[Close] Asterdex SHORT {symbol} qty={qty} price={price} -> {res}")
            else:
                print(f"[Close] Asterdex unsupported side: {pos}")

        elif pos["exchange"] == "Hyperliquid":
            book = hyper.get_top_of_book(symbol)
            if side == "LONG":
                price = execu._price_with_slippage(book.get("bid", 0.0), "SELL")
                res = hyper.place_order(
                    Order(symbol=symbol, side="SELL", quantity=qty, price=price, type="LIMIT")
                )
                print(f"[Close] Hyperliquid LONG {symbol} qty={qty} price={price} -> {res}")
            elif side == "SHORT":
                price = execu._price_with_slippage(book.get("ask", 0.0), "BUY")
                res = hyper.place_order(
                    Order(symbol=symbol, side="BUY", quantity=qty, price=price, type="LIMIT")
                )
                print(f"[Close] Hyperliquid SHORT {symbol} qty={qty} price={price} -> {res}")
            else:
                print(f"[Close] Hyperliquid unsupported side: {pos}")
        else:
            print(f"[Close] Unsupported exchange: {pos}")


if __name__ == "__main__":
    main()
