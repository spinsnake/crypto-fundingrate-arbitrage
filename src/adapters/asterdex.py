import requests
import time
from typing import Dict, Any
from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import ASTERDEX_API_URL

class AsterdexAdapter(ExchangeInterface):
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = ASTERDEX_API_URL

    def get_name(self) -> str:
        return "Asterdex"

    def get_all_funding_rates(self) -> Dict[str, FundingRate]:
        try:
            # Fetch Funding Rates
            fr_response = requests.get(f"{self.base_url}/fapi/v3/premiumIndex", timeout=10)
            fr_response.raise_for_status()
            fr_data = fr_response.json()
            
            # Fetch 24h Ticker for Volume
            ticker_response = requests.get(f"{self.base_url}/fapi/v3/ticker/24hr", timeout=10)
            ticker_response.raise_for_status()
            ticker_data = ticker_response.json()
            
            # Map volume: {symbol: quoteVolume}
            vol_map = {t['symbol']: float(t.get('quoteVolume', 0)) for t in ticker_data}

            rates = {}
            for item in fr_data:
                symbol = item.get('symbol', '')
                if not symbol.endswith("USDT"):
                    continue
                    
                # Convert ETHUSDT -> ETH
                base_symbol = symbol[:-4]
                
                rates[base_symbol] = FundingRate(
                    symbol=base_symbol,
                    rate=float(item.get('lastFundingRate', 0)),
                    mark_price=float(item.get('markPrice', 0)),
                    source=self.get_name(),
                    timestamp=int(time.time() * 1000),
                    volume_24h=vol_map.get(symbol, 0.0),
                    next_funding_time=int(item.get('nextFundingTime', 0))
                )
            return rates
        except Exception as e:
            print(f"[Asterdex] Error fetching rates: {e}")
            return {}

    def get_balance(self) -> float:
        # TODO: Implement signed request for balance
        return 0.0

    def place_order(self, order: Order) -> Dict:
        # TODO: Implement signed request for order
        print(f"[Asterdex] Mock Order Placed: {order}")
        return {"status": "mock_success", "order_id": "mock_123"}

    def is_symbol_active(self, symbol: str) -> bool:
        # Simple caching mechanism (refresh every 1 hour)
        if not hasattr(self, '_active_symbols') or time.time() - getattr(self, '_last_update', 0) > 3600:
            try:
                response = requests.get(f"{self.base_url}/fapi/v3/exchangeInfo", timeout=10)
                response.raise_for_status()
                data = response.json()
                self._active_symbols = {
                    s['symbol'][:-4] for s in data['symbols'] 
                    if s['status'] == 'TRADING' and s['symbol'].endswith('USDT')
                }
                self._last_update = time.time()
                print(f"[Asterdex] Updated active symbols: {len(self._active_symbols)}")
            except Exception as e:
                print(f"[Asterdex] Error checking status: {e}")
                return True # Default to True to avoid blocking if API fails, but log error
        
        return symbol in self._active_symbols
