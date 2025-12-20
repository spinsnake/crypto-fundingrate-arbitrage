import ast
import json
import os
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, List, Optional

import requests
from dotenv import load_dotenv
from eth_account import Account

try:
    import lighter
    from lighter.signer_client import SignerClient
except Exception:
    lighter = None
    SignerClient = None

from ..core.interfaces import ExchangeInterface
from ..core.models import FundingRate, Order
from ..config import LIGHTER_API_URL, LIGHTER_TAKER_FEE, DEFAULT_LEVERAGE

load_dotenv()


class LighterAdapter(ExchangeInterface):
    def __init__(self, account_index: str = ""):
        self.base_url = LIGHTER_API_URL
        self.account_index = self._clean_env_value(
            account_index
            or os.getenv("lighter_account_index", "")
            or os.getenv("LIGHTER_ACCOUNT_INDEX", "")
        )
        self.private_key = self._clean_env_value(
            os.getenv("lighter_private_key", "") or os.getenv("LIGHTER_PRIVATE_KEY", "")
        )
        self.wallet_address = self._clean_env_value(
            os.getenv("lighter_wallet_address", "") or os.getenv("LIGHTER_WALLET_ADDRESS", "")
        )
        self.leverage = DEFAULT_LEVERAGE
        self.api_key_index = self._load_api_key_index()
        self.api_private_keys = self._load_api_private_keys()
        self._symbol_details: Dict[str, Dict[str, Any]] = {}
        self._market_id_to_symbol: Dict[int, str] = {}
        self._last_details_ts = 0.0
        self._account_index_cached: Optional[int] = None
        self._account_index_checked = False
        self._signer_client = None

    def get_name(self) -> str:
        return "Lighter"

    def _clean_env_value(self, val: str) -> str:
        return str(val or "").strip().strip('"').strip("'")

    def _to_float(self, val: Any, default: float = 0.0) -> float:
        try:
            return float(val)
        except Exception:
            return default

    def _to_int(self, val: Any, default: int = 0) -> int:
        try:
            return int(val)
        except Exception:
            return default

    def _to_scaled_int(self, val: float, decimals: int) -> int:
        scale = Decimal("10") ** decimals
        return int((Decimal(str(val)) * scale).to_integral_value(rounding=ROUND_DOWN))

    def _load_api_key_index(self) -> Optional[int]:
        raw = self._clean_env_value(
            os.getenv("lighter_api_key_index", "") or os.getenv("LIGHTER_API_KEY_INDEX", "")
        )
        if not raw:
            return None
        try:
            return int(raw)
        except Exception:
            return None

    def _parse_api_private_keys(self, raw: str) -> Dict[int, str]:
        cleaned = raw.strip()
        if not cleaned:
            return {}
        data = None
        try:
            data = ast.literal_eval(cleaned)
        except Exception:
            try:
                data = json.loads(cleaned)
            except Exception:
                return {}
        if not isinstance(data, dict):
            return {}
        out: Dict[int, str] = {}
        for key, value in data.items():
            try:
                idx = int(key)
            except Exception:
                continue
            key_str = self._clean_env_value(str(value))
            if key_str:
                out[idx] = key_str
        return out

    def _load_api_private_keys(self) -> Dict[int, str]:
        raw = self._clean_env_value(
            os.getenv("lighter_api_private_keys", "") or os.getenv("LIGHTER_API_PRIVATE_KEYS", "")
        )
        if raw:
            parsed = self._parse_api_private_keys(raw)
            if parsed:
                return parsed
        single_key = self._clean_env_value(
            os.getenv("lighter_api_private_key", "") or os.getenv("LIGHTER_API_PRIVATE_KEY", "")
        )
        if single_key:
            idx = self.api_key_index if self.api_key_index is not None else 0
            return {idx: single_key}
        return {}

    def _account_index_int(self) -> Optional[int]:
        if self.account_index:
            try:
                return int(self.account_index)
            except Exception:
                return None
        if self._account_index_cached is not None:
            return self._account_index_cached
        if not self._account_index_checked:
            self._account_index_checked = True
            resolved = self._resolve_account_index()
            if resolved is not None:
                self._account_index_cached = resolved
                self.account_index = str(resolved)
                return resolved
        return None

    def _resolve_account_index(self) -> Optional[int]:
        l1_address = self._resolve_wallet_address()
        if not l1_address:
            print("[Lighter] Missing wallet address/private key for account lookup")
            return None
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/accountsByL1Address",
                params={"l1_address": l1_address},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            sub_accounts = data.get("sub_accounts") or []
            indices = []
            for acct in sub_accounts:
                idx = acct.get("index")
                if idx is not None:
                    indices.append(int(idx))
            if not indices:
                print(f"[Lighter] No account index found for {l1_address}")
                return None
            return sorted(indices)[0]
        except Exception as e:
            print(f"[Lighter] Account index lookup failed: {e}")
            return None

    def _resolve_wallet_address(self) -> str:
        if self.wallet_address:
            return self.wallet_address
        if not self.private_key:
            return ""
        try:
            acct = Account.from_key(self.private_key)
            return acct.address
        except Exception as e:
            print(f"[Lighter] Private key parse failed: {e}")
            return ""

    def _refresh_market_details(self, force: bool = False) -> None:
        if not force and self._symbol_details and (time.time() - self._last_details_ts) < 60:
            return
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/orderBookDetails",
                params={"filter": "perp"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            details = data.get("order_book_details") or []
            symbol_details: Dict[str, Dict[str, Any]] = {}
            id_map: Dict[int, str] = {}
            for item in details:
                symbol = item.get("symbol")
                market_id = item.get("market_id")
                if not symbol or market_id is None:
                    continue
                taker_fee_pct = self._to_float(item.get("taker_fee"), None)
                symbol_details[symbol] = {
                    "market_id": int(market_id),
                    "status": item.get("status", ""),
                    "last_trade_price": self._to_float(item.get("last_trade_price", 0.0)),
                    "daily_quote_token_volume": self._to_float(item.get("daily_quote_token_volume", 0.0)),
                    "min_base_amount": self._to_float(item.get("min_base_amount", 0.0)),
                    "min_quote_amount": self._to_float(item.get("min_quote_amount", 0.0)),
                    "supported_size_decimals": self._to_int(
                        item.get("supported_size_decimals", item.get("size_decimals", 0))
                    ),
                    "supported_price_decimals": self._to_int(
                        item.get("supported_price_decimals", item.get("price_decimals", 0))
                    ),
                    "taker_fee": (taker_fee_pct / 100) if taker_fee_pct is not None else None,
                }
                id_map[int(market_id)] = symbol
            self._symbol_details = symbol_details
            self._market_id_to_symbol = id_map
            self._last_details_ts = time.time()
        except Exception as e:
            print(f"[Lighter] Error fetching order book details: {e}")

    def _get_symbol_detail(self, symbol: str) -> Dict[str, Any]:
        self._refresh_market_details()
        return self._symbol_details.get(symbol, {})

    def _get_market_id(self, symbol: str) -> Optional[int]:
        detail = self._get_symbol_detail(symbol)
        market_id = detail.get("market_id")
        return int(market_id) if market_id is not None else None

    def get_all_funding_rates(self) -> Dict[str, FundingRate]:
        try:
            resp = requests.get(f"{self.base_url}/api/v1/funding-rates", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("funding_rates") or []
        except Exception as e:
            print(f"[Lighter] Error fetching funding rates: {e}")
            return {}

        self._refresh_market_details()
        next_hour = (int(time.time() / 3600) + 1) * 3600 * 1000
        rates: Dict[str, FundingRate] = {}
        for item in items:
            if item.get("exchange") != "lighter":
                continue
            symbol = item.get("symbol")
            if not symbol:
                continue
            detail = self._symbol_details.get(symbol, {})
            rate_raw = self._to_float(item.get("rate", 0.0))
            taker_fee = detail.get("taker_fee")
            if taker_fee is None:
                taker_fee = LIGHTER_TAKER_FEE / 100

            rates[symbol] = FundingRate(
                symbol=symbol,
                # Lighter funding is hourly; normalize to 8h like other adapters
                rate=rate_raw * 8,
                mark_price=self._to_float(detail.get("last_trade_price", 0.0)),
                source=self.get_name(),
                timestamp=int(time.time() * 1000),
                volume_24h=self._to_float(detail.get("daily_quote_token_volume", 0.0)),
                next_funding_time=next_hour,
                is_active=str(detail.get("status", "")).lower() == "active",
                taker_fee=taker_fee,
            )
        return rates

    def get_balance(self) -> float:
        account_index = self._account_index_int()
        if account_index is None:
            print("[Lighter] get_balance missing account_index")
            return 0.0
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/account",
                params={"by": "index", "value": str(account_index)},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("accounts") or []
            if not accounts:
                return 0.0
            acct = accounts[0]
            for key in ("total_asset_value", "cross_asset_value", "collateral", "available_balance"):
                val = self._to_float(acct.get(key), None)
                if val is not None:
                    return val
            return 0.0
        except Exception as e:
            print(f"[Lighter] get_balance failed: {e}")
            return 0.0

    def place_order(self, order: Order) -> Dict:
        if SignerClient is None:
            print("[Lighter] lighter-python not installed; cannot send tx")
            return {"status": "error", "error": "lighter_sdk_missing"}

        account_index = self._account_index_int()
        if account_index is None:
            print("[Lighter] place_order missing account_index")
            return {"status": "error", "error": "missing_account_index"}

        if not self.api_private_keys:
            print("[Lighter] place_order missing api private key(s)")
            return {"status": "error", "error": "missing_api_private_key"}

        if self._signer_client is None:
            try:
                self._signer_client = SignerClient(
                    url=self.base_url,
                    account_index=account_index,
                    api_private_keys=self.api_private_keys,
                )
                err = self._signer_client.check_client()
                if err:
                    print(f"[Lighter] check_client failed: {err}")
                    self._signer_client = None
                    return {"status": "error", "error": f"check_client_failed:{err}"}
            except Exception as e:
                print(f"[Lighter] Signer init failed: {e}")
                self._signer_client = None
                return {"status": "error", "error": str(e)}

        detail = self._get_symbol_detail(order.symbol)
        market_id = detail.get("market_id")
        if market_id is None:
            return {"status": "error", "error": "unknown_symbol"}

        size_decimals = self._to_int(detail.get("supported_size_decimals", 0))
        price_decimals = self._to_int(detail.get("supported_price_decimals", 0))
        min_base = self._to_float(detail.get("min_base_amount", 0.0))
        min_quote = self._to_float(detail.get("min_quote_amount", 0.0))

        qty = self._to_scaled_int(order.quantity, size_decimals)
        qty_float = float(Decimal(qty) / (Decimal("10") ** size_decimals)) if size_decimals else float(qty)
        if qty <= 0:
            return {"status": "error", "error": "invalid_quantity"}

        if min_base and qty_float < min_base:
            return {"status": "error", "error": f"quantity_below_min_base:{min_base}"}

        price = order.price or self._to_float(detail.get("last_trade_price", 0.0))
        if price <= 0:
            return {"status": "error", "error": "invalid_price"}

        px = self._to_scaled_int(price, price_decimals)
        px_float = float(Decimal(px) / (Decimal("10") ** price_decimals)) if price_decimals else float(px)
        if min_quote and (qty_float * px_float) < min_quote:
            return {"status": "error", "error": f"notional_below_min_quote:{min_quote}"}
        is_ask = order.side.upper() == "SELL"

        order_type = self._signer_client.ORDER_TYPE_LIMIT
        time_in_force = self._signer_client.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME
        order_expiry = self._signer_client.DEFAULT_28_DAY_ORDER_EXPIRY
        if order.type and order.type.upper() == "MARKET":
            order_type = self._signer_client.ORDER_TYPE_MARKET
            time_in_force = self._signer_client.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL
            order_expiry = self._signer_client.DEFAULT_IOC_EXPIRY

        client_order_index = int(time.time() * 1000)
        try:
            if self.api_key_index is not None:
                if self.api_key_index not in self.api_private_keys:
                    return {"status": "error", "error": "api_key_index_not_configured"}
                api_key_index, nonce = self._signer_client.nonce_manager.next_nonce(self.api_key_index)
            else:
                api_key_index, nonce = self._signer_client.nonce_manager.next_nonce()

            tx_type, tx_info, tx_hash, err = self._signer_client.sign_create_order(
                market_id,
                client_order_index,
                qty,
                px,
                int(is_ask),
                order_type,
                time_in_force,
                False,
                self._signer_client.NIL_TRIGGER_PRICE,
                order_expiry,
                nonce=nonce,
                api_key_index=api_key_index,
            )
            if err:
                return {"status": "error", "error": err}

            resp = requests.post(
                f"{self.base_url}/api/v1/sendTx",
                files={
                    "tx_type": (None, str(tx_type)),
                    "tx_info": (None, tx_info),
                    "price_protection": (None, "true"),
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")
            status = "ok" if code == 200 else "error"
            return {
                "status": status,
                "tx_hash": data.get("tx_hash") or tx_hash,
                "response": data,
                "client_order_index": client_order_index,
            }
        except Exception as e:
            print(f"[Lighter] Order failed: {e}")
            return {"status": "error", "error": str(e)}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        account_index = self._account_index_int()
        if account_index is None:
            print("[Lighter] get_open_positions missing account_index")
            return []
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/account",
                params={"by": "index", "value": str(account_index)},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            accounts = data.get("accounts") or []
            if not accounts:
                return []
            acct = accounts[0]
            positions = []
            for p in acct.get("positions", []) or []:
                symbol = p.get("symbol")
                if not symbol:
                    continue
                size = self._to_float(p.get("position", 0.0))
                if size == 0:
                    continue
                sign = int(p.get("sign", 0) or 0)
                side = "LONG" if sign >= 0 else "SHORT"
                detail = self._get_symbol_detail(symbol)
                positions.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "quantity": abs(size),
                        "entry_price": self._to_float(p.get("avg_entry_price", 0.0)),
                        "mark_price": self._to_float(detail.get("last_trade_price", 0.0)),
                        "unrealized_pnl": self._to_float(p.get("unrealized_pnl", 0.0)),
                    }
                )
            return positions
        except Exception as e:
            print(f"[Lighter] get_open_positions failed: {e}")
            return []

    def get_top_of_book(self, symbol: str) -> Dict[str, float]:
        market_id = self._get_market_id(symbol)
        if market_id is None:
            return {"bid": 0.0, "ask": 0.0}
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/orderBookOrders",
                params={"market_id": market_id, "limit": 5},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
            asks = data.get("asks") or []
            bids = data.get("bids") or []
            best_ask = self._to_float(asks[0].get("price")) if asks else 0.0
            best_bid = self._to_float(bids[0].get("price")) if bids else 0.0
            if best_ask == 0.0 and best_bid == 0.0:
                last_px = self._to_float(self._get_symbol_detail(symbol).get("last_trade_price", 0.0))
                return {"bid": last_px, "ask": last_px}
            return {"bid": best_bid, "ask": best_ask}
        except Exception:
            last_px = self._to_float(self._get_symbol_detail(symbol).get("last_trade_price", 0.0))
            return {"bid": last_px, "ask": last_px}

    def is_symbol_active(self, symbol: str) -> bool:
        detail = self._get_symbol_detail(symbol)
        return str(detail.get("status", "")).lower() == "active"

    def get_funding_history(self, symbol: str, start_time: int, end_time: int) -> float:
        account_index = self._account_index_int()
        if account_index is None:
            return 0.0
        market_id = self._get_market_id(symbol)
        if market_id is None:
            return 0.0

        total = 0.0
        cursor = None
        for _ in range(5):
            params = {"account_index": account_index, "limit": 200, "market_id": market_id}
            if cursor:
                params["cursor"] = cursor
            try:
                resp = requests.get(
                    f"{self.base_url}/api/v1/positionFunding",
                    params=params,
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                entries = data.get("position_fundings") or []
                for entry in entries:
                    ts = int(entry.get("timestamp", 0) or 0)
                    if ts and ts < 1_000_000_000_000:
                        ts *= 1000
                    if ts < start_time or ts > end_time:
                        continue
                    total += self._to_float(entry.get("change", 0.0))
                cursor = data.get("next_cursor")
                if not cursor or not entries:
                    break
            except Exception as e:
                print(f"[Lighter] Error fetching funding history: {e}")
                break
        return total

    def get_trade_fees(self, symbol: str, start_time: int, end_time: int) -> float:
        # Fee history requires authenticated trade data; return 0 for now.
        return 0.0

    def get_fill_vwap(self, symbol: str, start_time: int, end_time: int) -> Dict[str, float]:
        # Placeholder for later fill aggregation.
        return {"buy_qty": 0.0, "buy_vwap": 0.0, "sell_qty": 0.0, "sell_vwap": 0.0}

    def test_connection(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/info", timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            print(f"[Lighter] Connection test failed: {e}")
            return False
