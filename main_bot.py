import time
import sys
from datetime import datetime, timedelta, timezone
from src.core.interfaces import ExchangeInterface
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.notification.discord import DiscordNotifier
from src.config import POLL_INTERVAL, ENABLE_TRADING

def main():
    print("--- Starting Crypto Arbitrage Bot (Phase 3) ---")
    
    # 1. Initialize Components
    exchanges = [
        AsterdexAdapter(),
        HyperliquidAdapter()
    ]
    strategy = FundingArbitrageStrategy()
    telegram_notifier = TelegramNotifier()
    discord_notifier = DiscordNotifier()
    
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
                # Prioritize Watchlist Signals
                watchlist_signals = [s for s in signals if s.is_watchlist]
                other_signals = [s for s in signals if not s.is_watchlist]
                
                # Combine: Watchlist first, then others sorted by profit
                final_signals = watchlist_signals + other_signals
                
                if final_signals:
                    top_signal = final_signals[0]
                    
                    # Calculate countdown
                    now_ms = int(time.time() * 1000)
                    diff_ms = top_signal.next_funding_time - now_ms
                    minutes_left = max(0, int(diff_ms / 60000))
                    
                    # Calculate BKK time (UTC+7)
                    payout_dt_utc = datetime.fromtimestamp(top_signal.next_funding_time / 1000, tz=timezone.utc)
                    bkk_time = payout_dt_utc + timedelta(hours=7)
                    bkk_str = bkk_time.strftime("%H:%M")
                    
                    icon = "👀" if top_signal.is_watchlist else "🚀"
                    warning_text = f"\n{top_signal.warning}" if top_signal.warning else ""
                    
                    msg = (
                        f"{icon} **Opportunity Found: {top_signal.symbol}**{warning_text}\n"
                        f"💰 Monthly Return: {top_signal.projected_monthly_return*100:.2f}%\n"
                        f"↔️ Spread (8h): {top_signal.spread*100:.4f}%\n"
                        f"⏳ Next Payout: in {minutes_left} mins ({bkk_str} BKK)\n"
                        f"action: {top_signal.direction}\n"
                        f"(Long {top_signal.exchange_long} / Short {top_signal.exchange_short})"
                    )
                    print(msg)
                    telegram_notifier.send_alert(msg)
                    discord_notifier.send_alert(msg)
                    
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
