import os
import requests
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import ASTERDEX_API_URL, ASTERDEX_TAKER_FEE
import hmac
import hashlib
import urllib.parse

load_dotenv()

class AsterdexAdapter(ExchangeInterface):
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or os.getenv("asterdex_api_key", "")
        self.api_secret = api_secret or os.getenv("asterdex_api_secret", "")
        self.base_url = ASTERDEX_API_URL
        self._filters: Dict[str, Dict[str, float]] = {}

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
                    next_funding_time=int(item.get('nextFundingTime', 0)),
                    is_active=self.is_symbol_active(base_symbol),
                    taker_fee=ASTERDEX_TAKER_FEE
                )
            return rates
        except Exception as e:
            print(f"[Asterdex] Error fetching rates: {e}")
            return {}

    def get_balance(self) -> float:
        # Placeholder: would require signed request to account endpoint
        return 0.0

    def place_order(self, order: Order) -> Dict:
        """
        Best-effort Binance-style signed order. Falls back to mock if keys missing or call fails.
        """
        if not self.api_key or not self.api_secret:
            print(f"[Asterdex] Mock Order Placed (no API key/secret): {order}")
            return {"status": "mock_success", "order_id": "mock_123"}

        symbol_pair = f"{order.symbol}USDT"
        qty, px = self._round_qty_px(symbol_pair, order.quantity, order.price)

        endpoint = "/fapi/v1/order"
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol_pair,
            "side": order.side,
            "type": order.type,
            "quantity": qty,
            "timestamp": timestamp,
            "recvWindow": 5000,
        }
        if order.type.upper() == "LIMIT":
            params["price"] = px
            params["timeInForce"] = "GTC"
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            resp = requests.post(f"{self.base_url}{endpoint}", params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[Asterdex] Order failed, falling back to mock: {e}")
            print(f"[Asterdex] Mock Order Placed: {order}")
            return {"status": "mock_success", "order_id": "mock_asterdex_fallback"}

    def get_open_positions(self) -> list:
        """
        Best-effort to fetch positions via Binance-style endpoint; fallback empty on failure.
        """
        if not self.api_key or not self.api_secret:
            print("[Asterdex] get_open_positions using mock (no API key/secret)")
            return []
        endpoint = "/fapi/v2/positionRisk"
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp, "recvWindow": 5000}
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = signature
        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            positions = []
            for p in data:
                amt = float(p.get("positionAmt", 0))
                if amt == 0:
                    continue
                sym = p.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                base = sym[:-4]
                side = "LONG" if amt > 0 else "SHORT"
                positions.append({"symbol": base, "side": side, "quantity": abs(amt)})
            return positions
        except Exception as e:
            print(f"[Asterdex] get_open_positions failed: {e}")
            return []

    def _round_qty_px(self, symbol_pair: str, qty: float, price: Optional[float]) -> tuple:
        """Round quantity/price using exchangeInfo filters when available."""
        if symbol_pair not in self._filters:
            self._load_filters()
        f = self._filters.get(symbol_pair, {})
        step = f.get("stepSize", 0)
        tick = f.get("tickSize", 0)

        def _round(value: float, step_size: float) -> float:
            if step_size <= 0:
                return value
            return max(step_size, (int(value / step_size)) * step_size)

        qty_r = _round(qty, step)
        px_r = _round(price, tick) if price is not None else None
        return qty_r, px_r

    def _load_filters(self):
        try:
            resp = requests.get(f"{self.base_url}/fapi/v1/exchangeInfo", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            for sym in data.get("symbols", []):
                spair = sym.get("symbol")
                if not spair:
                    continue
                filters = sym.get("filters", [])
                step = 0
                tick = 0
                for flt in filters:
                    ftype = flt.get("filterType")
                    if ftype == "LOT_SIZE":
                        step = float(flt.get("stepSize", 0))
                    if ftype == "PRICE_FILTER":
                        tick = float(flt.get("tickSize", 0))
                self._filters[spair] = {"stepSize": step, "tickSize": tick}
        except Exception as e:
            print(f"[Asterdex] load filters failed: {e}")

    def get_top_of_book(self, symbol: str) -> Dict[str, float]:
        """
        Return best bid/ask for symbol (USDT pairs). Uses mark price as fallback.
        """
        pair = f"{symbol}USDT"
        try:
            depth = requests.get(f"{self.base_url}/fapi/v1/depth", params={"symbol": pair, "limit": 5}, timeout=5)
            depth.raise_for_status()
            data = depth.json()
            bid = float(data["bids"][0][0]) if data.get("bids") else 0.0
            ask = float(data["asks"][0][0]) if data.get("asks") else 0.0
            # Fallback to mark price if empty book
            if bid == 0 or ask == 0:
                mp = self._get_mark_price(pair)
                return {"bid": mp, "ask": mp}
            return {"bid": bid, "ask": ask}
        except Exception:
            mp = self._get_mark_price(pair)
            return {"bid": mp, "ask": mp}

    def _get_mark_price(self, pair: str) -> float:
        try:
            r = requests.get(f"{self.base_url}/fapi/v1/premiumIndex", params={"symbol": pair}, timeout=5)
            r.raise_for_status()
            data = r.json()
            return float(data.get("markPrice", 0))
        except Exception:
            return 0.0

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

    def test_connection(self) -> bool:
        """Simple liveness check using public endpoint"""
        try:
            resp = requests.get(f"{self.base_url}/fapi/v3/premiumIndex", timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[Asterdex] Connection test failed: {e}")
            return False
