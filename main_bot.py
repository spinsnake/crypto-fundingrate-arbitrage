import time
import sys
from src.core.interfaces import ExchangeInterface
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.config import POLL_INTERVAL, ENABLE_TRADING

def main():
    print("--- Starting Crypto Arbitrage Bot (Phase 3) ---")
    
    # 1. Initialize Components
    exchanges = [
        AsterdexAdapter(),
        HyperliquidAdapter()
    ]
    strategy = FundingArbitrageStrategy()
    notifier = TelegramNotifier()
    
    print(f"Loaded {len(exchanges)} exchanges: {[e.get_name() for e in exchanges]}")
    print(f"Mode: {'AUTO TRADING' if ENABLE_TRADING else 'ALERT ONLY'}")
    
    # 2. Main Loop
    while True:
        try:
            print("\n[Scanning] Fetching market data...")
            market_data = {} # { 'BTC': { 'Asterdex': Rate, 'Hyperliquid': Rate } }
            
            # Fetch from all exchanges
            for exchange in exchanges:
                name = exchange.get_name()
                rates = exchange.get_all_funding_rates()
                print(f"  -> {name}: Got {len(rates)} rates")
                
                for symbol, rate_obj in rates.items():
                    if symbol not in market_data:
                        market_data[symbol] = {}
                    market_data[symbol][name] = rate_obj
            
            # Analyze
            signals = strategy.analyze(market_data)
            print(f"[Analysis] Found {len(signals)} opportunities > Threshold")
            
            # Act
            if signals:
                top_signal = signals[0]
                msg = (
                    f"🚀 **Opportunity Found: {top_signal.symbol}**\n"
                    f"💰 Monthly Return: {top_signal.projected_monthly_return*100:.2f}%\n"
                    f"↔️ Spread (8h): {top_signal.spread*100:.4f}%\n"
                    f"action: {top_signal.direction}\n"
                    f"(Long {top_signal.exchange_long} / Short {top_signal.exchange_short})"
                )
                print(msg)
                notifier.send_alert(msg)
                
                if ENABLE_TRADING:
                    print("[Execution] Auto-trading is enabled but not implemented yet.")
                    # execution_manager.execute(top_signal)
            
            print(f"[Sleep] Waiting {POLL_INTERVAL}s...")
            time.sleep(POLL_INTERVAL)
            
        except KeyboardInterrupt:
            print("\nStopping bot...")
            sys.exit(0)
        except Exception as e:
            print(f"[Error] Main loop crashed: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
