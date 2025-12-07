"""
Asterdex adapter that provides helper factories and credential management.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


from trading_core.adapters.signals.kol.signal_adapter import (
    KolSignalAdapter,
    KolSignal,
)
from trading_core.core.wallet_model import CryptoAccountCex
from trading_core.core.cex_account_manager import CexAccountManager as AsterdexAccountManager
from trading_core.exchanges.asterdex.core.client import AsterdexFuturesClient
from trading_core.exchanges.asterdex.core.executor import AsterdexFutureExecution
from trading_core.exchanges.asterdex.core.order_management import AsterdexOrderManagement
from trading_core.exchanges.asterdex.core.portfolio_management import AsterdexPortfolioManagement
from trading_core.exchanges.asterdex.core.symbol_registry import AsterdexSymbolRegistry
from trading_core.log.logger import logger
from trading_core.utils.proxy import ProxySettings


class AsterdexAdapter:
    """Wrapper exposing helper factories similar to HyperliquidPrivyAdapter."""

    def __init__(
        self,
        *,
        account_id: str,
        wallet_type: str = "copytrade",
        include_deleted: bool = False,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = "https://fapi.asterdex.com",
        accounts: Optional[Sequence[Dict[str, Any]]] = None,
        recv_window: int = 5_000,
        default_notional: float = 15.0,
    ) -> None:
        self.wallet_type = wallet_type
        self.account_id = account_id
        self.accounts_config: List[Dict[str, Any]] = list(accounts or [])

        self._base_url = base_url.rstrip("/")
        self._recv_window = recv_window
        self.default_notional = float(default_notional)

        self._account_manager = AsterdexAccountManager(
            exchange="asterdex",
        )
        self.account_setting = self._account_manager.get_account_by_id(
            account_id,
            include_deleted=include_deleted,
        )
        if self.account_setting is None:
            raise RuntimeError(f"AsterdexAdapter: account not found for id={account_id}")

        self._default_api_key = api_key or self.account_setting.api_key
        self._default_api_secret = api_secret or self.account_setting.api_secret
        if not self._default_api_key or not self._default_api_secret:
            raise ValueError(f"AsterdexAdapter: missing credentials for account {account_id}")

        self.client: AsterdexFuturesClient | None = None
        self._symbol_registry: AsterdexSymbolRegistry | None = None
        self._signal_adapter = KolSignalAdapter(crypto_user_wallet_id=account_id)

        self._configure_client(self._default_api_key, self._default_api_secret, account_id)

        logger.info("AsterdexAdapter initialised for account_id=%s", account_id)


    def find_stale_triggers(self) -> dict:
        portfolio_manager = self.create_portfolio_manager(self.account_id, attempt=1)
        open_positions = portfolio_manager.filter_open_positions(
            portfolio_manager.get_positions_summary()
        )
        active_symbols = {
            str(pos.get("symbol", "")).upper().split("/")[0]
            for pos in open_positions if pos.get("symbol")
        }

        orders = self.client.open_orders()  # ต้องมีเมธอดนี้ใน client
        stale = {}
        trigger_orders = []
        for order in orders or []:
            order_type = str(order.get("type", "")).upper()
            reduce_only = str(order.get("reduceOnly", "")).lower() == "true"
            if order_type not in {"TAKE_PROFIT_MARKET", "STOP_MARKET"} or not reduce_only:
                continue

            symbol = str(order.get("symbol", "")).upper()
            base_symbol = symbol.split("/")[0]
            trigger_orders.append(order)
            if base_symbol not in active_symbols:
                stale.setdefault(symbol, []).append(order)

        return {
            "active_position_symbols": sorted(active_symbols),
            "trigger_order_count": len(trigger_orders),
            "stale_triggers_by_symbol": stale,
            "has_stale_triggers": bool(stale),
        }

    def get_setting(self)->CryptoAccountCex:
        return self.account_setting
    
    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    def fetch_signals(
        self,
        *,
        use_market_filter: bool = True,
        use_tp_sl: bool = False,
        usdc_amount: Optional[float] = None,
        timeframe: str = "4h",
    ) -> List[KolSignal]:
        """Retrieve downstream KOL signals ready for execution."""
        notional = usdc_amount or self.default_notional
        return self._signal_adapter.get_signals(
            use_market_filter=use_market_filter,
            usdc_amount=notional,
            timeframe=timeframe,
        )

    # ------------------------------------------------------------------
    # Helper factories
    # ------------------------------------------------------------------


    

    def create_portfolio_manager(self, account_id: str, attempt: int = 1) -> AsterdexPortfolioManagement:
        self._ensure_client_configured()
        wallet_created_at = self.account_setting.created_at if self.account_setting else None
        return AsterdexPortfolioManagement(
            self.client,
            account_id,
            attempt=attempt,
            wallet_created_at=wallet_created_at,
        )  # type: ignore[arg-type]

    def create_order_manager(self, account_id: str) -> AsterdexOrderManagement:
        self._ensure_client_configured()
        return AsterdexOrderManagement(self.client, account_id)  # type: ignore[arg-type]

    def create_executor(self, account_id: str) -> AsterdexFutureExecution:
        self._ensure_client_configured()
        return AsterdexFutureExecution(self.client, account_id, symbol_registry=self._symbol_registry)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Proxy helpers
    # ------------------------------------------------------------------
    def apply_proxy(self, proxy: ProxySettings) -> None:
        """Configure the underlying requests session to use the supplied proxy."""
        self._ensure_client_configured()
        session = self.client.session  # type: ignore[assignment]
        session.trust_env = False
        session.proxies.clear()
        if proxy and proxy.is_configured:
            session.proxies.update(proxy.as_requests_proxies())
            logger.info("AsterdexAdapter: proxy enabled %s:%s", proxy.host, proxy.port)
        else:
            logger.info("AsterdexAdapter: using direct connection (no proxy)")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _configure_client(
        self,
        api_key: str,
        api_secret: str,
        account_id: Optional[str],
    ) -> None:
        self.client = AsterdexFuturesClient(
            api_key=api_key,
            api_secret=api_secret,
            base_url=self._base_url,
            recv_window=self._recv_window,
        )
        self._symbol_registry = AsterdexSymbolRegistry(self.client)
        self._signal_adapter = KolSignalAdapter(crypto_user_wallet_id=account_id)

    def _ensure_client_configured(self) -> None:
        if self.client is None or self._symbol_registry is None:
            raise RuntimeError("Asterdex client not configured; call use_account() first")


__all__ = ["AsterdexAdapter"]
