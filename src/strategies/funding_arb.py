from typing import List, Dict
import time
from ..core.interfaces import StrategyInterface
from ..core.models import FundingRate, Signal
from ..config import MIN_MONTHLY_RETURN, MIN_SPREAD_PER_ROUND

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
                
            # Calculate Spread
            diff = abs(aster.rate - hl.rate)
            
            # Project Returns
            daily_return = diff * 3
            monthly_return = daily_return * 30
            
            # Filter by Threshold
            if monthly_return < MIN_MONTHLY_RETURN:
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
                
            signals.append(Signal(
                symbol=symbol,
                direction=direction,
                exchange_long=exchange_long,
                exchange_short=exchange_short,
                spread=diff,
                projected_monthly_return=monthly_return,
                timestamp=int(time.time() * 1000)
            ))
            
        # Sort by profitability
        signals.sort(key=lambda x: x.projected_monthly_return, reverse=True)
        return signals
