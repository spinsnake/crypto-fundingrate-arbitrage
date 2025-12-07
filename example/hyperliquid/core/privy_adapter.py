"""Hyperliquid Privy adapter consolidating account and portfolio helpers."""

from __future__ import annotations

from typing import Optional

from trading_core.core.privy.privy_executor import PrivyFutureExecution
from trading_core.core.privy.privy_order_management import PrivyOrderManagement
from trading_core.core.privy.privy_portfolio_management import PrivyPortfolioManagement
from trading_core.core.management.multi_account_privy_manager import MultiAccountPrivyManager


class HyperliquidPrivyAdapter:
    """Thin wrapper that exposes helper factories for Privy workflows."""

    def __init__(self, wallet_type: str = "copytrade") -> None:
        self.wallet_type = wallet_type

    def get_account_manager(self) -> MultiAccountPrivyManager:
        return MultiAccountPrivyManager(wallet_type=self.wallet_type)

    def create_portfolio_manager(self, account_id: str, attempt: int = 1) -> PrivyPortfolioManagement:
        return PrivyPortfolioManagement(account_id=account_id, attempt=attempt)

    def create_order_manager(self, account_id: str) -> PrivyOrderManagement:
        return PrivyOrderManagement(account_id=account_id)

    def create_executor(self, account_id: str) -> PrivyFutureExecution:
        return PrivyFutureExecution(account_id=account_id)


__all__ = ["HyperliquidPrivyAdapter"]

