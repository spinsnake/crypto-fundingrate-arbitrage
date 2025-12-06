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
                
                # Hyperliquid pays every hour on the hour
                next_hour = (int(time.time() / 3600) + 1) * 3600 * 1000
                
                rates[symbol] = FundingRate(
                    symbol=symbol,
                    rate=float(ctx.get('funding', 0)),
                    mark_price=float(ctx.get('markPx', 0)),
                    source=self.get_name(),
                    timestamp=int(time.time() * 1000),
                    volume_24h=float(ctx.get('dayNtlVlm', 0)),
                    next_funding_time=next_hour,
                    is_active=True
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

    def is_symbol_active(self, symbol: str) -> bool:
        # Hyperliquid universe check
        if not hasattr(self, '_active_symbols') or time.time() - getattr(self, '_last_update', 0) > 3600:
            try:
                response = requests.post(f"{self.base_url}/info", json={"type": "meta"}, timeout=10)
                response.raise_for_status()
                data = response.json()
                self._active_symbols = {a['name'] for a in data['universe']}
                self._last_update = time.time()
                print(f"[Hyperliquid] Updated active symbols: {len(self._active_symbols)}")
            except Exception as e:
                print(f"[Hyperliquid] Error checking status: {e}")
                return True
                
        return symbol in self._active_symbols
