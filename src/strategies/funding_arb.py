from typing import List, Dict
import time
import math
from ..core.interfaces import StrategyInterface
from ..core.models import FundingRate, Signal
from ..config import (
    MIN_MONTHLY_RETURN, MIN_SPREAD_PER_ROUND, MIN_VOLUME_ASTER_USDT, MIN_VOLUME_HL_USDT,
    ESTIMATED_FEE_PER_ROTATION, ENABLE_VOLUME_FILTER, ENABLE_DELIST_FILTER, WATCHLIST,
    SLIPPAGE_BPS, DEBUG_FILTER_LOG, MAX_BREAK_EVEN_ROUNDS
)

class FundingArbitrageStrategy(StrategyInterface):
    def analyze(self, market_data: Dict[str, Dict[str, FundingRate]]) -> List[Signal]:
        signals = []
        debug = DEBUG_FILTER_LOG
        
        # market_data structure: { 'BTC': { 'Asterdex': RateObj, 'Hyperliquid': RateObj } }

        def log_skip(symbol: str, reason: str):
            if debug:
                print(f"[Filter] {symbol}: {reason}")

        for symbol, rates in market_data.items():
            # We need at least 2 exchanges to compare
            if len(rates) < 2:
                log_skip(symbol, f"missing second exchange (have {list(rates.keys())})")
                continue
                
            # For this specific strategy, we look for Asterdex vs Hyperliquid
            aster = rates.get('Asterdex')
            hl = rates.get('Hyperliquid')
            
            if not aster or not hl:
                log_skip(symbol, "missing Asterdex or Hyperliquid rate")
                continue

            is_watched = symbol in WATCHLIST
            warning_msg = ""

            # Delist/Inactive Check
            if ENABLE_DELIST_FILTER and not is_watched:
                if not aster.is_active or not hl.is_active:
                    log_skip(symbol, f"inactive: aster_active={aster.is_active} hl_active={hl.is_active}")
                    continue

            # Volume Check
            if ENABLE_VOLUME_FILTER and not is_watched:
                if aster.volume_24h < MIN_VOLUME_ASTER_USDT or hl.volume_24h < MIN_VOLUME_HL_USDT:
                    log_skip(
                        symbol,
                        f"low volume: aster={aster.volume_24h:.0f}/{MIN_VOLUME_ASTER_USDT} hl={hl.volume_24h:.0f}/{MIN_VOLUME_HL_USDT}"
                    )
                    continue
                
            # Calculate Spread
            diff = abs(aster.rate - hl.rate)

            # Dynamic fee per rotation (open+close both legs); fallback to config constant
            fee_per_rotation = ESTIMATED_FEE_PER_ROTATION
            if aster.taker_fee or hl.taker_fee:
                fee_per_rotation = (aster.taker_fee + hl.taker_fee) * 2

            # Slippage allowance per round (approx 4 legs * slippage_bps)
            slippage_cost = (SLIPPAGE_BPS / 10000) * 4

            # Net per 8h round after fees (conservative: fee charged once per open+close)
            net_per_round = diff - fee_per_rotation - slippage_cost
            
            # Project Returns for HOLDING strategy:
            # Revenue = Spread * 90 rounds (30 days), Cost = Fee + Slippage (paid once)
            monthly_revenue = diff * 90
            monthly_net = monthly_revenue - (fee_per_rotation + slippage_cost)
            
            # Filter by per-round net (we target positive net per round)
            # Filter by break-even horizon
            # We want to see if we can break even within MAX_BREAK_EVEN_ROUNDS
            # Total Cost (Fee + Slippage) <= Spread * Rounds
            
            # Note: "net_per_round" variable above is calculated as (diff - fee - slippage), 
            # which assumes 1 round. If net_per_round > 0, it means we break even in < 1 round.
            
            # If we allow more rounds, we need to check:
            # (diff * MAX_BREAK_EVEN_ROUNDS) - fee_per_rotation - slippage_cost > 0
            # or equivalently: revenue_over_horizon > total_cost
            
            potential_revenue = diff * MAX_BREAK_EVEN_ROUNDS
            total_cost = fee_per_rotation + slippage_cost
            net_over_horizon = potential_revenue - total_cost

            if net_over_horizon <= 0 and not is_watched:
                 log_skip(
                    symbol,
                    f"net<=0 (max {MAX_BREAK_EVEN_ROUNDS} rnds): spread={diff:.6f} cost={total_cost:.6f} net_horizon={net_over_horizon:.6f}"
                )
                 continue
            
            # Check for Negative/Warning for Watchlist
            if is_watched and monthly_net < 0:
                warning_msg = "⚠️ WARNING: Net Profit is NEGATIVE!"
                
            # Determine Direction
            if hl.rate > aster.rate:
                # Short HL (Receive High), Long Aster (Pay Low)
                direction = "LONG_ASTER_SHORT_HL"
                exchange_long = "Asterdex"
                exchange_short = "Hyperliquid"
            else:
                # Short Aster (Receive High), Long HL (Pay Low)
                direction = "LONG_HL_SHORT_ASTER"
                exchange_long = "Hyperliquid"
                exchange_short = "Asterdex"
                
            # Use the later funding time (usually Asterdex 8h) as the target
            next_payout = max(aster.next_funding_time, hl.next_funding_time)

            # Calculate Break-Even Rounds (Fee / Spread)
            # Avoid division by zero and handle negative net
            # Calculate Break-Even Rounds (Fee / Spread)
            # Avoid division by zero
            if diff > 0:
                 # Rounds needed to cover total cost
                 # Cost = Fee + Slippage
                 # Revenue per round = diff
                 # Rounds = Cost / diff
                 rounds_needed = (fee_per_rotation + slippage_cost) / diff
                 
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
                spread=diff,
                spread_net=net_per_round,
                round_return_net=net_per_round,
                projected_monthly_return=monthly_net,
                timestamp=int(time.time() * 1000),
                next_funding_time=next_payout,
                is_watchlist=is_watched,
                warning=warning_msg,
                break_even_rounds=break_even_rounds,
                next_aster_payout=aster.next_funding_time,
                next_hl_payout=hl.next_funding_time,
                aster_rate=aster.rate,
                hl_rate=hl.rate
            ))
            
        # Sort by profitability
        signals.sort(key=lambda x: x.projected_monthly_return, reverse=True)
        return signals
