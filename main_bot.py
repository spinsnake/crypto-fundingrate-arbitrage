import time
import sys
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.notification.discord import DiscordNotifier
from src.config import POLL_INTERVAL, ENABLE_TRADING, WATCHLIST
from src.core.execution_manager import ExecutionManager
from src.utils.time_helper import TimeHelper


def main():
    print("--- Starting Crypto Arbitrage Bot (Phase 3) ---")

    aster = AsterdexAdapter()
    hl = HyperliquidAdapter()
    exchanges = [aster, hl]
    
    strategy = FundingArbitrageStrategy()
    execu = ExecutionManager()
    telegram_notifier = TelegramNotifier()
    discord_notifier = DiscordNotifier()

    print(f"Loaded {len(exchanges)} exchanges: {[e.get_name() for e in exchanges]}")
    print(f"Mode: {'AUTO TRADING' if ENABLE_TRADING else 'ALERT ONLY'}")

    while True:
        try:
            time_str = TimeHelper.now_bkk_str()

            print(f"\n[Scanning {time_str}] Fetching market data...")
            market_data = {}  # { 'BTC': { 'Asterdex': Rate, 'Hyperliquid': Rate } }

            for exchange in exchanges:
                name = exchange.get_name()
                rates = exchange.get_all_funding_rates()
                print(f"  -> {name}: Got {len(rates)} rates")

                for symbol, rate_obj in rates.items():
                    market_data.setdefault(symbol, {})[name] = rate_obj

            signals = strategy.analyze(market_data)
            print(f"[Analysis] Found {len(signals)} opportunities > Threshold")

            if signals:
                watchlist_signals = [s for s in signals if s.is_watchlist]
                other_signals = [s for s in signals if not s.is_watchlist]
                final_signals = watchlist_signals + other_signals

                if final_signals:
                    top_signal = final_signals[0]
                    
                    # Asterdex payout
                    aster_mins_left = TimeHelper.ms_to_mins_remaining(top_signal.next_aster_payout)
                    aster_bkk = TimeHelper.ms_to_bkk_str(top_signal.next_aster_payout)
                    
                    # HL payout
                    hl_mins_left = TimeHelper.ms_to_mins_remaining(top_signal.next_hl_payout)
                    hl_bkk = TimeHelper.ms_to_bkk_str(top_signal.next_hl_payout)

                    icon = "🚀" if top_signal.is_watchlist else "✨"
                    warning_text = f"\n{top_signal.warning}" if top_signal.warning else ""

                    hold_hours = top_signal.break_even_rounds * 8

                    # Determine Pay/Recv
                    # HL Rate is already normalized to 8h in strategy/model
                    aster_action = "RECV" if top_signal.aster_rate > 0 else "PAY" # Assuming Short Aster
                    hl_action = "PAY" if top_signal.hl_rate > 0 else "RECV"       # Assuming Long HL
                    
                    if top_signal.direction == "LONG_ASTER_SHORT_HL":
                         aster_action = "PAY" if top_signal.aster_rate > 0 else "RECV"
                         hl_action = "RECV" if top_signal.hl_rate > 0 else "PAY"

                    msg = (
                        f"{icon} **Opportunity Found: {top_signal.symbol}**{warning_text}\n"
                        f"💰 Monthly Return (net): {top_signal.projected_monthly_return*100:.2f}%\n"
                        f"↔️ Spread (8h, net of fees): {top_signal.spread_net*100:.4f}%\n"
                        f"🛡️ Round Return (after fees, 1 round): {top_signal.round_return_net*100:.4f}%\n"
                        f"📊 Rates (8h):\n"
                        f"  • Asterdex: {top_signal.aster_rate*100:.4f}% ({aster_action})\n"
                        f"  • Hyperliq: {top_signal.hl_rate*100:.4f}% ({hl_action})\n"
                        f"⏳ Min Hold: {top_signal.break_even_rounds} Rounds (~{hold_hours} Hours) to Break Even\n"
                        f"⏱️ Asterdex Payout: in {aster_mins_left} mins ({aster_bkk} BKK)\n"
                        f"⏱️ HL Payout: in {hl_mins_left} mins ({hl_bkk} BKK)\n"
                        f"action: {top_signal.direction}\n"
                        f"(Long {top_signal.exchange_long} / Short {top_signal.exchange_short})"
                    )
                    print(msg)
                    telegram_notifier.send_alert(msg)
                    discord_notifier.send_alert(msg)

                # --- NEW: Live PnL for Watchlist ---
                for symbol in WATCHLIST:
                    trade = execu.get_last_open_trade(symbol)
                    if trade:
                        try:
                            # 1. Realized Funding
                            start_time_str = trade['Timestamp']
                            dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
                            start_time = int(dt.timestamp() * 1000)
                            now_ms = int(time.time() * 1000)
                            
                            # Determine exchanges from log
                            ex_long_name = trade['Long_Exchange']
                            ex_short_name = trade['Short_Exchange']
                            
                            # Get Adapters (simple lookup if names match)
                            fund_aster = aster.get_funding_history(symbol, start_time, now_ms)
                            fund_hl = hl.get_funding_history(symbol, start_time, now_ms)
                            net_funding = fund_aster + fund_hl
                            
                            
                            # Icon Logic
                            net_icon = "💰" if net_funding >= 0 else "💸"
                            aster_icon = "🟢" if fund_aster >= 0 else "🔴"
                            hl_icon = "🟢" if fund_hl >= 0 else "🔴"

                            print(f"\n[{symbol} LIVE STATUS]")
                            print(f"   Realized Funding: {net_icon} {net_funding:+.4f} USDT")
                            print(f"      Asterdex:    {aster_icon} {fund_aster:+.4f} USDT")
                            print(f"      Hyperliquid: {hl_icon} {fund_hl:+.4f} USDT")
                            print(f"   (Open since {start_time_str})\n")
                        except Exception as e:
                            print(f"[Live PnL] Error for {symbol}: {e}")

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
