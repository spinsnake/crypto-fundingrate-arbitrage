"""CCXT-based multi-account runner for Hyperliquid trading."""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from discord_webhook import DiscordWebhook

from config import get_config
from trading_core.adapters.vault_bot_adapter import SignalTweetAdapter
from trading_core.core.executor import FutureExecution
from trading_core.core.management.multi_account_manager import MultiAccountCcxtManager
from trading_core.core.management.order_management import CcxtOrderManagement
from trading_core.core.management.portfolio_management import CcxtPortfolioManagement
from trading_core.exchanges.hyperliquid.helper.map_symbol import map_k_symbol
from trading_core.log.trade_logging import log_trade_event
from trading_core.utils.trading_stats import upsert_crypto_trading_bot_stat
from utils.common.logger import logger


_MAX_ALLOWED_POSITIONS = 20


def execute_single_account_trading(account_id: str | None = None) -> str:
    """Execute trading operations for a single CCXT-backed account."""
    notification_message = f"Account {account_id or 'Default'}:\n"

    try:
        order_manager = CcxtOrderManagement(account_id=account_id)
        portfolio_manager = CcxtPortfolioManagement(account_id=account_id)

        holding_positions: List[Dict[str, Any]] = portfolio_manager.get_positions_summary()
        current_time_utc = datetime.now(timezone.utc)

        positions_closed = 0
        for pos in holding_positions:
            open_timestamp = pos.get("open_timestamp_utc")
            if open_timestamp and isinstance(open_timestamp, str):
                open_time_utc = datetime.fromisoformat(open_timestamp)
                if current_time_utc - open_time_utc > timedelta(hours=24):
                    order_manager.close_position_by_symbol(pos["symbol"])
                    notification_message += f"Closed old position: {pos['symbol']}\n"
                    positions_closed += 1

        adapter = SignalTweetAdapter(crypto_user_wallet_id=account_id)
        dynamic_usdc_amount = portfolio_manager.get_equity_based_usdc_amount(
            percentage=0.1,
            base_amount=1.0,
        )

        signals = adapter.get_signal(use_tp_sl=False, usdc_amount=dynamic_usdc_amount)
        for sig in signals:
            sig.symbol = map_k_symbol(sig.symbol)

        logger.info(
            "Prepared %s signals for account %s",
            len(signals),
            account_id or "default",
        )

        if not signals:
            notification_message += "No signals generated\n"
            return notification_message

        if positions_closed > 0:
            holding_positions = portfolio_manager.get_positions_summary()

        filtered_duplicates = portfolio_manager.drop_duplicate_signals(signals)
        filtered_position_in_port = portfolio_manager.filter_out_position_in_portfolio(
            filtered_duplicates,
            holding_positions,
        )

        signal_should_open, signal_should_close = portfolio_manager.categorize_signals(
            filtered_position_in_port,
            holding_positions,
        )

        for sig in signal_should_close:
            order_manager.close_position_by_symbol(sig.symbol)
            notification_message += f"Closed position: {sig.symbol}\n"

        positions_count = portfolio_manager.positions_count()
        available_slots = _MAX_ALLOWED_POSITIONS - positions_count

        if available_slots <= 0:
            notification_message += f"Portfolio full ({positions_count} positions)\n"
            signal_should_open = []
        elif len(signal_should_open) > available_slots:
            notification_message += f"Limited to {available_slots} new positions\n"
            signal_should_open = signal_should_open[:available_slots]

        executor = FutureExecution(account_id=account_id)
        account_failed = False
        trades_executed = 0

        for sig in signal_should_open:
            symbol = sig.symbol
            try:
                logger.info(
                    "Executing trade %s %s $%s",
                    sig.side.upper(),
                    symbol,
                    sig.target_usdc_amount,
                )
                result = executor.execute_trade(
                    symbol=symbol,
                    side=sig.side,
                    target_usdc_amount=sig.target_usdc_amount,
                )
                success = bool(isinstance(result, dict) and result.get("success"))
                log_trade_event(
                    source="ccxt_multi",
                    account_id=str(account_id or "default"),
                    wallet_id=None,
                    symbol=symbol,
                    side=sig.side,
                    base_size=(result or {}).get("calculated_size") if isinstance(result, dict) else None,
                    usdc_value=sig.target_usdc_amount,
                    price=(result or {}).get("execution_price") if isinstance(result, dict) else None,
                    leverage=None,
                    event="ccxt",
                    status="success" if success else "failed",
                )
                if success:
                    notification_message += f"{sig.side.upper()} {symbol}: ${sig.target_usdc_amount}\n"
                    trades_executed += 1
                else:
                    account_failed = True
                    err = (result or {}).get("error") if isinstance(result, dict) else "Order not confirmed"
                    notification_message += f"Failed {symbol}: {err}\n"
                    logger.error("Trade failed for %s: %s", symbol, err)
            except Exception as exc:  # pragma: no cover - defensive
                account_failed = True
                notification_message += f"Failed {symbol}: {exc}\n"
                logger.error("Trade execution error for %s: %s", symbol, exc)

        try:
            account_stat = portfolio_manager.get_account_stat(
                bot_name=f"multi_ccxt_bot_{account_id or 'default'}"
            )
            upsert_crypto_trading_bot_stat(account_stat)
            notification_message += f"Stats saved (Trades: {trades_executed})\n"
        except Exception as exc:
            logger.error("Could not save account stats for %s: %s", account_id, exc)
            notification_message += "Failed to save account stats\n"

        if account_failed:
            notification_message += "Account run completed with errors\n"

        return notification_message

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Trading execution failed for account %s: %s", account_id, exc)
        return f"Account {account_id or 'Default'} failed: {exc}"


