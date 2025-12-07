import time
import sys
from datetime import datetime, timedelta, timezone
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.notification.discord import DiscordNotifier
from src.config import POLL_INTERVAL, ENABLE_TRADING


def main():
    print("--- Starting Crypto Arbitrage Bot (Phase 3) ---")

    exchanges = [
        AsterdexAdapter(),
        HyperliquidAdapter(),
    ]
    strategy = FundingArbitrageStrategy()
    telegram_notifier = TelegramNotifier()
    discord_notifier = DiscordNotifier()

    print(f"Loaded {len(exchanges)} exchanges: {[e.get_name() for e in exchanges]}")
    print(f"Mode: {'AUTO TRADING' if ENABLE_TRADING else 'ALERT ONLY'}")

    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_bkk = now_utc + timedelta(hours=7)
            time_str = now_bkk.strftime("%H:%M:%S")

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

                    now_ms = int(time.time() * 1000)
                    diff_ms = top_signal.next_funding_time - now_ms
                    minutes_left = max(0, int(diff_ms / 60000))

                    payout_dt_utc = datetime.fromtimestamp(
                        top_signal.next_funding_time / 1000, tz=timezone.utc
                    )
                    bkk_time = payout_dt_utc + timedelta(hours=7)
                    bkk_str = bkk_time.strftime("%H:%M")

                    icon = "🚀" if top_signal.is_watchlist else "✨"
                    warning_text = f"\n{top_signal.warning}" if top_signal.warning else ""

                    hold_hours = top_signal.break_even_rounds * 8

                    msg = (
                        f"{icon} **Opportunity Found: {top_signal.symbol}**{warning_text}\n"
                        f"💰 Monthly Return (net): {top_signal.projected_monthly_return*100:.2f}%\n"
                        f"↔️ Spread (8h, net of fees): {top_signal.spread_net*100:.4f}%\n"
                        f"🛡️ Round Return (after fees, 1 round): {top_signal.round_return_net*100:.4f}%\n"
                        f"⏳ Min Hold: {top_signal.break_even_rounds} Rounds (~{hold_hours} Hours) to Break Even\n"
                        f"⏱️ Next Payout: in {minutes_left} mins ({bkk_str} BKK)\n"
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
