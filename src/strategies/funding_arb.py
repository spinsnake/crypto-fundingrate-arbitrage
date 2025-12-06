from typing import List, Dict
import time
from ..core.interfaces import StrategyInterface
from ..core.models import FundingRate, Signal
from ..config import (
    MIN_MONTHLY_RETURN, MIN_SPREAD_PER_ROUND, MIN_VOLUME_USDT, ESTIMATED_FEE_PER_ROTATION,
    ENABLE_VOLUME_FILTER, ENABLE_DELIST_FILTER
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

            # Delist/Inactive Check
            if ENABLE_DELIST_FILTER:
                if not aster.is_active or not hl.is_active:
                    continue

            # Volume Check
            if ENABLE_VOLUME_FILTER:
                if aster.volume_24h < MIN_VOLUME_USDT or hl.volume_24h < MIN_VOLUME_USDT:
                    continue
                
            # Calculate Spread
            diff = abs(aster.rate - hl.rate)
            
            # Project Returns
            daily_return = diff * 3
            monthly_gross = daily_return * 30
            
            # Net Return (Subtract Entry+Exit Fees ~0.2%)
            monthly_net = monthly_gross - ESTIMATED_FEE_PER_ROTATION
            
            # Filter by Threshold
            if monthly_net < MIN_MONTHLY_RETURN:
                continue
                
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

            signals.append(Signal(
                symbol=symbol,
                direction=direction,
                exchange_long=exchange_long,
                exchange_short=exchange_short,
                spread=diff,
                projected_monthly_return=monthly_net,
                timestamp=int(time.time() * 1000),
                next_funding_time=next_payout
            ))
            
        # Sort by profitability
        signals.sort(key=lambda x: x.projected_monthly_return, reverse=True)
        return signals
