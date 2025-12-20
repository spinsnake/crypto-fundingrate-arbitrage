import os
import requests
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, List
from dotenv import load_dotenv
from eth_account import Account
from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import HYPERLIQUID_API_URL, HYPERLIQUID_TAKER_FEE, DEFAULT_LEVERAGE

# Hyperliquid SDK (best effort import)
try:
    from hyperliquid.exchange import Exchange as HlExchange
    from hyperliquid.info import Info as HlInfo
    from hyperliquid.utils import constants as hl_constants
except Exception:
    HlExchange = None
    HlInfo = None
    hl_constants = None

load_dotenv()

class HyperliquidAdapter(ExchangeInterface):
    def __init__(self, private_key: str = ""):
        self.private_key = private_key or os.getenv("hyperliquid_private_key", "")
        self.wallet_address = os.getenv("hyperliquid_wallet_address", "")
        self.base_url = HYPERLIQUID_API_URL
        self.leverage = DEFAULT_LEVERAGE
        self._sz_decimals: Dict[str, int] = {}
        self._px_decimals: Dict[str, int] = {}

        if HlExchange and hl_constants and self.private_key:
            try:
                wallet_obj = Account.from_key(self.private_key)
                self._exchange = HlExchange(wallet_obj, hl_constants.MAINNET_API_URL, account_address=self.wallet_address)
                self._info = HlInfo(hl_constants.MAINNET_API_URL)
                self._load_meta()
            except Exception as e:
                print(f"[Hyperliquid] SDK init failed, using mock: {e}")
                self._exchange = None
                self._info = None
        else:
            self._exchange = None
            self._info = None

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
                    # Hyperliquid funding is HOURLY; normalize to 8h to match Asterdex
                    rate=float(ctx.get('funding', 0)) * 8,
                    mark_price=float(ctx.get('markPx', 0)),
                    source=self.get_name(),
                    timestamp=int(time.time() * 1000),
                    volume_24h=float(ctx.get('dayNtlVlm', 0)),
                    next_funding_time=next_hour,
                    is_active=True,
                    taker_fee=HYPERLIQUID_TAKER_FEE / 100,  # store as decimal fraction
                    funding_interval_hours=1,
                )
            return rates
        except Exception as e:
            print(f"[Hyperliquid] Error fetching rates: {e}")
            return {}

    def get_balance(self) -> float:
        if not self._info or not self.wallet_address:
            return 0.0
        try:
            state = self._info.user_state(self.wallet_address)
            return float(state.get("marginSummary", {}).get("accountValue", 0))
        except Exception:
            return 0.0

    def place_order(self, order: Order) -> Dict:
        # Use SDK if available; otherwise mock
        if not self._exchange:
            print(f"[Hyperliquid] Mock Order Placed: {order}")
            return {"status": "mock_success", "order_id": "mock_456"}
        


        is_buy = order.side.upper() == "BUY"
        tif = {"limit": {"tif": "Gtc"}} if order.type.upper() == "LIMIT" else {"market": {}}
        leverage = order.leverage or self.leverage
        qty = self._quantize_size(order.symbol, order.quantity)
        px = self._quantize_price(order.symbol, order.price) if order.price else None
        reduce_only = bool(getattr(order, "reduce_only", False))

        try:
            if hasattr(self._exchange, "update_leverage"):
                try:
                    self._exchange.update_leverage(leverage, order.symbol, True)
                except Exception as le:
                    print(f"[Hyperliquid] set leverage failed (ignored): {le}")

            resp = self._exchange.order(
                order.symbol,
                is_buy,
                qty,
                px if order.type.upper() == "LIMIT" else None,
                tif,
                reduce_only=reduce_only,
            )
            return resp
        except Exception as e:
            print(f"[Hyperliquid] Order failed: {e}")
            return {"status": "error", "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        if not self.wallet_address:
            print("[Hyperliquid] get_open_positions using mock (no wallet)")
            return []

        def _to_float(val) -> float:
            try:
                return float(val)
            except Exception:
                return 0.0

        def _parse_positions(state) -> List[Dict[str, Any]]:
            positions: List[Dict[str, Any]] = []
            for pos in state.get("assetPositions", []):
                p = pos.get("position", {}) or {}
                coin = p.get("coin") or pos.get("coin") or pos.get("asset")
                szi = p.get("szi", 0) or pos.get("szi", 0)
                sz = _to_float(szi)
                if not coin or sz == 0:
                    continue
                side = "LONG" if sz > 0 else "SHORT"
                entry_px = _to_float(p.get("entryPx") or pos.get("entryPx"))

                mark_px = _to_float(p.get("markPx") or pos.get("markPx"))
                if mark_px == 0.0:
                    pos_val = _to_float(p.get("positionValue") or pos.get("positionValue"))
                    if pos_val and abs(sz) > 0:
                        mark_px = pos_val / abs(sz)

                unrealized_pnl = _to_float(
                    p.get("unrealizedPnl")
                    or pos.get("unrealizedPnl")
                    or p.get("unrealizedPnlUsd")
                    or pos.get("unrealizedPnlUsd")
                )
                funding_since_open = _to_float(
                    (p.get("cumFunding") or {}).get("sinceOpen") or (pos.get("cumFunding") or {}).get("sinceOpen")
                )

                positions.append(
                    {
                        "symbol": coin,
                        "side": side,
                        "quantity": abs(sz),
                        "entry_price": entry_px,
                        "mark_price": mark_px,
                        "unrealized_pnl": unrealized_pnl,
                        "funding_since_open": funding_since_open,
                    }
                )
            return positions

        # Try SDK first
        if self._info:
            try:
                state = self._info.user_state(self.wallet_address)
                return _parse_positions(state)
            except Exception as e:
                print(f"[Hyperliquid] get_open_positions SDK failed: {e}")

        # Fallback HTTP
        try:
            payload = {"type": "clearinghouseState", "user": self.wallet_address}
            resp = requests.post(f"{self.base_url}/info", json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # Response may be list [state]; accept dict or first element
            state = data[0] if isinstance(data, list) else data
            return _parse_positions(state)
        except Exception as e:
            print(f"[Hyperliquid] get_open_positions HTTP failed: {e}")
            return []

    def _load_meta(self):
        try:
            meta = self._info.meta() if self._info else None
            if not meta:
                return
            universe = meta.get("universe", [])
            sz_dec = {}
            px_dec = {}
            for asset in universe:
                name = asset.get("name")
                if not name:
                    continue
                sz_dec[name] = int(asset.get("szDecimals", 0))
                px_dec[name] = int(asset.get("pxDecimals", 0)) if "pxDecimals" in asset else 4
            self._sz_decimals = sz_dec
            self._px_decimals = px_dec
        except Exception as e:
            print(f"[Hyperliquid] load meta failed: {e}")

    def _quantize_size(self, symbol: str, qty: float) -> float:
        dec = self._sz_decimals.get(symbol, 4)
        q = Decimal(str(qty)).quantize(Decimal(10) ** -dec, rounding=ROUND_DOWN)
        return float(q)

    def _quantize_price(self, symbol: str, price: float) -> float:
        dec = self._px_decimals.get(symbol, 4)
        p = Decimal(str(price)).quantize(Decimal(10) ** -dec, rounding=ROUND_DOWN)
        return float(p)

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

    def get_account_info(self) -> Dict[str, Any]:
        """
        Return user_state if SDK/info is available, else empty dict.
        """
        if self._info and self.wallet_address:
            try:
                return self._info.user_state(self.wallet_address)
            except Exception as e:
                print(f"[Hyperliquid] get_account_info failed: {e}")
        return {}

    def get_funding_history(self, symbol: str, start_time: int, end_time: int) -> float:
        if not self.wallet_address:
            print("[Hyperliquid] No wallet address for funding history")
            return 0.0

        endpoint = "/info"
        payload = {
            "type": "userFunding",
            "user": self.wallet_address,
            "startTime": start_time
        }
        
        try:
            response = requests.post(f"{self.base_url}{endpoint}", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # print(f"[HL DEBUG] Funding raw data count: {len(data)}") # Debug
            total_funding = 0.0
            for i, item in enumerate(data):
                # Expected item keys: 'coin', 'usdc', 'time'
                # HL response structure might be nested
                # Check for 'delta' key common in HL updates
                delta = item.get('delta', {})
                if delta:
                    item_coin = delta.get('coin')
                    amount = float(delta.get('usdc', 0) or delta.get('fundingPayment', 0)) # handle various formats
                else:
                    item_coin = item.get('coin')
                    amount = float(item.get('usdc', 0))

                ts = int(item.get('time', 0))
                
                if item_coin != symbol:
                    continue
                
                ts = int(item.get('time', 0))
                if ts < start_time or ts > end_time:
                    continue
                
                # Use the amount extracted from delta/item above
                total_funding += amount
            
            # print(f"[HL DEBUG] Total for {symbol}: {total_funding}")
            return total_funding
        except Exception as e:
            print(f"[Hyperliquid] Error fetching funding history: {e}")
            return 0.0

    def get_trade_fees(self, symbol: str, start_time: int, end_time: int) -> float:
        """
        Sum trade fees from userFills between start_time and end_time (ms). Returns positive fee cost.
        """
        if not self.wallet_address:
            return 0.0

        endpoint = "/info"
        payload = {"type": "userFills", "user": self.wallet_address, "startTime": start_time}
        try:
            response = requests.post(f"{self.base_url}{endpoint}", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            total_fee = 0.0
            for item in data:
                try:
                    ts = int(item.get("time", 0))
                    if ts < start_time or ts > end_time:
                        continue
                    coin = item.get("coin") or (item.get("delta", {}) or {}).get("coin")
                    if coin != symbol:
                        continue
                    fee_val = item.get("fee")
                    if fee_val is None:
                        fee_val = item.get("feePaid") or item.get("fee_paid")
                    if fee_val is None:
                        fee_val = (item.get("delta", {}) or {}).get("fee")
                    if fee_val is None:
                        continue
                    total_fee += abs(float(fee_val))
                except Exception:
                    continue
            return total_fee
        except Exception as e:
            print(f"[Hyperliquid] Error fetching trade fees: {e}")
            return 0.0

    def get_fill_vwap(self, symbol: str, start_time: int, end_time: int) -> Dict[str, float]:
        """
        Return VWAP buy/sell prices and total filled qty for the window using userFills.
        """
        summary = {"buy_qty": 0.0, "buy_vwap": 0.0, "sell_qty": 0.0, "sell_vwap": 0.0}
        if not self.wallet_address:
            return summary

        endpoint = "/info"
        payload = {"type": "userFills", "user": self.wallet_address, "startTime": start_time}
        try:
            response = requests.post(f"{self.base_url}{endpoint}", json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            buy_notional = 0.0
            sell_notional = 0.0
            for item in data:
                try:
                    ts = int(item.get("time", 0))
                    if ts < start_time or ts > end_time:
                        continue
                    coin = item.get("coin") or (item.get("delta", {}) or {}).get("coin")
                    if coin != symbol:
                        continue
                    side = item.get("side") or (item.get("delta", {}) or {}).get("side")
                    if not side:
                        # Infer side from sz sign if available
                        sz = item.get("sz") or (item.get("delta", {}) or {}).get("sz")
                        try:
                            if sz is not None and float(sz) < 0:
                                side = "sell"
                            elif sz is not None:
                                side = "buy"
                        except Exception:
                            pass
                    price = item.get("px") or item.get("price") or (item.get("delta", {}) or {}).get("px")
                    sz = item.get("sz") or (item.get("delta", {}) or {}).get("sz")
                    if price is None or sz is None:
                        continue
                    px = float(price)
                    qty = abs(float(sz))
                    if px <= 0 or qty <= 0:
                        continue
                    if str(side).lower() == "buy":
                        summary["buy_qty"] += qty
                        buy_notional += qty * px
                    elif str(side).lower() == "sell":
                        summary["sell_qty"] += qty
                        sell_notional += qty * px
                except Exception:
                    continue
            if summary["buy_qty"] > 0:
                summary["buy_vwap"] = buy_notional / summary["buy_qty"]
            if summary["sell_qty"] > 0:
                summary["sell_vwap"] = sell_notional / summary["sell_qty"]
        except Exception as e:
            print(f"[Hyperliquid] Error fetching fills: {e}")
        return summary
