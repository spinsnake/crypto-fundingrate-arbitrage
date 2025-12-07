import os
import requests
import time
from typing import Dict, Any
from dotenv import load_dotenv
from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import HYPERLIQUID_API_URL, HYPERLIQUID_TAKER_FEE

load_dotenv()

class HyperliquidAdapter(ExchangeInterface):
    def __init__(self, private_key: str = ""):
        self.private_key = private_key or os.getenv("hyperliquid_private_key", "")
        self.wallet_address = os.getenv("hyperliquid_wallet_address", "")
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
                    is_active=True,
                    taker_fee=HYPERLIQUID_TAKER_FEE
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

    def get_top_of_book(self, symbol: str) -> Dict[str, float]:
        """
        Hyperliquid public orderbook is not documented in this codebase; fallback to mark price.
        """
        try:
            # Try to infer from metaAndAssetCtxs (markPx)
            resp = requests.post(f"{self.base_url}/info", json={"type": "metaAndAssetCtxs"}, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            universe = data[0]["universe"]
            asset_ctxs = data[1]
            idx = next(i for i, a in enumerate(universe) if a["name"] == symbol)
            mark = float(asset_ctxs[idx].get("markPx", 0))
            if mark == 0:
                return {"bid": 0.0, "ask": 0.0}
            # Assume tight book around mark
            return {"bid": mark, "ask": mark}
        except Exception:
            return {"bid": 0.0, "ask": 0.0}

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

    def test_connection(self) -> bool:
        """Simple liveness check using meta endpoint"""
        try:
            resp = requests.post(f"{self.base_url}/info", json={"type": "meta"}, timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[Hyperliquid] Connection test failed: {e}")
            return False
