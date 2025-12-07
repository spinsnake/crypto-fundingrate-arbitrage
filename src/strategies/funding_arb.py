from typing import List, Dict
import time
from ..core.interfaces import StrategyInterface
from ..core.models import FundingRate, Signal
from ..config import (
    MIN_MONTHLY_RETURN, MIN_SPREAD_PER_ROUND, MIN_VOLUME_USDT, ESTIMATED_FEE_PER_ROTATION,
    ENABLE_VOLUME_FILTER, ENABLE_DELIST_FILTER, WATCHLIST, SLIPPAGE_BPS
)

class FundingArbitrageStrategy(StrategyInterface):
    def analyze(self, market_data: Dict[str, Dict[str, FundingRate]]) -> List[Signal]:
        signals = []
        
        # market_data structure: { 'BTC': { 'Asterdex': RateObj, 'Hyperliquid': RateObj } }
        
        for symbol, rates in market_data.items():
            # We need at least 2 exchanges to compare
            if len(rates) < 2:
                continue
                
            # For this specific strategy, we look for Asterdex vs Hyperliquid
            aster = rates.get('Asterdex')
            hl = rates.get('Hyperliquid')
            
            if not aster or not hl:
                continue

            is_watched = symbol in WATCHLIST
            warning_msg = ""

            # Delist/Inactive Check
            if ENABLE_DELIST_FILTER and not is_watched:
                if not aster.is_active or not hl.is_active:
                    continue

            # Volume Check
            if ENABLE_VOLUME_FILTER and not is_watched:
                if aster.volume_24h < MIN_VOLUME_USDT or hl.volume_24h < MIN_VOLUME_USDT:
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
            
            # Project Returns
            daily_return = diff * 3
            monthly_gross = daily_return * 30
            
            # Net Return (Subtract Entry+Exit Fees ~0.2%)
            monthly_net = monthly_gross - fee_per_rotation - slippage_cost
            
            # Filter by Threshold
            if monthly_net < MIN_MONTHLY_RETURN and not is_watched:
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
            # Avoid division by zero
            if diff > 0:
                break_even_rounds = int((fee_per_rotation / diff) + 0.99) # Ceiling division
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
                break_even_rounds=break_even_rounds
            ))
            
        # Sort by profitability
        signals.sort(key=lambda x: x.projected_monthly_return, reverse=True)
        return signals
