import time
import sys
import math
from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.adapters.lighter import LighterAdapter
from src.strategies.funding_arb import FundingArbitrageStrategy
from src.notification.telegram import TelegramNotifier
from src.notification.discord import DiscordNotifier
from src.config import (
    POLL_INTERVAL,
    ENABLE_TRADING,
    WATCHLIST,
    SCAN_EXCHANGES,
    AUTO_CLOSE_RET_PCT,
    AUTO_CLOSE_SIDE_DD_PCT,
    ESTIMATED_FEE_PER_ROTATION,
    REBALANCE_FIXED_COST_USDC,
    DISCORD_ALERT_INTERVAL,
    SLIPPAGE_BPS,
    DEFAULT_LEVERAGE,
    SAFETY_BUFFER,
)
from src.core.execution_manager import ExecutionManager
from src.utils.time_helper import TimeHelper


EXCHANGE_REGISTRY = {
    "asterdex": AsterdexAdapter,
    "hyperliquid": HyperliquidAdapter,
    "lighter": LighterAdapter,
}


def _resolve_scan_exchange_keys() -> list[str]:
    keys = [str(k).lower() for k in SCAN_EXCHANGES]
    keys = [k for k in keys if k in EXCHANGE_REGISTRY]
    if len(keys) != 2 or len(set(keys)) != 2:
        print("[Config] SCAN_EXCHANGES invalid. Using ['hyperliquid', 'asterdex'].")
        return ["hyperliquid", "asterdex"]
    return keys


