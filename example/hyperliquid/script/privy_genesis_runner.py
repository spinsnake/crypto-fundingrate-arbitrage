"""Privy Genesis trading runner implemented under trading_core."""

from __future__ import annotations

import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from requests import exceptions as req_exc
from trading_core.adapters.vault_bot_adapter_genesis import SignalTweetAdapter
from trading_core.core.privy.privy_executor import PrivyFutureExecution
from trading_core.core.privy.privy_order_management import PrivyOrderManagement
from trading_core.core.privy.privy_portfolio_management import PrivyPortfolioManagement
from trading_core.core.management.multi_account_privy_manager import MultiAccountPrivyManager
from trading_core.log.trade_logging import log_trade_event
from trading_core.utils.trading_stats import upsert_crypto_trading_bot_stat
from trading_core.utils.discord.notifier import send_discord_notification
from trading_core.utils.proxy.proxy_pool import next_proxy, push_proxy_override, pop_proxy_override
from trading_core.websocket_utils.connection_manager import execute_with_websocket_retry
from utils.common.logger import logger

_MAX_ALLOWED_POSITIONS = 20
_DEFAULT_BATCH_SIZE = 4
_MAX_WORKERS_PER_BATCH = 1
_DEFAULT_USE_PROXY = False
_DEFAULT_PER_ACCOUNT_DELAY = 2.0
_DEFAULT_ACCOUNT_MIN_INTERVAL = 1.5
_execution_lock = threading.Lock()
_last_execution_ts = 0.0
# Limit multi-account runs to specific account IDs when debugging or hotfixing.
# Set to an empty set to run all accounts.
_TARGET_ACCOUNT_IDS: set[str] = {"4e879d8c-6258-41f4-891e-4d92fdc15939"}
_FINAL_SUMMARY_HEADER = "privy_genesis - FINAL SUMMARY - Multi-Account Privy Genesis Trading Completed"


def _throttle_account_execution(min_interval: float) -> None:
    """Ensure spacing between account executions across threads."""
    global _last_execution_ts
    with _execution_lock:
        now = time.time()
        wait_for = max(0.0, (_last_execution_ts + min_interval) - now)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_execution_ts = time.time()