# ... (rest of file continues with main_multi_account and dispatch routines)

def process_account_batch(account_id: str) -> tuple[str, str]:
    """Helper for concurrent execution in multi-account runs."""
    notification = execute_single_account_trading(account_id)
    return account_id, notification


def main_multi_account(batch_size: int = 3) -> None:
    """Run multi-account trading workflow using CCXT adapter."""
    logger.info("Starting multi-account trading run")

    account_manager = MultiAccountCcxtManager()
    accounts = account_manager.account_repository.get_all_accounts()
    if not accounts:
        logger.error("No trading accounts found. Please check database configuration.")
        return

    sorted_accounts = sorted(accounts, key=lambda account: account.priority)
    total_accounts = len(sorted_accounts)
    total_batches = (total_accounts + batch_size - 1) // batch_size

    logger.info(
        "Processing %s accounts in %s batches of %s",
        total_accounts,
        total_batches,
        batch_size,
    )

    all_notifications: list[str] = []

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, total_accounts)
        current_batch = sorted_accounts[start_idx:end_idx]

        logger.info(
            "Processing batch %s/%s with %s accounts",
            batch_num + 1,
            total_batches,
            len(current_batch),
        )

        with ThreadPoolExecutor(max_workers=len(current_batch)) as executor:
            futures = {
                executor.submit(process_account_batch, account.id): account.id
                for account in current_batch
            }

            batch_notifications: list[str] = []
            for future in as_completed(futures):
                account_id = futures[future]
                try:
                    _, notification = future.result()
                    batch_notifications.append(notification)
                    logger.info(
                        "Batch %s completed for account %s",
                        batch_num + 1,
                        account_id,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    error_msg = (
                        f"Account {account_id}:\nBatch processing error: {exc}\n"
                    )
                    batch_notifications.append(error_msg)
                    logger.error(
                        "Batch %s processing failed for account %s: %s",
                        batch_num + 1,
                        account_id,
                        exc,
                    )

            all_notifications.extend(batch_notifications)

        if batch_num < total_batches - 1:
            wait_time = 2
            logger.info("Waiting %s seconds before next batch", wait_time)
            time.sleep(wait_time)

    if all_notifications:
        combined_message = (
            "Multi-Account Trading Results (Sequential Batch Mode):\n\n"
            + "\n".join(all_notifications)
        )
        try:
            webhook = DiscordWebhook(
                url=get_config(["hyperliquid", "webhook_url"]),
                content=combined_message,
            )
            webhook.execute()
            logger.info("Discord notification sent successfully")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to send Discord notification: %s", exc)

    logger.info("Multi-account trading run completed successfully")


def main_single_account() -> None:
    """Run single-account trading workflow using CCXT adapter."""
    logger.info("Starting single-account trading run")

    account_manager = MultiAccountCcxtManager()
    available_accounts = account_manager.get_available_account_ids()
    if not available_accounts:
        logger.error("No trading accounts available. Please check configuration.")
        return

    repo = account_manager.account_repository
    all_accounts = repo.get_all_accounts()
    if not all_accounts:
        logger.error("No trading accounts found in repository")
        return

    sorted_accounts = sorted(all_accounts, key=lambda account: account.priority)
    default_account_id = sorted_accounts[0].id

    notification = execute_single_account_trading(default_account_id)
    if notification:
        try:
            webhook = DiscordWebhook(
                url=get_config(["hyperliquid", "webhook_url"]),
                content=notification,
            )
            webhook.execute()
            logger.info("Discord notification sent successfully")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to send Discord notification: %s", exc)

    logger.info("Single-account trading run completed successfully")


__all__ = [
    "execute_single_account_trading",
    "main_multi_account",
    "main_single_account",
]

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run CCXT-based Hyperliquid trading workflows.")
    parser.add_argument(
        "--mode",
        choices=["multi", "single"],
        default="multi",
        help="Run multi-account or single-account execution.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=3,
        help="Batch size for multi-account mode (default: 3)",
    )
    parser.add_argument(
        "--account-id",
        help="Account ID to run in single mode. If omitted, highest priority account is used.",
    )

    args = parser.parse_args()

    if args.mode == "multi":
        main_multi_account(batch_size=args.batch_size)
    else:
        if args.account_id:
            notification = execute_single_account_trading(args.account_id)
            if notification:
                print(notification)
        else:
            main_single_account()
