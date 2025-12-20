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
from collections import OrderedDict
from decimal import Decimal, ROUND_DOWN, InvalidOperation

import json

load_dotenv()

CACHE_FILE = "asterdex_intervals.json"

class AsterdexAdapter(ExchangeInterface):
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or os.getenv("asterdex_api_key", "")
        self.api_secret = api_secret or os.getenv("asterdex_api_secret", "")
        self.base_url = ASTERDEX_API_URL
        self._filters: Dict[str, Dict[str, float]] = {}
        self._interval_cache: Dict[str, int] = {} # Cache for funding intervals (hours)
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    self._interval_cache = json.load(f)
                print(f"[Asterdex] Loaded {len(self._interval_cache)} intervals from cache.")
            except Exception as e:
                print(f"[Asterdex] Failed to load cache: {e}")

    def _save_cache(self):
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self._interval_cache, f, indent=2)
        except Exception as e:
            print(f"[Asterdex] Failed to save cache: {e}")


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
                # Convert ETHUSDT -> ETH
                base_symbol = symbol[:-4]
                
                # Get dynamic interval
                interval_hours = self._get_funding_interval_hours(base_symbol)
                norm_factor = 8 / interval_hours if interval_hours > 0 else 1
                
                # Use API provided nextFundingTime directly
                next_funding_time = int(item.get('nextFundingTime', 0))
                if next_funding_time == 0:
                     # Fallback calculation if API missing
                     now = time.time()
                     interval_sec = interval_hours * 3600
                     next_funding_time = int(((now // interval_sec) + 1) * interval_sec * 1000)

                rates[base_symbol] = FundingRate(
                    symbol=base_symbol,
                    rate=float(item.get('lastFundingRate', 0)) * norm_factor, # Normalize to 8h
                    mark_price=float(item.get('markPrice', 0)),
                    source=self.get_name(),
                    timestamp=int(time.time() * 1000),
                    volume_24h=vol_map.get(symbol, 0.0),
                    next_funding_time=next_funding_time,
                    is_active=self.is_symbol_active(base_symbol),
                    taker_fee=ASTERDEX_TAKER_FEE / 100  # store as decimal fraction
                )
            return rates
        except Exception as e:
            print(f"[Asterdex] Error fetching rates: {e}")
            return {}


    def get_balance(self) -> float:
        """
        Best-effort fetch USDT account equity (margin balance) for futures.

        Why: the UI shows both "Wallet Balance" and "Margin Balance"; for PnL / equity tracking
        we want the margin/equity figure (wallet + unrealized PnL), not only wallet cash.

        Implementation:
        - Try signed /fapi/v2/account and return totalMarginBalance (Binance-style field),
          falling back to totalWalletBalance + totalUnrealizedProfit when available.
        - If that endpoint/fields are unavailable, fall back to signed /fapi/v2/balance "balance".

        Returns 0.0 on error.
        """
        if not self.api_key or not self.api_secret:
            print("[Asterdex] get_balance missing api key/secret, returning 0")
            return 0.0

        timestamp = int(time.time() * 1000)
        headers = {"X-MBX-APIKEY": self.api_key}

        def _signed_get(endpoint: str) -> Any:
            params = {"timestamp": timestamp, "recvWindow": 5000}
            query = urllib.parse.urlencode(params)
            signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            resp = requests.get(
                f"{self.base_url}{endpoint}",
                params={**params, "signature": signature},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

        # 1) Prefer account equity (margin balance)
        try:
            data = _signed_get("/fapi/v2/account")
            if isinstance(data, dict):
                # Most useful field (Binance futures)
                total_margin = data.get("totalMarginBalance")
                if total_margin is not None:
                    return float(total_margin or 0)

                # Fallback: wallet + unrealized
                total_wallet = data.get("totalWalletBalance")
                total_unreal = data.get("totalUnrealizedProfit")
                if total_wallet is not None or total_unreal is not None:
                    return float(total_wallet or 0) + float(total_unreal or 0)
        except Exception as e:
            # Don't spam logs here; we'll fall back to /balance
            print(f"[Asterdex] get_balance (/fapi/v2/account) failed, falling back: {e}")

        # 2) Fallback: balance list (often closer to wallet balance)
        try:
            data = _signed_get("/fapi/v2/balance")
            if isinstance(data, list):
                for item in data:
                    if item.get("asset") == "USDT":
                        return float(item.get("balance", 0) or 0)
            return 0.0
        except Exception as e:
            print(f"[Asterdex] get_balance failed: {e}")
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
        if bool(getattr(order, "reduce_only", False)):
            params["reduceOnly"] = "true"
        if order.type.upper() == "LIMIT":
            params["price"] = px
            params["timeInForce"] = "GTC"
        # Preserve order for signing
        query = urllib.parse.urlencode(list(OrderedDict(params).items()))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        signed_params = dict(params)
        signed_params["signature"] = signature

        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/x-www-form-urlencoded"}
        try:
            resp = requests.post(f"{self.base_url}{endpoint}", data=signed_params, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            try:
                err_body = resp.text  # type: ignore
            except Exception:
                err_body = ""
            print(f"[Asterdex] Order failed, falling back to mock: {e} {err_body}")
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
                entry_price = float(p.get("entryPrice", 0) or 0)
                mark_price = float(p.get("markPrice", 0) or 0)
                unrealized = float(p.get("unRealizedProfit", 0) or 0)
                positions.append(
                    {
                        "symbol": base,
                        "side": side,
                        "quantity": abs(amt),
                        "entry_price": entry_price,
                        "mark_price": mark_price,
                        "unrealized_pnl": unrealized,
                    }
                )
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

        def _quant(val: float, step_size: float) -> float:
            if step_size and step_size > 0:
                try:
                    q = Decimal(str(step_size))
                    v = Decimal(str(val))
                    return float((v // q) * q)
                except (InvalidOperation, ValueError):
                    pass
            # fallback: trim precision
            return float(Decimal(str(val)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN))

        qty_r = _quant(qty, step)
        px_r = _quant(price, tick) if price is not None else None
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

    def get_funding_history(self, symbol: str, start_time: int, end_time: int) -> float:
        if not self.api_key or not self.api_secret:
            return 0.0

        symbol_pair = f"{symbol}USDT"
        endpoint = "/fapi/v1/income"
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol_pair,
            "incomeType": "FUNDING_FEE",
            "startTime": start_time,
            "endTime": end_time,
            "limit": 1000,
            "timestamp": timestamp,
            "recvWindow": 5000
        }
        
        # Sign
        query = urllib.parse.urlencode(list(OrderedDict(params).items()))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        # Construct final URL with signature to ensure order matches
        final_query = f"{query}&signature={signature}"
        
        headers = {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            # Send GET directly
            response = requests.get(f"{self.base_url}{endpoint}?{final_query}", headers=headers, timeout=10)
            
            # Handle 401 specifically
            if response.status_code == 401:
                print(f"[Asterdex] 401 Unauthorized. Check API Key/Secret/Time.")
                return 0.0

            response.raise_for_status()
            data = response.json()
            # Sum up all income entries
            # Sum up all income entries
            # No sign flip: API returns actual realized PnL (Negative = Cost, Positive = Income)
            total_funding = sum(float(item.get('income', 0)) for item in data)
            return total_funding 
        except Exception as e:
            print(f"[Asterdex] Error fetching funding history: {e}")
            return 0.0

    def get_trade_fees(self, symbol: str, start_time: int, end_time: int) -> float:
        """
        Sum actual commissions from userTrades endpoint between start_time and end_time.
        Returns positive fee cost in quote currency.
        """
        if not self.api_key or not self.api_secret:
            return 0.0

        symbol_pair = f"{symbol}USDT"
        endpoint = "/fapi/v1/userTrades"
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol_pair,
            "startTime": start_time,
            "endTime": end_time,
            "timestamp": timestamp,
            "recvWindow": 5000,
            "limit": 1000,
        }

        query = urllib.parse.urlencode(list(OrderedDict(params).items()))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", params={**params, "signature": signature}, headers=headers, timeout=10)
            resp.raise_for_status()
            trades = resp.json()
            total_fee = 0.0
            for t in trades:
                try:
                    total_fee += float(t.get("commission", 0) or 0)
                except Exception:
                    continue
            return total_fee
        except Exception as e:
            print(f"[Asterdex] Error fetching trade fees: {e}")
            return 0.0

    def get_fill_vwap(self, symbol: str, start_time: int, end_time: int) -> Dict[str, float]:
        """
        Return VWAP buy/sell prices and total filled qty for the window using userTrades.
        """
        summary = {"buy_qty": 0.0, "buy_vwap": 0.0, "sell_qty": 0.0, "sell_vwap": 0.0}
        if not self.api_key or not self.api_secret:
            return summary

        symbol_pair = f"{symbol}USDT"
        endpoint = "/fapi/v1/userTrades"
        timestamp = int(time.time() * 1000)
        params = {
            "symbol": symbol_pair,
            "startTime": start_time,
            "endTime": end_time,
            "timestamp": timestamp,
            "recvWindow": 5000,
            "limit": 1000,
        }

        query = urllib.parse.urlencode(list(OrderedDict(params).items()))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            resp = requests.get(f"{self.base_url}{endpoint}", params={**params, "signature": signature}, headers=headers, timeout=10)
            resp.raise_for_status()
            trades = resp.json()
            buy_notional = 0.0
            sell_notional = 0.0
            for t in trades:
                try:
                    qty = float(t.get("qty", 0) or 0)
                    px = float(t.get("price", 0) or 0)
                    is_buyer = bool(t.get("isBuyer"))
                    if qty <= 0 or px <= 0:
                        continue
                    if is_buyer:
                        summary["buy_qty"] += qty
                        buy_notional += qty * px
                    else:
                        summary["sell_qty"] += qty
                        sell_notional += qty * px
                except Exception:
                    continue
            if summary["buy_qty"] > 0:
                summary["buy_vwap"] = buy_notional / summary["buy_qty"]
            if summary["sell_qty"] > 0:
                summary["sell_vwap"] = sell_notional / summary["sell_qty"]
        except Exception as e:
            print(f"[Asterdex] Error fetching fills: {e}")
        return summary

    def _get_next_funding_time(self) -> int:
        """
        Calculate next 1-hour funding time (Asterdex is Hourly)
        """
        now = time.time()
        interval = 3600  # 1 hour
        # Determine next interval
        next_ts = ((int(now) // interval) + 1) * interval
    def _get_funding_interval_hours(self, symbol: str) -> int:
        """
        Determine funding interval (1, 4, or 8 hours) by checking history.
        Cached to avoid excessive API calls.
        """
        # Check cache first
        if symbol in self._interval_cache:
            return self._interval_cache[symbol]

        try:
            # Fetch last 2 funding rates
            pair = f"{symbol}USDT"
            url = f"{self.base_url}/fapi/v1/fundingRate"
            params = {"symbol": pair, "limit": 2}
            resp = requests.get(url, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            
            if len(data) >= 2:
                t1 = data[-1]['fundingTime']
                t2 = data[-2]['fundingTime']
                diff_ms = t1 - t2
                diff_hours = int(round(diff_ms / 1000 / 3600))
                # Validate common intervals
                if diff_hours in [1, 2, 4, 8]:
                    self._interval_cache[symbol] = diff_hours
                    self._save_cache() # Persist immediately
                    # print(f"[Asterdex] Detected {diff_hours}h interval for {symbol}")
                    return diff_hours
            
            # Default fallback if not enough history or error
            # Don't cache default unless sure? Better not cache defaults to retry next time?
            # actually if we cache 8, we avoid re-checking. But if it's an error, we shouldn't cache.
            # Only cache if data len >= 2.
            
            return 8 # Default but don't save to cache if it's a transient error

            
        except Exception as e:
            # print(f"[Asterdex] Interval check failed for {symbol}: {e}")
            return 8 # Default


    def test_connection(self) -> bool:
        """Simple liveness check using public endpoint"""
        try:
            resp = requests.get(f"{self.base_url}/fapi/v3/premiumIndex", timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[Asterdex] Connection test failed: {e}")
            return False
