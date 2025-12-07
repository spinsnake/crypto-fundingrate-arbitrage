from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Set

from trading_core.exchanges.asterdex.core.client import AsterdexFuturesClient


class AsterdexSymbolRegistry:
    """Cache of tradable Asterdex perpetual symbols refreshed from exchangeInfo."""

    def __init__(self, client: AsterdexFuturesClient, ttl_seconds: float = 300.0) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self._symbols: Set[str] = set()
        self._symbol_meta: Dict[str, Dict[str, Any]] = {}
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def is_symbol_supported(self, symbol: str) -> bool:
        normalized = self._normalize(symbol)
        if not normalized:
            return False

        now = time.time()
        if now >= self._expires_at:
            self._refresh()

        return normalized in self._symbols

    def _refresh(self) -> None:
        with self._lock:
            if time.time() < self._expires_at:
                return

            info = self.client.exchange_info()
            symbols = info.get("symbols", []) if isinstance(info, dict) else []

            refreshed: Set[str] = set()
            meta: Dict[str, Dict[str, Any]] = {}
            for item in symbols:
                if not isinstance(item, dict):
                    continue
                if item.get("contractType") != "PERPETUAL":
                    continue
                if item.get("status") != "TRADING":
                    continue
                raw_symbol = item.get("symbol")
                normalized = self._normalize(raw_symbol)
                if normalized:
                    refreshed.add(normalized)
                    meta[normalized] = item

            self._symbols = refreshed
            self._symbol_meta = meta
            self._expires_at = time.time() + self.ttl_seconds

    @staticmethod
    def _normalize(symbol: str | None) -> str:
        if not symbol:
            return ""
        cleaned = str(symbol).upper()
        if "/" in cleaned:
            cleaned = cleaned.split("/", 1)[0]
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[0]
        if cleaned.endswith("USDC:USDC"):
            cleaned = cleaned[: -len("USDC:USDC")] + "USDT"
        elif cleaned.endswith("/USDC"):
            cleaned = cleaned.replace("/USDC", "USDT")
        if not cleaned.endswith("USDT"):
            cleaned += "USDT"
        return cleaned

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        normalized = self._normalize(symbol)
        if not normalized:
            return None
        if time.time() >= self._expires_at:
            self._refresh()
        return self._symbol_meta.get(normalized)


__all__ = ["AsterdexSymbolRegistry"]