def main():
    print("--- Starting Crypto Arbitrage Bot (Phase 3) ---")

    scan_keys = _resolve_scan_exchange_keys()
    exchanges = [EXCHANGE_REGISTRY[key]() for key in scan_keys]
    exchange_by_name = {ex.get_name(): ex for ex in exchanges}
    
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
            market_data = {}  # { 'BTC': { 'ExchangeName': Rate } }

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
                live_horizon_returns = {}
                live_costs = {}

                # --- Live PnL for Watchlist (also used for alerts) ---
                positions_by_exchange = {}
                balances_by_exchange = {}
                for ex in exchanges:
                    ex_name = ex.get_name()
                    positions_by_exchange[ex_name] = {p["symbol"]: p for p in ex.get_open_positions()}
                    balances_by_exchange[ex_name] = ex.get_balance()
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

                        ex_long = exchange_by_name.get(ex_long_name)
                        ex_short = exchange_by_name.get(ex_short_name)
                        if not ex_long or not ex_short:
                            print(f"[Live PnL] Missing exchange adapter for {symbol} ({ex_long_name}/{ex_short_name})")
                            continue

                        fund_long = ex_long.get_funding_history(symbol, start_time, now_ms)
                        fund_short = ex_short.get_funding_history(symbol, start_time, now_ms)
                        net_funding = fund_long + fund_short

                        # 2) Fees (actual if possible)
                        fee_notes = []
                        fee_long = ex_long.get_trade_fees(symbol, start_time, now_ms)
                        fee_short = ex_short.get_trade_fees(symbol, start_time, now_ms)
                        if fee_long:
                            fee_notes.append(f"{ex_long_name} fees: {fee_long:.4f}")
                        if fee_short:
                            fee_notes.append(f"{ex_short_name} fees: {fee_short:.4f}")

                        open_fee_logged = float(trade.get("Est_Fee_Cost", 0) or 0)  # legacy estimate from log
                        # fallback estimate (open + close both legs) if no actual fee found
                        open_notional = float(trade.get("Est_Total_Notional", 0) or 0)
                        sym_data = market_data.get(symbol, {})
                        rate_long = sym_data.get(ex_long_name)
                        rate_short = sym_data.get(ex_short_name)
                        per_round_fee_rate = 0.0
                        if rate_long and rate_long.taker_fee:
                            per_round_fee_rate += rate_long.taker_fee
                        if rate_short and rate_short.taker_fee:
                            per_round_fee_rate += rate_short.taker_fee
                        if per_round_fee_rate == 0:
                            per_round_fee_rate = (ESTIMATED_FEE_PER_ROTATION / 100) / 2
                        est_open_fee = open_notional * per_round_fee_rate

                        total_fees_paid = fee_long + fee_short
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

                        curr_px_long = 0.0
                        curr_px_short = 0.0
                        entry_px_long = float(trade.get("Long_Price", 0) or 0)
                        qty_long = float(trade.get("Long_Qty", 0) or 0)
                        entry_px_short = float(trade.get("Short_Price", 0) or 0)
                        qty_short = float(trade.get("Short_Qty", 0) or 0)
                        if rate_long and rate_short:
                            curr_px_long = rate_long.mark_price
                            curr_px_short = rate_short.mark_price

                            pos_long = positions_by_exchange.get(ex_long_name, {}).get(symbol)
                            pos_short = positions_by_exchange.get(ex_short_name, {}).get(symbol)

                            # Prefer VWAP fills over log if available
                            fills_long = {}
                            fills_short = {}
                            try:
                                fills_long = ex_long.get_fill_vwap(symbol, start_time, now_ms)
                            except Exception:
                                fills_long = {}
                            try:
                                fills_short = ex_short.get_fill_vwap(symbol, start_time, now_ms)
                            except Exception:
                                fills_short = {}

                            if fills_long.get("buy_vwap"):
                                entry_px_long = float(fills_long["buy_vwap"])
                            if fills_short.get("sell_vwap"):
                                entry_px_short = float(fills_short["sell_vwap"])

                            if pos_long:
                                entry_px_long = float(pos_long.get("entry_price") or entry_px_long)
                                qty_long = float(pos_long.get("quantity") or qty_long)
                                if pos_long.get("mark_price"):
                                    curr_px_long = float(pos_long["mark_price"])
                            if pos_short:
                                entry_px_short = float(pos_short.get("entry_price") or entry_px_short)
                                qty_short = float(pos_short.get("quantity") or qty_short)
                                if pos_short.get("mark_price"):
                                    curr_px_short = float(pos_short["mark_price"])

                            # Prefer API unrealized PnL when available
                            price_pnl_api = 0.0
                            used_api = False
                            if pos_long and pos_long.get("unrealized_pnl") is not None:
                                price_pnl_api += float(pos_long.get("unrealized_pnl", 0.0))
                                used_api = True
                            if pos_short and pos_short.get("unrealized_pnl") is not None:
                                price_pnl_api += float(pos_short.get("unrealized_pnl", 0.0))
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
                            ex_long_obj = exchange_by_name.get(ex_long_name)
                            ex_short_obj = exchange_by_name.get(ex_short_name)
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
                        bal_long = balances_by_exchange.get(ex_long_name, 0.0)
                        bal_short = balances_by_exchange.get(ex_short_name, 0.0)
                        total_equity = (bal_long or 0) + (bal_short or 0)
                        equity_source = "API"
                        if total_equity <= 0:
                            total_equity = open_notional or 1.0  # avoid zero-div
                            equity_source = "EST"
                        ret_pct = (net_pnl / total_equity) * 100 if total_equity else 0.0

                        # 7) Auto-close based on return %
                        auto_close_hit = ENABLE_TRADING and AUTO_CLOSE_RET_PCT > 0 and ret_pct >= AUTO_CLOSE_RET_PCT

                        print(f"\n[= LIVE =] {symbol}")
                        print(f"   [FUND] {net_funding:+.4f} USDT "
                              f"({ex_long_name} {fund_long:+.4f}, {ex_short_name} {fund_short:+.4f})")
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
                              f"({ex_long_name} {bal_long:.4f}, {ex_short_name} {bal_short:.4f}, {equity_source})")
                        ret_icon = "\U0001F7E2" if ret_pct >= 0 else "\U0001F534"
                        print(f"   [RET ] {ret_icon} {ret_pct:+.4f}% of equity")
                        if leg_ret_info:
                            print(leg_ret_info)
                        print(f"   -----------------------------------------")
                        net_icon = "\U0001F7E2" if net_pnl >= 0 else "\U0001F534"
                        print(f"   [NET ] {net_icon} {net_pnl:+.4f} USDT")
                        held_hours = 0.0
                        rounds_held = 0.0
                        interval_long = getattr(rate_long, "funding_interval_hours", 8) if rate_long else 8
                        interval_short = getattr(rate_short, "funding_interval_hours", 8) if rate_short else 8
                        round_hours = max(interval_long or 8, interval_short or 8)
                        if start_time > 0 and round_hours > 0:
                            held_hours = max(0.0, (now_ms - start_time) / 3600000)
                            rounds_held = held_hours / round_hours
                        print(f"   [HOLD] {rounds_held:.2f} rounds (~{held_hours:.2f}h)")
                        fund_24h_gross = None
                        fund_7d_gross = None
                        fund_30d_gross = None
                        fund_24h = None
                        fund_7d = None
                        fund_30d = None
                        one_time_cost = None
                        one_time_cost_note = "LIVE"
                        notional_long = abs(entry_px_long * qty_long) if entry_px_long and qty_long else 0.0
                        notional_short = abs(entry_px_short * qty_short) if entry_px_short and qty_short else 0.0
                        notional_total = notional_long + notional_short
                        position_value = notional_total / 2 if notional_total > 0 else 0.0
                        if notional_total > 0 and rate_long and rate_short and interval_long and interval_short:
                            rate_long_per_hour = 0.0
                            rate_short_per_hour = 0.0
                            if rate_long and interval_long:
                                rate_long_per_hour = rate_long.rate / interval_long
                            if rate_short and interval_short:
                                rate_short_per_hour = rate_short.rate / interval_short

                            # Long pays positive funding, receives negative; short is the inverse.
                            funding_per_hour = (
                                (-rate_long_per_hour * notional_long)
                                + (rate_short_per_hour * notional_short)
                            )

                            fund_24h_gross = funding_per_hour * 24
                            fund_7d_gross = funding_per_hour * 24 * 7
                            fund_30d_gross = funding_per_hour * 24 * 30

                        one_time_cost = total_costs - price_pnl_slip
                        if fund_24h_gross is not None:
                            fund_24h = fund_24h_gross - one_time_cost
                            fund_7d = fund_7d_gross - one_time_cost
                            fund_30d = fund_30d_gross - one_time_cost
                            print(f"   [FUND24] {fund_24h:+.4f} USDT (net)")
                            print(f"   [FUND7D] {fund_7d:+.4f} USDT (net)")
                            print(f"   [FUND30] {fund_30d:+.4f} USDT (net)")
                        if one_time_cost is not None:
                            print(f"   [COST] {one_time_cost:+.4f} USDT (1 time)")
                        if auto_close_hit or drawdown_hit:
                            try:
                                ex_long_obj = exchange_by_name.get(ex_long_name)
                                ex_short_obj = exchange_by_name.get(ex_short_name)
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
                            f"   • FUND: {net_funding:+.4f} USDT ({ex_long_name} {fund_long:+.4f}, {ex_short_name} {fund_short:+.4f})",
                            f"   • PNL: {price_pnl:+.4f} USDT ({pnl_source})",
                            f"   • SLIP est close: {price_pnl_slip:+.4f} USDT",
                            f"   • FEE: -{total_costs:.4f} USDT ({fee_display_text}; EST)",
                            f"   • BAL: {total_equity:.4f} USDT ({ex_long_name} {bal_long:.4f}, {ex_short_name} {bal_short:.4f}, {equity_source})",
                            f"   • RET: {ret_icon} {ret_pct:+.4f}% of equity",
                        ]
                        if one_time_cost is not None:
                            live_section_lines.append(f"   1 Time Cost: {one_time_cost:+.4f} USDT")
                        if leg_text:
                            live_section_lines.append(f"   • LEG: {leg_text}")
                        live_section_lines.append(f"   • NET: {net_icon} {net_pnl:+.4f} USDT")
                        live_section_lines.append(f"   • HOLD: {rounds_held:.2f} rounds (~{held_hours:.2f}h)")
                        if fund_24h is not None:
                            live_section_lines.append(f"   • FUND24: {fund_24h:+.4f} USDT")
                            live_section_lines.append(f"   • FUND7D: {fund_7d:+.4f} USDT")
                            live_section_lines.append(f"   • FUND30: {fund_30d:+.4f} USDT")
                        else:
                            live_section_lines.append("   • FUND24: N/A")
                            live_section_lines.append("   • FUND7D: N/A")
                            live_section_lines.append("   • FUND30: N/A")
                        live_section_lines.append(f"   • Open since {start_time_str}")
                        live_sections[symbol] = "\n".join(live_section_lines)
                        live_costs[symbol] = {
                            "one_time_cost": one_time_cost,
                            "one_time_cost_note": one_time_cost_note,
                            "position_value": position_value,
                            "notional_long": notional_long,
                            "notional_short": notional_short,
                            "total_equity": total_equity,
                            "bal_long": bal_long,
                            "bal_short": bal_short,
                            "equity_source": equity_source,
                        }
                        if fund_24h is not None:
                            live_horizon_returns[symbol] = {
                                "24h": fund_24h,
                                "7d": fund_7d,
                                "30d": fund_30d,
                            }
                    except Exception as e:
                        print(f"[Live PnL] Error for {symbol}: {e}")

                if final_signals:
                    top_signal = final_signals[0]

                    # Payout timing
                    ex_a_name = top_signal.exchange_a or "Asterdex"
                    ex_b_name = top_signal.exchange_b or "Hyperliquid"
                    rate_a = top_signal.rate_a if top_signal.exchange_a else top_signal.aster_rate
                    rate_b = top_signal.rate_b if top_signal.exchange_b else top_signal.hl_rate
                    price_a = top_signal.price_a if top_signal.exchange_a else top_signal.aster_price
                    price_b = top_signal.price_b if top_signal.exchange_b else top_signal.hl_price
                    payout_a = top_signal.next_payout_a if top_signal.exchange_a else top_signal.next_aster_payout
                    payout_b = top_signal.next_payout_b if top_signal.exchange_b else top_signal.next_hl_payout

                    ex_a_mins_left = TimeHelper.ms_to_mins_remaining(payout_a)
                    ex_a_bkk = TimeHelper.ms_to_bkk_str(payout_a)
                    ex_b_mins_left = TimeHelper.ms_to_mins_remaining(payout_b)
                    ex_b_bkk = TimeHelper.ms_to_bkk_str(payout_b)

                    icon = "WATCH" if top_signal.is_watchlist else "SIG"
                    warning_text = f" | {top_signal.warning}" if top_signal.warning else ""
                    price_edge_pct = top_signal.price_spread_pct * 100
                    price_line = (
                        f"Price edge: {price_edge_pct:.4f}% "
                        f"({ex_a_name} {price_a:.4f} / {ex_b_name} {price_b:.4f})"
                    )

                    # Determine Pay/Recv
                    rate_by_exchange = {ex_a_name: rate_a, ex_b_name: rate_b}

                    def funding_action(ex_name: str) -> str:
                        rate_val = rate_by_exchange.get(ex_name, 0.0)
                        is_long = ex_name == top_signal.exchange_long
                        if rate_val >= 0:
                            return "PAY" if is_long else "RECV"
                        return "RECV" if is_long else "PAY"

                    ex_a_action = funding_action(ex_a_name)
                    ex_b_action = funding_action(ex_b_name)

                    rate_obj_a = market_data.get(top_signal.symbol, {}).get(ex_a_name)
                    rate_obj_b = market_data.get(top_signal.symbol, {}).get(ex_b_name)
                    interval_a = getattr(rate_obj_a, "funding_interval_hours", 8) if rate_obj_a else 8
                    interval_b = getattr(rate_obj_b, "funding_interval_hours", 8) if rate_obj_b else 8

                    rate_obj_by_name = {ex_a_name: rate_obj_a, ex_b_name: rate_obj_b}
                    interval_long = getattr(rate_obj_by_name.get(top_signal.exchange_long), "funding_interval_hours", 8)
                    interval_short = getattr(rate_obj_by_name.get(top_signal.exchange_short), "funding_interval_hours", 8)
                    round_hours = max(interval_long or 8, interval_short or 8)

                    fee_per_rotation = ESTIMATED_FEE_PER_ROTATION / 100
                    taker_a = getattr(rate_obj_a, "taker_fee", 0.0) if rate_obj_a else 0.0
                    taker_b = getattr(rate_obj_b, "taker_fee", 0.0) if rate_obj_b else 0.0
                    if taker_a or taker_b:
                        fee_per_rotation = (taker_a + taker_b) * 2
                    slippage_cost = (SLIPPAGE_BPS / 10000) * 4
                    diff_round = top_signal.spread

                    break_even_hours = None
                    if diff_round > 0:
                        break_even_rounds = math.ceil((fee_per_rotation + slippage_cost) / diff_round)
                        break_even_hours = break_even_rounds * round_hours
                    break_even_text = "N/A"
                    if break_even_hours is not None:
                        break_even_text = f"{break_even_hours}h"

                    # Equity / position estimate
                    bal_a = balances_by_exchange.get(ex_a_name, 0.0)
                    bal_b = balances_by_exchange.get(ex_b_name, 0.0)
                    total_equity = (bal_a or 0) + (bal_b or 0)

                    live_cost = live_costs.get(top_signal.symbol)
                    notional_long = 0.0
                    notional_short = 0.0
                    position_value = 0.0
                    if live_cost:
                        notional_long = live_cost.get("notional_long", 0.0)
                        notional_short = live_cost.get("notional_short", 0.0)
                        position_value = live_cost.get("position_value", 0.0)
                        total_equity = total_equity or live_cost.get("total_equity", 0.0)

                    if position_value <= 0:
                        trade = execu.get_last_open_trade(top_signal.symbol)
                        if trade:
                            open_notional = float(trade.get("Est_Total_Notional", 0) or 0)
                            if open_notional > 0:
                                position_value = open_notional / 2
                                notional_long = position_value
                                notional_short = position_value

                    if position_value <= 0 and bal_a > 0 and bal_b > 0:
                        position_value = min(bal_a, bal_b) * SAFETY_BUFFER * DEFAULT_LEVERAGE
                        notional_long = position_value
                        notional_short = position_value

                    if notional_long <= 0:
                        notional_long = position_value
                    if notional_short <= 0:
                        notional_short = position_value

                    rate_long_val = rate_by_exchange.get(top_signal.exchange_long, 0.0)
                    rate_short_val = rate_by_exchange.get(top_signal.exchange_short, 0.0)
                    rate_long_round = rate_long_val * (round_hours / interval_long) if interval_long else rate_long_val
                    rate_short_round = rate_short_val * (round_hours / interval_short) if interval_short else rate_short_val
                    spread_round = (-rate_long_round) + (rate_short_round)
                    spread_pct = spread_round * 100

                    one_time_cost = None
                    one_time_cost_note = ""
                    if live_cost:
                        one_time_cost = live_cost.get("one_time_cost")
                        one_time_cost_note = live_cost.get("one_time_cost_note", "LIVE")

                    if one_time_cost is None and position_value > 0:
                        total_notional = position_value * 2
                        one_time_cost = total_notional * (fee_per_rotation + slippage_cost) + REBALANCE_FIXED_COST_USDC
                        one_time_cost_note = "EST"

                    cost_text = "N/A"
                    if one_time_cost is not None:
                        cost_text = f"{one_time_cost:+.4f} USDT"
                        if one_time_cost_note:
                            cost_text += f" ({one_time_cost_note})"

                    fund_24h_text = "N/A"
                    fund_7d_text = "N/A"
                    fund_30d_text = "N/A"
                    if position_value > 0 and interval_long and interval_short:
                        funding_per_hour = (
                            (-rate_long_val / interval_long) * (notional_long or 0.0)
                            + (rate_short_val / interval_short) * (notional_short or 0.0)
                        )
                        fund_24h_gross = funding_per_hour * 24
                        fund_7d_gross = funding_per_hour * 24 * 7
                        fund_30d_gross = funding_per_hour * 24 * 30
                        if one_time_cost is not None:
                            fund_24h_net = fund_24h_gross - one_time_cost
                            fund_7d_net = fund_7d_gross - one_time_cost
                            fund_30d_net = fund_30d_gross - one_time_cost
                            if total_equity > 0:
                                fund_24h_text = f"{fund_24h_net:+.4f} USDT ({(fund_24h_net/total_equity)*100:+.2f}%)"
                                fund_7d_text = f"{fund_7d_net:+.4f} USDT ({(fund_7d_net/total_equity)*100:+.2f}%)"
                                fund_30d_text = f"{fund_30d_net:+.4f} USDT ({(fund_30d_net/total_equity)*100:+.2f}%)"
                            else:
                                fund_24h_text = f"{fund_24h_net:+.4f} USDT"
                                fund_7d_text = f"{fund_7d_net:+.4f} USDT"
                                fund_30d_text = f"{fund_30d_net:+.4f} USDT"

                    separator = "-" * 38
                    position_text = "N/A" if position_value <= 0 else f"{position_value:.2f} USDT"
                    msg_lines = [
                        f"{icon} {top_signal.symbol}{warning_text}",
                        separator,
                        "💼 Equity:",
                        f"   {ex_a_name}: {bal_a:.4f} USDT",
                        f"   {ex_b_name}: {bal_b:.4f} USDT",
                        f"⚖️ Leverage: {DEFAULT_LEVERAGE}x",
                        f"📊 Position Value: {position_text}",
                        "💱 Rates (interval):",
                        f"  • {ex_a_name}: {rate_a*100:.4f}% ({interval_a}h, {ex_a_action})",
                        f"  • {ex_b_name}: {rate_b*100:.4f}% ({interval_b}h, {ex_b_action})",
                        f"  • Spread: {spread_pct:+.4f}% ({round_hours}h)",
                        f"💸 1 Time Cost: {cost_text}",
                        f"📅 24H Funding: {fund_24h_text}",
                        f"📅 7D Funding: {fund_7d_text}",
                        f"📅 30D Funding: {fund_30d_text}",
                        f"💵 {price_line}",
                        f"⏳ Min Hold: {break_even_text} to break even",
                        f"🕰️ {ex_a_name} Payout: in {ex_a_mins_left} mins ({ex_a_bkk} BKK)",
                        f"🕰️ {ex_b_name} Payout: in {ex_b_mins_left} mins ({ex_b_bkk} BKK)",
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




