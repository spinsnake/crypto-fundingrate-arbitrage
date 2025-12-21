from typing import List, Dict
import time
import math
from ..core.interfaces import StrategyInterface
from ..core.models import FundingRate, Signal
from ..config import (
    MIN_MONTHLY_RETURN,
    MIN_SPREAD_PER_ROUND,
    MIN_VOLUME_ASTER_USDT,
    MIN_VOLUME_HL_USDT,
    MIN_VOLUME_LIGHTER_USDT,
    ESTIMATED_FEE_PER_ROTATION,
    ENABLE_VOLUME_FILTER,
    ENABLE_DELIST_FILTER,
    WATCHLIST,
    SLIPPAGE_BPS,
    DEBUG_FILTER_LOG,
    MAX_BREAK_EVEN_ROUNDS,
    MIN_PRICE_SPREAD_PCT,
    ENABLE_PRICE_SPREAD_FILTER,
    SCAN_EXCHANGES,
    DEFAULT_LEVERAGE,
    MIN_24H_FUNDING_PCT,
    MIN_7D_FUNDING_PCT,
    MIN_30D_FUNDING_PCT,
)

EXCHANGE_KEY_TO_NAME = {
    "asterdex": "Asterdex",
    "hyperliquid": "Hyperliquid",
    "lighter": "Lighter",
}

MIN_VOLUME_BY_EXCHANGE = {
    "Asterdex": MIN_VOLUME_ASTER_USDT,
    "Hyperliquid": MIN_VOLUME_HL_USDT,
    "Lighter": MIN_VOLUME_LIGHTER_USDT,
}


def _resolve_exchange_pair() -> tuple[str, str]:
    keys = [str(k).lower() for k in SCAN_EXCHANGES]
    if len(keys) != 2 or len(set(keys)) != 2:
        return ("Asterdex", "Hyperliquid")
    ex_a = EXCHANGE_KEY_TO_NAME.get(keys[0])
    ex_b = EXCHANGE_KEY_TO_NAME.get(keys[1])
    if not ex_a or not ex_b or ex_a == ex_b:
        return ("Asterdex", "Hyperliquid")
    return (ex_a, ex_b)


def _direction_key(name: str) -> str:
    return name.upper().replace(" ", "")

