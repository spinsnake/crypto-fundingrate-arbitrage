import time
import sys
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.notification.discord import DiscordNotifier
from src.config import (
    POLL_INTERVAL,
    ENABLE_TRADING,
    WATCHLIST,
    AUTO_CLOSE_RET_PCT,
    AUTO_CLOSE_SIDE_DD_PCT,
    REBALANCE_FIXED_COST_USDC,
    DISCORD_ALERT_INTERVAL,
)
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
    last_discord_alert_ts = 0  # epoch seconds

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
                live_sections = {}

                # --- Live PnL for Watchlist (also used for alerts) ---
                hl_positions = {p["symbol"]: p for p in hl.get_open_positions()}
                aster_positions = {p["symbol"]: p for p in aster.get_open_positions()}
                for symbol in WATCHLIST:
                    trade = execu.get_last_open_trade(symbol)
                    if not trade:
                        continue
                    try:
                        # 1) Realized funding
                        start_time_str = trade["Timestamp"]
                        start_time = TimeHelper.str_to_ms(start_time_str)
                        now_ms = int(time.time() * 1000)

                        ex_long_name = trade["Long_Exchange"]
                        ex_short_name = trade["Short_Exchange"]

                        fund_aster = aster.get_funding_history(symbol, start_time, now_ms)
                        fund_hl = hl.get_funding_history(symbol, start_time, now_ms)
                        net_funding = fund_aster + fund_hl

                        # 2) Fees (actual if possible)
                        fee_aster = 0.0
                        fee_hl = 0.0
                        fee_notes = []
                        if ex_long_name == "Asterdex" or ex_short_name == "Asterdex":
                            fee_aster = aster.get_trade_fees(symbol, start_time, now_ms)
                            if fee_aster:
                                fee_notes.append(f"Asterdex fees: {fee_aster:.4f}")
                        if ex_long_name == "Hyperliquid" or ex_short_name == "Hyperliquid":
                            fee_hl = hl.get_trade_fees(symbol, start_time, now_ms)
                            if fee_hl:
                                fee_notes.append(f"Hyperliquid fees: {fee_hl:.4f}")

                        open_fee_logged = float(trade.get("Est_Fee_Cost", 0) or 0)  # legacy estimate from log
                        # fallback estimate (open + close both legs) if no actual fee found
                        from src.config import ASTERDEX_TAKER_FEE, HYPERLIQUID_TAKER_FEE
                        open_notional = float(trade.get("Est_Total_Notional", 0) or 0)
                        per_round_fee_rate = (ASTERDEX_TAKER_FEE + HYPERLIQUID_TAKER_FEE) / 100
                        est_open_fee = open_notional * per_round_fee_rate

                        total_fees_paid = fee_aster + fee_hl
                        if total_fees_paid == 0:
                            total_fees_paid = est_open_fee  # nothing recorded yet, use open est.
                        # Estimate close fee = same as open (paid or est) per request
                        close_fee_est = total_fees_paid if total_fees_paid > 0 else est_open_fee
                        total_fees = total_fees_paid + close_fee_est  # include estimated close
                        total_costs = total_fees + REBALANCE_FIXED_COST_USDC  # add fixed rebalance transfer cost

                        # 3) Price PnL (unrealized)
                        price_pnl = 0.0
                        used_api = False
                        pnl_breakdown = ""
                        leg_ret_info = ""
                        drawdown_hit = False
                        sym_data = market_data.get(symbol, {})
                        rate_long = sym_data.get(ex_long_name)
                        rate_short = sym_data.get(ex_short_name)

                        curr_px_long = 0.0
                        curr_px_short = 0.0
                        if rate_long and rate_short:
                            curr_px_long = rate_long.mark_price
                            curr_px_short = rate_short.mark_price

                            entry_px_long = float(trade["Long_Price"])
                            qty_long = float(trade["Long_Qty"])
                            entry_px_short = float(trade["Short_Price"])
                            qty_short = float(trade["Short_Qty"])

                            hl_pos = hl_positions.get(symbol)
                            ast_pos = aster_positions.get(symbol)

                            # Prefer VWAP fills over log if available
                            fills_aster = {}
                            fills_hl = {}
                            try:
                                fills_aster = aster.get_fill_vwap(symbol, start_time, now_ms)
                            except Exception:
                                fills_aster = {}
                            try:
                                fills_hl = hl.get_fill_vwap(symbol, start_time, now_ms)
                            except Exception:
                                fills_hl = {}

                            # Override with live Asterdex positions if present
                            if ast_pos:
                                if ex_long_name == "Asterdex":
                                    if fills_aster.get("buy_vwap"):
                                        entry_px_long = float(fills_aster["buy_vwap"])
                                    else:
                                        entry_px_long = float(ast_pos.get("entry_price") or entry_px_long)
                                    qty_long = float(ast_pos.get("quantity") or qty_long)
                                    if ast_pos.get("mark_price"):
                                        curr_px_long = float(ast_pos["mark_price"])
                                if ex_short_name == "Asterdex":
                                    if fills_aster.get("sell_vwap"):
                                        entry_px_short = float(fills_aster["sell_vwap"])
                                    else:
                                        entry_px_short = float(ast_pos.get("entry_price") or entry_px_short)
                                    qty_short = float(ast_pos.get("quantity") or qty_short)
                                    if ast_pos.get("mark_price"):
                                        curr_px_short = float(ast_pos["mark_price"])

                            if hl_pos:
                                if ex_long_name == "Hyperliquid":
                                    if fills_hl.get("buy_vwap"):
                                        entry_px_long = float(fills_hl["buy_vwap"])
                                    else:
                                        entry_px_long = float(hl_pos.get("entry_price") or entry_px_long)
                                    qty_long = float(hl_pos.get("quantity") or qty_long)
                                    if hl_pos.get("mark_price"):
                                        curr_px_long = float(hl_pos["mark_price"])
                                if ex_short_name == "Hyperliquid":
                                    if fills_hl.get("sell_vwap"):
                                        entry_px_short = float(fills_hl["sell_vwap"])
                                    else:
                                        entry_px_short = float(hl_pos.get("entry_price") or entry_px_short)
                                    qty_short = float(hl_pos.get("quantity") or qty_short)
                                    if hl_pos.get("mark_price"):
                                        curr_px_short = float(hl_pos["mark_price"])

                            # Prefer API unrealized PnL when available
                            price_pnl_api = 0.0
                            used_api = False
                            if hl_pos and hl_pos.get("unrealized_pnl") is not None:
                                price_pnl_api += float(hl_pos.get("unrealized_pnl", 0.0))
                                used_api = True
                            if ast_pos and ast_pos.get("unrealized_pnl") is not None:
                                price_pnl_api += float(ast_pos.get("unrealized_pnl", 0.0))
                                used_api = True

                            if used_api:
                                price_pnl = price_pnl_api
                            else:
                                pnl_long = (curr_px_long - entry_px_long) * qty_long
                                pnl_short = (entry_px_short - curr_px_short) * qty_short
                                price_pnl = pnl_long + pnl_short

                            pnl_breakdown = (
                                f"      Long ({ex_long_name}): {(curr_px_long - entry_px_long)*qty_long:+.4f} "
                                f"(Px: {entry_px_long:.4f}->{curr_px_long:.4f})\n"
                                f"      Short ({ex_short_name}): {(entry_px_short - curr_px_short)*qty_short:+.4f} "
                                f"(Px: {entry_px_short:.4f}->{curr_px_short:.4f})"
                            )

                            long_ret_pct = None
                            short_ret_pct = None
                            if entry_px_long > 0 and qty_long > 0 and curr_px_long > 0:
                                long_ret_pct = (curr_px_long - entry_px_long) / entry_px_long
                            if entry_px_short > 0 and qty_short > 0 and curr_px_short > 0:
                                short_ret_pct = (entry_px_short - curr_px_short) / entry_px_short
                            if long_ret_pct is not None and short_ret_pct is not None:
                                long_ret_pct *= 100
                                short_ret_pct *= 100
                                leg_ret_info = (
                                    f"   [LEG ] Long {long_ret_pct:+.2f}% | Short {short_ret_pct:+.2f}%"
                                )
                                worst_leg = min(long_ret_pct, short_ret_pct)
                                drawdown_hit = (
                                    ENABLE_TRADING
                                    and AUTO_CLOSE_SIDE_DD_PCT > 0
                                    and worst_leg <= -AUTO_CLOSE_SIDE_DD_PCT
                                )
                        else:
                            pnl_breakdown = "      (Waiting for market data...)"

                        # 4) Est. close PnL with slippage (book-based)
                        price_pnl_slip = price_pnl
                        close_detail = ""
                        try:
                            ex_map = {"Asterdex": aster, "Hyperliquid": hl}
                            ex_long_obj = ex_map.get(ex_long_name)
                            ex_short_obj = ex_map.get(ex_short_name)
                            if ex_long_obj and ex_short_obj:
                                book_long = ex_long_obj.get_top_of_book(symbol)
                                book_short = ex_short_obj.get_top_of_book(symbol)
                                close_px_long = execu._price_with_slippage(book_long.get("bid", 0.0), "SELL")
                                close_px_short = execu._price_with_slippage(book_short.get("ask", 0.0), "BUY")
                                if close_px_long > 0 and close_px_short > 0:
                                    pnl_close_long = (close_px_long - entry_px_long) * qty_long
                                    pnl_close_short = (entry_px_short - close_px_short) * qty_short
                                    price_pnl_slip = pnl_close_long + pnl_close_short
                                    close_detail = (
                                        f"      Est close Long @ {close_px_long:.6f} -> {pnl_close_long:+.4f}\n"
                                        f"      Est close Short @ {close_px_short:.6f} -> {pnl_close_short:+.4f}"
                                    )
                        except Exception as e:
                            close_detail = f"      (Close est error: {e})"

                        # 5) Net PnL (with slippage-based close est)
                        net_pnl = net_funding + price_pnl_slip - total_costs

                        pnl_source = "API" if used_api else "calc"

                        # 6) Equity / Return %
                        bal_aster = aster.get_balance()
                        bal_hl = hl.get_balance()
                        total_equity = (bal_aster or 0) + (bal_hl or 0)
                        equity_source = "API"
                        if total_equity <= 0:
                            total_equity = open_notional or 1.0  # avoid zero-div
                            equity_source = "EST"
                        ret_pct = (net_pnl / total_equity) * 100 if total_equity else 0.0

                        # 7) Auto-close based on return %
                        auto_close_hit = ENABLE_TRADING and AUTO_CLOSE_RET_PCT > 0 and ret_pct >= AUTO_CLOSE_RET_PCT

                        print(f"\n[= LIVE =] {symbol}")
                        print(f"   [FUND] {net_funding:+.4f} USDT "
                              f"(Asterdex {fund_aster:+.4f}, Hyperliquid {fund_hl:+.4f})")
                        print(f"   [PNL ] {price_pnl:+.4f} USDT ({pnl_source})")
                        print(pnl_breakdown)
                        print(f"   [SLIP] {price_pnl_slip:+.4f} USDT (est close w/ slippage)")
                        if close_detail:
                            print(close_detail)
                        # Fee display: paid + estimated close
                        fee_display_notes = []
                        if fee_notes:
                            fee_display_notes.append("; ".join(fee_notes))
                        fee_display_notes.append(f"Close est.: {close_fee_est:.4f}")
                        fee_display_notes.append(f"Rebalance fixed: {REBALANCE_FIXED_COST_USDC:.4f}")
                        print(f"   [FEE ] -{total_costs:.4f} USDT"
                              + f" ({' | '.join(fee_display_notes)}; EST)")
                        print(f"   [BAL ] {total_equity:.4f} USDT "
                              f"(Asterdex {bal_aster:.4f}, Hyperliquid {bal_hl:.4f}, {equity_source})")
                        ret_icon = "\U0001F7E2" if ret_pct >= 0 else "\U0001F534"
                        print(f"   [RET ] {ret_icon} {ret_pct:+.4f}% of equity")
                        if leg_ret_info:
                            print(leg_ret_info)
                        print(f"   -----------------------------------------")
                        net_icon = "\U0001F7E2" if net_pnl >= 0 else "\U0001F534"
                        print(f"   [NET ] {net_icon} {net_pnl:+.4f} USDT")
                        if auto_close_hit or drawdown_hit:
                            try:
                                ex_map = {"Asterdex": aster, "Hyperliquid": hl}
                                ex_long_obj = ex_map.get(ex_long_name)
                                ex_short_obj = ex_map.get(ex_short_name)
                                if ex_long_obj and ex_short_obj:
                                    reason = ""
                                    if auto_close_hit:
                                        reason = f"Ret {ret_pct:.4f}% >= {AUTO_CLOSE_RET_PCT:.4f}%"
                                    if drawdown_hit:
                                        if reason:
                                            reason += " | "
                                        reason += f"Leg drawdown <= -{AUTO_CLOSE_SIDE_DD_PCT:.2f}%"
                                    print(f"[Auto-Close] {reason} -> closing spread...")
                                    res_close = execu.close_spread(
                                        symbol,
                                        qty_long=float(trade.get("Long_Qty", 0) or 0),
                                        qty_short=float(trade.get("Short_Qty", 0) or 0),
                                        exchange_long=ex_long_obj,
                                        exchange_short=ex_short_obj,
                                    )
                                    print(f"[Auto-Close] Done: {res_close}")
                                else:
                                    print(f"[Auto-Close] Missing exchange objects for {symbol} (long={ex_long_name}, short={ex_short_name})")
                            except Exception as e:
                                print(f"[Auto-Close] Error: {e}")
                        print(f"   (Open since {start_time_str})\n")

                        fee_display_text = " | ".join(fee_display_notes)
                        leg_text = leg_ret_info.replace("   [LEG ] ", "").strip() if leg_ret_info else ""
                        live_section_lines = [
                            f"💹 LIVE {symbol}",
                            f"   • FUND: {net_funding:+.4f} USDT (Asterdex {fund_aster:+.4f}, Hyperliquid {fund_hl:+.4f})",
                            f"   • PNL: {price_pnl:+.4f} USDT ({pnl_source})",
                            f"   • SLIP est close: {price_pnl_slip:+.4f} USDT",
                            f"   • FEE: -{total_costs:.4f} USDT ({fee_display_text}; EST)",
                            f"   • BAL: {total_equity:.4f} USDT ({equity_source})",
                            f"   • RET: {ret_icon} {ret_pct:+.4f}% of equity",
                        ]
                        if leg_text:
                            live_section_lines.append(f"   • LEG: {leg_text}")
                        live_section_lines.append(f"   • NET: {net_icon} {net_pnl:+.4f} USDT")
                        live_section_lines.append(f"   • Open since {start_time_str}")
                        live_sections[symbol] = "\n".join(live_section_lines)
                    except Exception as e:
                        print(f"[Live PnL] Error for {symbol}: {e}")

                if final_signals:
                    top_signal = final_signals[0]

                    # Payout timing
                    aster_mins_left = TimeHelper.ms_to_mins_remaining(top_signal.next_aster_payout)
                    aster_bkk = TimeHelper.ms_to_bkk_str(top_signal.next_aster_payout)
                    hl_mins_left = TimeHelper.ms_to_mins_remaining(top_signal.next_hl_payout)
                    hl_bkk = TimeHelper.ms_to_bkk_str(top_signal.next_hl_payout)

                    icon = "👀 WATCH" if top_signal.is_watchlist else "📣 SIG"
                    warning_text = f" | {top_signal.warning}" if top_signal.warning else ""
                    hold_hours = top_signal.break_even_rounds * 8
                    price_edge_pct = top_signal.price_spread_pct * 100
                    price_line = (
                        f"💵 Price edge: {price_edge_pct:.4f}% "
                        f"(Asterdex {top_signal.aster_price:.4f} / Hyperliq {top_signal.hl_price:.4f})"
                    )

                    # Determine Pay/Recv
                    aster_action = "RECV" if top_signal.aster_rate > 0 else "PAY"  # assuming short Aster
                    hl_action = "PAY" if top_signal.hl_rate > 0 else "RECV"        # assuming long HL
                    if top_signal.direction == "LONG_ASTER_SHORT_HL":
                        aster_action = "PAY" if top_signal.aster_rate > 0 else "RECV"
                        hl_action = "RECV" if top_signal.hl_rate > 0 else "PAY"

                    separator = "━━━━━━━━━━━━"
                    msg_lines = [
                        f"🔔 {icon} {top_signal.symbol}{warning_text}",
                        separator,
                        f"📅 Monthly Return (net): {top_signal.projected_monthly_return*100:.2f}%",
                        f"📊 Spread 8h (net of fees): {top_signal.spread_net*100:.4f}%",
                        f"💫 Round Return (after fees): {top_signal.round_return_net*100:.4f}%",
                        price_line,
                        "💱 Rates (8h):",
                        f"  • Asterdex: {top_signal.aster_rate*100:.4f}% ({aster_action})",
                        f"  • Hyperliq: {top_signal.hl_rate*100:.4f}% ({hl_action})",
                        f"⏳ Min Hold: {top_signal.break_even_rounds} rounds (~{hold_hours}h) to break even",
                        f"🕰️ Asterdex Payout: in {aster_mins_left} mins ({aster_bkk} BKK)",
                        f"🕰️ HL Payout: in {hl_mins_left} mins ({hl_bkk} BKK)",
                        f"🎯 Action: {top_signal.direction}",
                        f"   (Long {top_signal.exchange_long} / Short {top_signal.exchange_short})",
                    ]
                    live_section_text = live_sections.get(top_signal.symbol)
                    if live_section_text:
                        msg_lines.append(separator)
                        msg_lines.append(live_section_text)

                    msg = "\n".join(msg_lines)
                    print(msg)
                    telegram_notifier.send_alert(msg)
                    now_sec = time.time()
                    if now_sec - last_discord_alert_ts >= DISCORD_ALERT_INTERVAL:
                        discord_notifier.send_alert(msg)
                        last_discord_alert_ts = now_sec
                    else:
                        wait_sec = int(DISCORD_ALERT_INTERVAL - (now_sec - last_discord_alert_ts))
                        print(f"[Discord] Skipped (cooldown {wait_sec}s remaining)")

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