def _format_duration(seconds: float) -> str:
    """Return human-friendly duration."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"


def _normalize_privy_symbol(symbol: str) -> str:
    """Strip "/USDC:USDC" suffix for Privy executor."""
    return symbol.split("/")[0] if "/" in symbol else symbol


def execute_single_privy_genesis_account_trading(account_id: str | None = None) -> str:
    """Execute trading operations for a single Privy Genesis account."""
    notification_message = f"Privy Genesis Account {account_id or 'Default'}:\n"

    try:
        order_manager = PrivyOrderManagement(account_id=account_id)
        portfolio_manager = PrivyPortfolioManagement(account_id=account_id)

        holding_positions = portfolio_manager.get_positions_summary()
        current_time_utc = datetime.now(timezone.utc)
        # print(holding_positions)
        # return   ""
        balance_data = portfolio_manager._get_balance()  # Uses cache to avoid repeated API calls
        account_value = float(balance_data.get("account_value", 0) or 0)
        if account_value <= 0:
            logger.warning(
                "Skip Privy Genesis trading for %s (account_value = %.2f)",
                account_id or "Default",
                account_value,
            )
            notification_message += "Skipped: balance is zero\n"
            return notification_message

        positions_closed = 0
        for pos in holding_positions:
            open_timestamp = pos.get("open_timestamp_utc")
            if open_timestamp and isinstance(open_timestamp, str):
                open_time_utc = datetime.fromisoformat(open_timestamp)
                if current_time_utc - open_time_utc > timedelta(hours=24):
                    symbol = _normalize_privy_symbol(pos["symbol"])
                    order_manager.close_position_by_symbol(symbol)
                    notification_message += f"Closed old position: {symbol}\n"
                    positions_closed += 1

        adapter = SignalTweetAdapter(crypto_user_wallet_id=account_id)
        dynamic_usdc_amount = portfolio_manager.get_equity_based_usdc_amount(
            percentage=0.1,
            base_amount=1.0,
        )

        signals = adapter.get_signal(use_tp_sl=False, usdc_amount=dynamic_usdc_amount)
        logger.info(
            "Retrieved %s signals for Privy Genesis account %s",
            len(signals),
            account_id or "Default",
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
            symbol = _normalize_privy_symbol(sig.symbol)
            order_manager.close_position_by_symbol(symbol)
            notification_message += f"Closed position: {symbol}\n"

        positions_count = portfolio_manager.positions_count()
        available_slots = _MAX_ALLOWED_POSITIONS - positions_count

        if available_slots <= 0:
            notification_message += f"Portfolio full ({positions_count} positions)\n"
            signal_should_open = []
        elif len(signal_should_open) > available_slots:
            notification_message += f"Limited to {available_slots} new positions\n"
            signal_should_open = signal_should_open[:available_slots]

        executor = PrivyFutureExecution(account_id=account_id)
        account_failed = False
        trades_executed = 0

        for sig in signal_should_open:
            symbol = _normalize_privy_symbol(sig.symbol)
            try:
                logger.info(
                    "Executing Privy Genesis trade %s %s $%s",
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
                    source="privy_genesis",
                    account_id=str(account_id or "default"),
                    wallet_id=None,
                    symbol=symbol,
                    side=sig.side,
                    base_size=(result or {}).get("calculated_size") if isinstance(result, dict) else None,
                    usdc_value=sig.target_usdc_amount,
                    price=(result or {}).get("execution_price") if isinstance(result, dict) else None,
                    leverage=None,
                    event="privy_genesis",
                    status="success" if success else "failed",
                )
                if success:
                    notification_message += f"{sig.side.upper()} {symbol}: ${sig.target_usdc_amount}\n"
                    trades_executed += 1
                else:
                    account_failed = True
                    err = (result or {}).get("error") if isinstance(result, dict) else "Order not confirmed"
                    notification_message += f"Failed {symbol}: {err}\n"
                    logger.error("Privy Genesis trade failed for %s: %s", symbol, err)
            except Exception as exc:  # pragma: no cover - defensive
                account_failed = True
                notification_message += f"Failed {symbol}: {exc}\n"
                logger.error("Privy Genesis trade error for %s: %s", symbol, exc)

        try:
            account_stat = portfolio_manager.get_account_stat(
                bot_name=f"multi_privy_genesis_bot_{account_id or 'default'}"
            )
            upsert_crypto_trading_bot_stat(account_stat)
            notification_message += f"Stats saved (Trades: {trades_executed})\n"
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Could not save Privy Genesis stats for %s: %s", account_id, exc)
            notification_message += "Failed to save account stats\n"

        if account_failed:
            notification_message += "Account run completed with errors\n"

        return notification_message

    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Privy Genesis execution failed for account %s: %s", account_id, exc)
        return f"Privy Genesis account {account_id or 'Default'} failed: {exc}"


def process_privy_genesis_account_batch(
    account_id: str,
    *,
    max_retries: int = 7,
    use_proxy: bool = _DEFAULT_USE_PROXY,
    per_account_delay: float = _DEFAULT_PER_ACCOUNT_DELAY,
    min_interval: float = _DEFAULT_ACCOUNT_MIN_INTERVAL,
) -> tuple[str, str]:
    """Helper for concurrent execution in multi-account runs."""
    proxy_applied = False
    proxy = next_proxy() if use_proxy else None
    if use_proxy and proxy:
        push_proxy_override(proxy)
        proxy_applied = True
    try:
        # Global throttle to keep IP-level rate within limits
        _throttle_account_execution(min_interval)

        pre_connection_delay = random.uniform(per_account_delay, per_account_delay + 0.7)
        logger.info(
            "Privy Genesis account %s: pre-connection stability delay %.1fs",
            account_id,
            pre_connection_delay,
        )
        time.sleep(pre_connection_delay)

        def _operation() -> str:
            return execute_single_privy_genesis_account_trading(account_id)

        def _run_with_fallback(use_proxy: bool = True) -> str:
            """Run trading operation with retry and optional proxy fallback."""
            try:
                return execute_with_websocket_retry(
                    account_id=account_id,
                    operation=_operation,
                    max_retries=max_retries,
                )
            except (req_exc.ProxyError, req_exc.SSLError, req_exc.ConnectionError, OSError) as exc:
                logger.warning(
                    "Proxy/connectivity issue for %s (use_proxy=%s): %s. Retrying without proxy.",
                    account_id,
                    use_proxy,
                    exc,
                )
                return execute_with_websocket_retry(
                    account_id=account_id,
                    operation=_operation,
                    max_retries=max_retries + 2,
                )

        notification = _run_with_fallback(use_proxy=proxy_applied)
        post_processing_delay = random.uniform(per_account_delay, per_account_delay + 0.6)
        logger.info(
            "Privy Genesis account %s: post-processing delay %.1fs",
            account_id,
            post_processing_delay,
        )
        time.sleep(post_processing_delay)

        return account_id, notification
    finally:
        if proxy_applied:
            pop_proxy_override()


def main_multi_privy_genesis_account(
    batch_size: int = _DEFAULT_BATCH_SIZE,
    max_workers: int = _MAX_WORKERS_PER_BATCH,
    use_proxy: bool = _DEFAULT_USE_PROXY,
    per_account_delay: float = _DEFAULT_PER_ACCOUNT_DELAY,
    min_interval: float = _DEFAULT_ACCOUNT_MIN_INTERVAL,
) -> None:
    """Multi-account Privy Genesis trading workflow."""
    start_time = time.time()
    logger.info("Starting multi-account Privy Genesis run")

    account_manager = MultiAccountPrivyManager(wallet_type="genesis")
    
    accounts = account_manager.get_all_accounts()
    
    if not accounts:
        logger.error("No Privy Genesis trading accounts available")
        return

    sorted_accounts = sorted(accounts, key=lambda account: account.priority)

    # run testing account only
    # if _TARGET_ACCOUNT_IDS:
    #     sorted_accounts = [account for account in sorted_accounts if account.id in _TARGET_ACCOUNT_IDS]
    #     if not sorted_accounts:
    #         logger.error("No Privy Genesis accounts matched TARGET_ACCOUNT_IDS filter")
    #         return


    total_accounts = len(sorted_accounts)
    total_batches = (total_accounts + batch_size - 1) // batch_size

    logger.info(
        "Processing %s Privy Genesis accounts in %s batches of %s",
        total_accounts,
        total_batches,
        batch_size,
    )

    all_notifications: list[str] = []
    failed_accounts: list[str] = []
    completed_accounts: list[str] = []

    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, total_accounts)
        current_batch = sorted_accounts[start_idx:end_idx]
        workers_for_batch = max(1, min(max_workers, len(current_batch))) if current_batch else 0

        logger.info(
            "Processing Privy Genesis batch %s/%s with %s accounts (max_workers=%s)",
            batch_num + 1,
            total_batches,
            len(current_batch),
            workers_for_batch,
        )

        if workers_for_batch == 0:
            logger.warning(
                "Skipping empty Privy Genesis batch %s/%s (no accounts in slice)",
                batch_num + 1,
                total_batches,
            )
            continue

        with ThreadPoolExecutor(max_workers=workers_for_batch) as executor:
            futures = {
                executor.submit(
                    process_privy_genesis_account_batch,
                    account.id,
                    max_retries=7,
                    use_proxy=use_proxy,
                    per_account_delay=per_account_delay,
                    min_interval=min_interval,
                ): account.id
                for account in current_batch
            }

            batch_notifications: list[str] = []
            for future in as_completed(futures):
                account_id = futures[future]
                try:
                    _, notification = future.result()
                    batch_notifications.append(notification)
                    notification_text = (notification or "").lower()
                    if (
                        "account run completed with errors" in notification_text
                        or "failed:" in notification_text
                    ):
                        failed_accounts.append(account_id)
                    else:
                        completed_accounts.append(account_id)
                    logger.info(
                        "Privy Genesis batch %s completed for account %s",
                        batch_num + 1,
                        account_id,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    error_msg = (
                        f"Privy Genesis account {account_id}:\nBatch processing error: {exc}\n"
                    )
                    batch_notifications.append(error_msg)
                    logger.error(
                        "Privy Genesis batch %s failed for account %s: %s",
                        batch_num + 1,
                        account_id,
                        exc,
                    )
                    failed_accounts.append(account_id)

            all_notifications.extend(batch_notifications)

        if batch_num < total_batches - 1:
            wait_time = 5 + random.uniform(0.0, 3.0)
            logger.info("Waiting %.1f seconds before next Privy Genesis batch", wait_time)
            time.sleep(wait_time)

    if all_notifications:
        combined_message = (
            "Multi-Account Privy Genesis Trading Results (Sequential Batch Mode):\n\n"
            + "\n".join(all_notifications)
        )
        send_discord_notification(combined_message)

    duration = time.time() - start_time
    time_summary = _format_duration(duration)
    success_count = len(completed_accounts)
    failed_count = len(failed_accounts)
    final_summary = (
        f"{_FINAL_SUMMARY_HEADER}\n"
        f"- Total Time: {time_summary} | Accounts: {total_accounts}\n"
        f"- Success: {success_count} | Failed: {failed_count}\n"
    )
    if failed_accounts:
        final_summary += f"Failed accounts: {', '.join(failed_accounts)}\n"

    send_discord_notification(final_summary)

    logger.info("Multi-account Privy Genesis run completed successfully")


def main_single_privy_genesis_account() -> None:
    """Single-account Privy Genesis trading workflow."""
    logger.info("Starting single-account Privy Genesis run")

    account_manager = MultiAccountPrivyManager(wallet_type="genesis")
    available_accounts = account_manager.get_available_account_ids()
    if not available_accounts:
        logger.error("No Privy Genesis trading accounts available")
        return

    default_exchange = account_manager.get_default_exchange()
    if not default_exchange:
        logger.error("No default Privy Genesis exchange available")
        return

    all_accounts = account_manager.get_all_accounts()
    if not all_accounts:
        logger.error("No Privy Genesis accounts found")
        return

    sorted_accounts = sorted(all_accounts, key=lambda account: account.priority)
    default_account_id = sorted_accounts[0].id

    notification = execute_single_privy_genesis_account_trading(default_account_id)
    if notification:
        send_discord_notification(notification)

    logger.info("Single-account Privy Genesis run completed successfully")


__all__ = [
    "execute_single_privy_genesis_account_trading",
    "main_multi_privy_genesis_account",
    "main_single_privy_genesis_account",
]

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Run Privy Genesis trading workflows.")
    parser.add_argument(
        "--mode",
        choices=["multi", "single"],
        default="multi",
        help="Run multi-account or single-account execution.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        help=f"Batch size for multi-account mode (default: {_DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=_MAX_WORKERS_PER_BATCH,
        help=f"Max concurrent workers per batch (default: {_MAX_WORKERS_PER_BATCH})",
    )
    parser.add_argument(
        "--use-proxy",
        action="store_true",
        default=_DEFAULT_USE_PROXY,
        help="Enable proxy usage from proxy pool (default: disabled)",
    )
    parser.add_argument(
        "--per-account-delay",
        type=float,
        default=_DEFAULT_PER_ACCOUNT_DELAY,
        help=f"Base delay (seconds) before/after each account to spread load (default: {_DEFAULT_PER_ACCOUNT_DELAY}s)",
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=_DEFAULT_ACCOUNT_MIN_INTERVAL,
        help=f"Global min interval between account executions to respect rate limits (default: {_DEFAULT_ACCOUNT_MIN_INTERVAL}s)",
    )

    args = parser.parse_args()

    if args.mode == "multi":
        main_multi_privy_genesis_account(
            batch_size=args.batch_size,
            max_workers=args.max_workers,
            use_proxy=args.use_proxy,
            per_account_delay=args.per_account_delay,
            min_interval=args.min_interval,
        )
    else:
        main_single_privy_genesis_account()