class FundingArbitrageStrategy(StrategyInterface):
    def analyze(self, market_data: Dict[str, Dict[str, FundingRate]]) -> List[Signal]:
        signals = []
        debug = DEBUG_FILTER_LOG

        ex_a_name, ex_b_name = _resolve_exchange_pair()

        # market_data structure: { 'BTC': { 'ExchangeName': RateObj } }

        def log_skip(symbol: str, reason: str):
            if debug:
                print(f"[Filter] {symbol}: {reason}")

        for symbol, rates in market_data.items():
            # We need at least 2 exchanges to compare
            if len(rates) < 2:
                log_skip(symbol, f"missing second exchange (have {list(rates.keys())})")
                continue
                
            ex_a = rates.get(ex_a_name)
            ex_b = rates.get(ex_b_name)

            if not ex_a or not ex_b:
                log_skip(symbol, f"missing {ex_a_name} or {ex_b_name} rate")
                continue

            is_watched = symbol in WATCHLIST
            warning_msg = ""

            # Delist/Inactive Check
            if ENABLE_DELIST_FILTER and not is_watched:
                if not ex_a.is_active or not ex_b.is_active:
                    log_skip(
                        symbol,
                        f"inactive: {ex_a_name}={ex_a.is_active} {ex_b_name}={ex_b.is_active}"
                    )
                    continue

            # Volume Check
            if ENABLE_VOLUME_FILTER and not is_watched:
                min_a = MIN_VOLUME_BY_EXCHANGE.get(ex_a_name)
                min_b = MIN_VOLUME_BY_EXCHANGE.get(ex_b_name)
                low_a = min_a is not None and ex_a.volume_24h < min_a
                low_b = min_b is not None and ex_b.volume_24h < min_b
                if low_a or low_b:
                    log_skip(
                        symbol,
                        f"low volume: {ex_a_name}={ex_a.volume_24h:.0f}/{min_a} {ex_b_name}={ex_b.volume_24h:.0f}/{min_b}"
                    )
                    continue
                
            interval_a = getattr(ex_a, "funding_interval_hours", 8) or 8
            interval_b = getattr(ex_b, "funding_interval_hours", 8) or 8
            round_hours = max(interval_a, interval_b)

            def _rate_per_round(rate: float, interval: int) -> float:
                if interval <= 0:
                    return rate
                return rate * (round_hours / interval)

            # Calculate spread using the real funding intervals
            rate_a_round = _rate_per_round(ex_a.rate, interval_a)
            rate_b_round = _rate_per_round(ex_b.rate, interval_b)
            diff_round = abs(rate_a_round - rate_b_round)

            # Price edge (mark price difference)
            price_a = ex_a.mark_price
            price_b = ex_b.mark_price
            mid_price = (price_a + price_b) / 2 if (price_a > 0 and price_b > 0) else 0.0
            price_diff = price_b - price_a

            # Dynamic fee per rotation (open+close both legs); fallback to config constant
            fee_per_rotation = ESTIMATED_FEE_PER_ROTATION / 100
            if ex_a.taker_fee or ex_b.taker_fee:
                fee_per_rotation = (ex_a.taker_fee + ex_b.taker_fee) * 2

            # Slippage allowance per round (approx 4 legs * slippage_bps)
            slippage_cost = (SLIPPAGE_BPS / 10000) * 4

            # Minimum spread per round filter (percent scale)
            min_spread_per_round = MIN_SPREAD_PER_ROUND / 100
            if diff_round < min_spread_per_round and not is_watched:
                log_skip(
                    symbol,
                    f"spread too small: {diff_round*100:.4f}% < {MIN_SPREAD_PER_ROUND:.4f}%"
                )
                continue

            # Net per round after fees (round = max interval)
            net_per_round = diff_round - fee_per_rotation - slippage_cost

            leverage = DEFAULT_LEVERAGE if DEFAULT_LEVERAGE > 0 else 1.0
            equity_factor = leverage / 2
            net_rate_round_equity = diff_round * equity_factor
            net_rate_hour_equity = (net_rate_round_equity / round_hours) if round_hours else 0.0
            cost_equity = (fee_per_rotation + slippage_cost) * equity_factor

            fund_24h_pct = (net_rate_hour_equity * 24) - cost_equity
            fund_7d_pct = (net_rate_hour_equity * 24 * 7) - cost_equity
            fund_30d_pct = (net_rate_hour_equity * 24 * 30) - cost_equity
            
            # Filter by per-round net (we target positive net per round)
            # Filter by break-even horizon
            # We want to see if we can break even within MAX_BREAK_EVEN_ROUNDS
            # Total Cost (Fee + Slippage) <= Spread * Rounds
            
            # Note: "net_per_round" variable above is calculated as (diff_round - fee - slippage),
            # which assumes 1 round. If net_per_round > 0, it means we break even in < 1 round.
            
            # If we allow more rounds, we need to check:
            # (diff_round * MAX_BREAK_EVEN_ROUNDS) - fee_per_rotation - slippage_cost > 0
            # or equivalently: revenue_over_horizon > total_cost
            
            potential_revenue = diff_round * MAX_BREAK_EVEN_ROUNDS
            total_cost = fee_per_rotation + slippage_cost
            net_over_horizon = potential_revenue - total_cost

            if net_over_horizon <= 0 and not is_watched:
                log_skip(
                    symbol,
                    f"net<=0 (max {MAX_BREAK_EVEN_ROUNDS} rnds): spread={diff_round:.6f} cost={total_cost:.6f} net_horizon={net_over_horizon:.6f}"
                )
                continue

            min_24h = MIN_24H_FUNDING_PCT / 100
            min_7d = MIN_7D_FUNDING_PCT / 100
            min_30d = MIN_30D_FUNDING_PCT / 100
            if MIN_24H_FUNDING_PCT > 0 and fund_24h_pct < min_24h and not is_watched:
                log_skip(
                    symbol,
                    f"24h funding too low: {fund_24h_pct*100:.4f}% < {MIN_24H_FUNDING_PCT:.4f}%"
                )
                continue
            if MIN_7D_FUNDING_PCT > 0 and fund_7d_pct < min_7d and not is_watched:
                log_skip(
                    symbol,
                    f"7d funding too low: {fund_7d_pct*100:.4f}% < {MIN_7D_FUNDING_PCT:.4f}%"
                )
                continue
            if MIN_30D_FUNDING_PCT > 0 and fund_30d_pct < min_30d and not is_watched:
                log_skip(
                    symbol,
                    f"30d funding too low: {fund_30d_pct*100:.4f}% < {MIN_30D_FUNDING_PCT:.4f}%"
                )
                continue
            
            # Check for Negative/Warning for Watchlist
            if is_watched and fund_30d_pct < 0:
                warning_msg = "?? WARNING: Net Profit is NEGATIVE!"
                
            # Determine Direction
            if rate_b_round > rate_a_round:
                # Short ex_b (Receive High), Long ex_a (Pay Low)
                direction = f"LONG_{_direction_key(ex_a_name)}_SHORT_{_direction_key(ex_b_name)}"
                exchange_long = ex_a_name
                exchange_short = ex_b_name
                net_rate_per_round = rate_b_round - rate_a_round
            else:
                # Short ex_a (Receive High), Long ex_b (Pay Low)
                direction = f"LONG_{_direction_key(ex_b_name)}_SHORT_{_direction_key(ex_a_name)}"
                exchange_long = ex_b_name
                exchange_short = ex_a_name
                net_rate_per_round = rate_a_round - rate_b_round
            # Require a favorable price edge so convergence helps PnL
            price_edge_pct = 0.0
            if mid_price > 0:
                if exchange_long == ex_a_name:
                    price_edge_pct = price_diff / mid_price  # want ex_b higher than ex_a
                else:
                    price_edge_pct = -price_diff / mid_price  # want ex_a higher than ex_b

            min_price_edge = MIN_PRICE_SPREAD_PCT / 100
            if ENABLE_PRICE_SPREAD_FILTER and not is_watched:
                if mid_price <= 0:
                    log_skip(symbol, "price spread check unavailable (missing mark price)")
                    continue
                if price_edge_pct < min_price_edge:
                    log_skip(
                        symbol,
                        f"price edge too small: {price_edge_pct*100:.4f}% < {MIN_PRICE_SPREAD_PCT:.4f}%"
                    )
                    continue
                
            # Use the later funding time (usually Asterdex 8h) as the target
            next_payout = max(ex_a.next_funding_time, ex_b.next_funding_time)

            # Calculate Break-Even Rounds (Fee / Spread)
            if diff_round > 0:
                 # Rounds needed to cover total cost
                 # Cost = Fee + Slippage
                 # Revenue per round = diff_round
                 # Rounds = Cost / diff_round
                 rounds_needed = (fee_per_rotation + slippage_cost) / diff_round
                 
                 # If rounds_needed < 1, it means we profit in first round.
                 # If rounds_needed is 1.5, we break even in 2nd round.
                 break_even_rounds = math.ceil(rounds_needed)
            else:
                break_even_rounds = 999

            signals.append(Signal(
                symbol=symbol,
                direction=direction,
                exchange_long=exchange_long,
                exchange_short=exchange_short,
                spread=diff_round,
                spread_net=net_per_round,
                round_return_net=net_per_round,
                projected_monthly_return=fund_30d_pct,
                timestamp=int(time.time() * 1000),
                next_funding_time=next_payout,
                is_watchlist=is_watched,
                warning=warning_msg,
                break_even_rounds=break_even_rounds,
                exchange_a=ex_a_name,
                exchange_b=ex_b_name,
                rate_a=ex_a.rate,
                rate_b=ex_b.rate,
                next_payout_a=ex_a.next_funding_time,
                next_payout_b=ex_b.next_funding_time,
                price_a=price_a,
                price_b=price_b,
                next_aster_payout=ex_a.next_funding_time,
                next_hl_payout=ex_b.next_funding_time,
                aster_rate=ex_a.rate,
                hl_rate=ex_b.rate,
                price_spread_pct=price_edge_pct,
                price_diff=price_diff,
                aster_price=price_a,
                hl_price=price_b
            ))
            
        # Sort by profitability
        signals.sort(key=lambda x: x.projected_monthly_return, reverse=True)
        return signals

