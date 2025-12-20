import sys
from pathlib import Path
from dotenv import load_dotenv

# Make src importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from src.adapters.lighter import LighterAdapter  # noqa: E402
from src.core.execution_manager import ExecutionManager  # noqa: E402
from datetime import datetime
import time
from src.core.models import Order  # noqa: E402

EXCHANGE_REGISTRY = {
    "asterdex": AsterdexAdapter,
    "hyperliquid": HyperliquidAdapter,
    "lighter": LighterAdapter,
}

# Set exchanges to close (keys from EXCHANGE_REGISTRY)
CLOSE_EXCHANGES = ["asterdex", "hyperliquid", "lighter"]


def _resolve_close_exchange_keys() -> list[str]:
    keys = [str(k).lower() for k in CLOSE_EXCHANGES]
    keys = [k for k in keys if k in EXCHANGE_REGISTRY]
    if not keys:
        print("[Config] CLOSE_EXCHANGES invalid/empty. Using all exchanges.")
        return list(EXCHANGE_REGISTRY.keys())
    return keys


def main():
    execu = ExecutionManager()
    exchange_keys = _resolve_close_exchange_keys()
    exchanges = [EXCHANGE_REGISTRY[key]() for key in exchange_keys]
    exchange_by_name = {ex.get_name(): ex for ex in exchanges}

    positions = []
    for ex in exchanges:
        ex_name = ex.get_name()
        positions.extend([{"exchange": ex_name, **p} for p in ex.get_open_positions()])

    if not positions:
        ex_names = ", ".join(exchange_by_name.keys())
        print(f"[Close] No open positions found on: {ex_names}.")
        return

    summary = {name: [] for name in exchange_by_name}

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
        exchange_obj = exchange_by_name.get(exchange)
        if exchange_obj:
            funding_pnl = exchange_obj.get_funding_history(symbol, start_time_ms, now_ms)
        print(f"   > Realized Funding: {funding_pnl:+.4f} USDT")

        # 3. Close the Position
        close_price = 0.0
        fee_cost = 0.0
        res = {}
        
        if not exchange_obj:
            print(f"   > Skipped: Missing adapter for {exchange}")
            continue

        book = exchange_obj.get_top_of_book(symbol)
        target_side = "SELL" if side == "LONG" else "BUY"
        book_price = book.get("bid" if target_side == "SELL" else "ask", 0.0)
        price = execu._price_with_slippage(book_price, target_side)
        if price <= 0:
            print("   > Skipped: Invalid book price")
            continue

        res = exchange_obj.place_order(
            Order(symbol=symbol, side=target_side, quantity=qty, price=price, type="LIMIT")
        )
        summary[exchange].append(res)
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

    for ex_name, ex_summary in summary.items():
        print(f"[Summary] {ex_name} close: {summarize(ex_summary)}")


if __name__ == "__main__":
    main()
