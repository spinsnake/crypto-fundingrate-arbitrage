import requests
import time
from typing import Dict, Any
from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import HYPERLIQUID_API_URL

class HyperliquidAdapter(ExchangeInterface):
    def __init__(self, private_key: str = ""):
        self.private_key = private_key
        self.base_url = HYPERLIQUID_API_URL

    def get_name(self) -> str:
        return "Hyperliquid"

    def get_all_funding_rates(self) -> Dict[str, FundingRate]:
        endpoint = "/info"
        payload = {"type": "metaAndAssetCtxs"}
        try:
            response = requests.post(f"{self.base_url}{endpoint}", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # data[0] is universe, data[1] is assetCtxs
            universe = data[0]["universe"]
            asset_ctxs = data[1]
            
            rates = {}
            for i, asset in enumerate(universe):
                symbol = asset["name"]
                ctx = asset_ctxs[i]
                
                rates[symbol] = FundingRate(
                    symbol=symbol,
                    rate=float(ctx.get('funding', 0)),
                    mark_price=float(ctx.get('markPx', 0)),
                    source=self.get_name(),
                    timestamp=int(time.time() * 1000)
                )
            return rates
        except Exception as e:
            print(f"[Hyperliquid] Error fetching rates: {e}")
            return {}

    def get_balance(self) -> float:
        # TODO: Implement balance check
        return 0.0

    def place_order(self, order: Order) -> Dict:
        # TODO: Implement order placement
        print(f"[Hyperliquid] Mock Order Placed: {order}")
        return {"status": "mock_success", "order_id": "mock_456"}
