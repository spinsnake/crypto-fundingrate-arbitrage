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
        endpoint = "/fapi/v3/premiumIndex"
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            rates = {}
            for item in data:
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
                    timestamp=int(time.time() * 1000)
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
