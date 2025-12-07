"""
HTTP client for interacting with the Asterdex perpetual futures REST API.

This keeps signing and request plumbing together so higher-level adapters
can focus on trading logic.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from requests import Response, Session


class AsterdexFuturesClient:
    """Lightweight REST client covering the core Asterdex endpoints we need."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = "https://fapi.asterdex.com",
        recv_window: int = 5_000,
        session: Optional[Session] = None,
    ) -> None:
        if not api_key:
            raise ValueError("AsterdexFuturesClient requires a non-empty api_key")
        if not api_secret:
            raise ValueError("AsterdexFuturesClient requires a non-empty api_secret")
        if not isinstance(api_secret, str):
            raise TypeError("api_secret must be a string")

        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/")
        self.recv_window = recv_window
        self.session = session or requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(params)
        payload.setdefault("timestamp", int(time.time() * 1000))
        payload.setdefault("recvWindow", self.recv_window)
        # Preserve insertion order when constructing the query string
        items = list(payload.items())
        query = urlencode(items)
        signature = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        timeout: int = 15,
    ) -> Response:
        params = params or {}
        request_params = self._sign(params) if signed else params
        url = f"{self.base_url}{path}"
        if method.upper() == "GET":
            response = self.session.get(url, params=request_params, timeout=timeout)
        else:
            response = self.session.request(method.upper(), url, data=request_params, timeout=timeout)
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Public REST wrappers
    # ------------------------------------------------------------------
    def ping(self) -> Dict[str, Any]:
        return self._request("GET", "/fapi/v1/ping").json()

    def exchange_info(self) -> Dict[str, Any]:
        return self._request("GET", "/fapi/v1/exchangeInfo").json()

    def mark_price(self, symbol: Optional[str] = None) -> Dict[str, Any] | list[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v1/premiumIndex", params=params).json()

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/fapi/v1/order", params=payload, signed=True).json()

    def cancel_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("DELETE", "/fapi/v1/order", params=payload, signed=True).json()

    def cancel_all(self, symbol: str) -> Dict[str, Any]:
        return self._request("DELETE", "/fapi/v1/allOpenOrders", params={"symbol": symbol}, signed=True).json()
    def open_orders(self, symbol: Optional[str] = None) -> list[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v1/openOrders", params=params, signed=True).json()

    def account(self) -> Dict[str, Any]:
        return self._request("GET", "/fapi/v4/account", signed=True).json()

    def futures_balance(self) -> list[Dict[str, Any]]:
        return self._request("GET", "/fapi/v2/balance", signed=True).json()

    def position_risk(self, symbol: Optional[str] = None) -> list[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/fapi/v2/positionRisk", params=params, signed=True).json()

    def income_history(self, *, symbol: Optional[str] = None, income_type: Optional[str] = None) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if income_type:
            params["incomeType"] = income_type
        return self._request("GET", "/fapi/v1/income", params=params, signed=True).json()

    def user_trades(
        self,
        *,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        from_id: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        params: Dict[str, Any] = {"symbol": symbol}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        if from_id is not None:
            params["fromId"] = int(from_id)
        if limit is not None:
            params["limit"] = int(limit)
        return self._request("GET", "/fapi/v1/userTrades", params=params, signed=True).json()
