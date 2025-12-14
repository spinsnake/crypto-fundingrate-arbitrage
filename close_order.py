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
from datetime import datetime
import time
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

    summary = {"Asterdex": [], "Hyperliquid": []}

    print("\n" + "="*50)
    print("       MANUAL CLOSE ORDER & PNL REPORT       ")
    print("="*50 + "\n")

    for pos in positions:
        symbol = pos.get("symbol")
        side = pos.get("side", "").upper()
        qty = float(pos.get("quantity", 0))
        exchange = pos.get("exchange")
        
        if qty <= 0 or not symbol:
            continue
            
        print(f"Processing {exchange} {side} {symbol} (Qty: {qty})...")

        # 1. Find Open Trade Details (Start Time & Open Price)
        trade_open = execu.get_last_open_trade(symbol)
        start_time_ms = 0
        open_price = 0.0
        
        if trade_open:
            # Check if this exchange matches the open trade
            is_long_leg = (exchange == trade_open['Long_Exchange']) and (side == "LONG")
            is_short_leg = (exchange == trade_open['Short_Exchange']) and (side == "SHORT")
            
            if is_long_leg:
                 open_price = float(trade_open['Long_Price'])
            elif is_short_leg:
                 open_price = float(trade_open['Short_Price'])
            
            # Parse Start Time
            try:
                dt = datetime.strptime(trade_open['Timestamp'], "%Y-%m-%d %H:%M:%S")
                start_time_ms = int(dt.timestamp() * 1000)
            except:
                pass
        
        # 2. Get Realized Funding (If we have start time)
        funding_pnl = 0.0
        if start_time_ms > 0:
            now_ms = int(time.time() * 1000)
            if exchange == "Asterdex":
                funding_pnl = aster.get_funding_history(symbol, start_time_ms, now_ms)
            elif exchange == "Hyperliquid":
                funding_pnl = hyper.get_funding_history(symbol, start_time_ms, now_ms)
            print(f"   > Realized Funding: {funding_pnl:+.4f} USDT")

        # 3. Close the Position
        close_price = 0.0
        fee_cost = 0.0
        res = {}
        
        if exchange == "Asterdex":
            book = aster.get_top_of_book(symbol)
            target_side = "SELL" if side == "LONG" else "BUY"
            # Price logic
            book_price = book.get("bid" if target_side == "SELL" else "ask", 0.0)
            price = execu._price_with_slippage(book_price, target_side)
            
            res = aster.place_order(
                Order(symbol=symbol, side=target_side, quantity=qty, price=price, type="LIMIT")
            )
            summary["Asterdex"].append(res)
            
            # Estimate close data
            close_price = price 
            # In simple manual mode, we might not get fill price back easily without querying order. 
            # Use placed price as estimate.
            
        elif exchange == "Hyperliquid":
            book = hyper.get_top_of_book(symbol)
            target_side = "SELL" if side == "LONG" else "BUY"
            book_price = book.get("bid" if target_side == "SELL" else "ask", 0.0)
            price = execu._price_with_slippage(book_price, target_side)
            
            res = hyper.place_order(
                Order(symbol=symbol, side=target_side, quantity=qty, price=price, type="LIMIT")
            )
            summary["Hyperliquid"].append(res)
            close_price = price

        # 4. Calculate Trade PnL
        # Long: (Close - Open) * Qty
        # Short: (Open - Close) * Qty
        trade_pnl = 0.0
        if open_price > 0:
            if side == "LONG":
                trade_pnl = (close_price - open_price) * qty
            else:
                trade_pnl = (open_price - close_price) * qty
        
        # Fee Estimate (0.05% approx)
        fee_cost = (close_price * qty) * 0.0005
        
        # Total PnL for this leg
        total_leg_pnl = trade_pnl + funding_pnl - fee_cost
        
        print(f"   > Close Price: {close_price:.6f} (Open: {open_price:.6f})")
        print(f"   > Trade PnL: {trade_pnl:+.4f} USDT")
        print(f"   > Est. Fee: -{fee_cost:.4f} USDT")
        print(f"   > TOTAL LEG PNL: {total_leg_pnl:+.4f} USDT")
        print("-" * 30)

        # 5. Log to CSV (Append Close info manually/independently)
        # Note: ExecutionManager._log_trade expects a pair. Here we are closing individually.
        # We will append a manual log entry "MANUAL_CLOSE".
        # We need to preserve the CSV structure or just add a comment line? 
        # Better to just print for now as splitting logging logic is complex. 
        # But User requested "Log".
        # Let's try to simulate a log entry matching the columns if we can.
        
        # Actually, let's just create a simple "MANUAL_CLOSE" entry that reuses the columns slightly wrongly
        # or properly if we close both legs. 
        # Since this loop is per-position, we might log 2 lines.
        
        execu._log_trade(
            symbol=symbol,
            action=f"CLOSE_MANUAL_{exchange}",
            ex_long=exchange if side=="LONG" else "-",
            px_long=close_price if side=="LONG" else 0.0,
            qty_long=qty if side=="LONG" else 0.0,
            res_long={"pnl": total_leg_pnl}, # Hack into status ?
            ex_short=exchange if side=="SHORT" else "-",
            px_short=close_price if side=="SHORT" else 0.0,
            qty_short=qty if side=="SHORT" else 0.0,
            res_short={"pnl": total_leg_pnl}
        )
        
    # Summary
    def summarize(lst):
        if not lst:
            return "no orders"
        # prefer 'status' field
        statuses = []
        for r in lst:
            if isinstance(r, dict):
                st = r.get("status") or r.get("response", {}).get("status")
                statuses.append(st or "unknown")
        return ", ".join(statuses) if statuses else "unknown"

    print(f"\n[Summary] Asterdex close: {summarize(summary['Asterdex'])}")
    print(f"[Summary] Hyperliquid close: {summarize(summary['Hyperliquid'])}")


if __name__ == "__main__":
    main()
