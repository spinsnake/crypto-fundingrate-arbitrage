"""Hyperliquid Privy runner implemented as a reusable class."""

from __future__ import annotations
import math
import asyncio
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from trading_core.core.privy.privy_native_integration import UnsupportedHyperliquidSymbol
from trading_core.exchanges.hyperliquid.helper.map_symbol import map_k_symbol
from trading_core.log.trade_logging import log_trade_event
from trading_core.websocket_utils.connection_manager import execute_with_websocket_retry
from trading_core.websocket_utils.websocket_safeguard import sdk_safe_execution
from utils.common.logger import logger

from trading_core.adapters.signals.kol.signal_adapter import (
    KolSignalAdapter,
    KolSignal,
)
from trading_core.core.base import ExchangeRunner
from trading_core.core.risk import RiskController
from trading_core.exchanges.hyperliquid.core.privy_adapter import HyperliquidPrivyAdapter
from trading_core.utils.discord.notifier import send_discord_notification


_MAX_ALLOWED_POSITIONS = 20
_MAX_WORKER_GROUPS = 16
_MIN_ACCOUNTS_PER_GROUP = 50
_FINAL_SUMMARY_HEADER = "privy_multithread_cached - FINAL SUMMARY - Multi-Account Privy Trading Completed"
_FINAL_SINGLE_SUMMARY_HEADER = "privy_multithread_cached - FINAL SUMMARY - Single-Account Privy Trading Completed"


class HyperliquidPrivyRunner(ExchangeRunner):
    """High-level runner that encapsulates the old privy scripts."""

    name = "hyperliquid"
    supported_modes = ("privy",)

    def __init__(
        self,
        wallet_type: str = "copytrade",
        max_allowed_positions: int = _MAX_ALLOWED_POSITIONS,
        risk_controller: RiskController | None = None,
    ) -> None:
        self.wallet_type = wallet_type
        self.max_allowed_positions = max_allowed_positions
        self.risk_controller = risk_controller or RiskController()
        self._adapter = HyperliquidPrivyAdapter(wallet_type=wallet_type)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run_multi(
        self,
        limit: Optional[int] = None,
        max_workers: int = _MAX_WORKER_GROUPS,
    ) -> None:
        start_time = time.time()
        logger.info("Starting async Privy run (limit=%s, max_concurrent=%s)", limit, max_workers)

        account_manager = self._adapter.get_account_manager()
        all_accounts = account_manager.get_all_accounts()
        if not all_accounts:
            logger.error("No Privy trading accounts available. Please check configuration.")
            return

        selected_accounts = all_accounts[:limit] if limit else all_accounts
        account_ids = [account.id for account in selected_accounts]
        logger.info("Selected %s accounts for async run:", len(account_ids))
        if not account_ids:
            logger.warning(
                "No Privy trading accounts selected after applying limit=%s; skipping run_multi.",
                limit,
            )
            return
        for account in selected_accounts:
            logger.info("   Priority %s: %s", account.priority, account.id)

        results = await self._process_privy_account_parallel(account_ids, max_workers)
        notifications, completed, failed, retried = self._summarize_results(results)

        duration = time.time() - start_time
        time_summary = self._format_duration(duration)
        summary_message = (
            "summary completed -> "
            f"completed: {completed}, failed: {len(failed)}, retried: {len(retried)}"
        )
        if failed:
            summary_message += f" | failed account_ids: {', '.join(failed)}"
        if retried:
            summary_message += f" | retried account_ids: {', '.join(retried)}"
        summary_message += f" | total_time: {time_summary} ({duration:.1f}s) | version=async-v2"
        logger.info(summary_message)

        final_summary = (
            f"{_FINAL_SUMMARY_HEADER}\n"
            f"- Total Time: {time_summary} | Accounts: {len(account_ids)}\n"
            f"- Success: {completed} | Failed: {len(failed)} | Retried: {len(retried)}\n"
        )
        if failed:
            final_summary += f"Failed accounts: {', '.join(failed)}\n"
        if retried:
            final_summary += f"Retried accounts: {', '.join(retried)}\n"

        if notifications:
            combined = "Multi-Account Privy Trading Results (Async Mode):\n\n" + "\n".join(notifications)
            send_discord_notification(combined)
        send_discord_notification(final_summary)
        logger.info("Total execution time: %s [mode=async]", time_summary)

    def run_single(self, account_id: str, wallet_type: Optional[str] = None) -> None:
        if not account_id:
            logger.error("An account_id is required for single-account run.")
            return

        wallet_type = wallet_type or self.wallet_type
        start_time = time.time()
        logger.info("Starting direct single-account Privy run for %s", account_id)

        adapter = HyperliquidPrivyAdapter(wallet_type=wallet_type)
        account_manager = adapter.get_account_manager()
        account = account_manager.get_account_info(account_id)
        if account is None:
            logger.error("Privy trading account %s not found. Please check configuration.", account_id)
            return

        logger.info("Selected account -> priority: %s, id: %s", account.priority, account.id)
        account_start = time.time()
        processed_id, notification, status, was_retried = self._process_privy_account_sequentially(account.id, account_manager, 0)
        processed_id = processed_id or account.id
        notification_text = (notification or "").strip()

        if notification_text:
            logger.info("[single] %s", notification_text)
        else:
            logger.info("[single] No notification returned for account %s", processed_id)

        self._log_account_result("single", account, processed_id, status)
        account_duration = time.time() - account_start
        logger.info(
            "[single] Account %s finished with status=%s in %.1fs",
            processed_id,
            status,
            account_duration,
        )

        total_duration = time.time() - start_time
        time_summary = self._format_duration(total_duration)
        completed_accounts = 1 if status == "success" else 0
        failed_accounts = [] if status == "success" else [processed_id]
        retried_accounts = [processed_id] if was_retried else []

        summary_message = (
            "summary completed -> "
            f"completed: {completed_accounts}, failed: {len(failed_accounts)}, retried: {len(retried_accounts)}"
        )
        if failed_accounts:
            summary_message += f" | failed account_ids: {', '.join(failed_accounts)}"
        if retried_accounts:
            summary_message += f" | retried account_ids: {', '.join(retried_accounts)}"
        summary_message += f" | total_time: {time_summary} ({total_duration:.1f}s) | version=direct-single-v2"
        logger.info(summary_message)
        logger.info(
            "Total execution time: %s for account %s [mode=direct-single]",
            time_summary,
            processed_id,
        )

        final_summary = (
            f"{_FINAL_SINGLE_SUMMARY_HEADER}\n"
            f"- Total Time: {time_summary} | Account: {processed_id}\n"
            f"- Success: {completed_accounts} | Failed: {len(failed_accounts)} | Retried: {len(retried_accounts)}\n"
        )
        if failed_accounts:
            final_summary += f"Failed account: {', '.join(failed_accounts)}\n"
        if retried_accounts:
            final_summary += f"Retried account: {', '.join(retried_accounts)}\n"

        if notification_text:
            send_discord_notification(notification_text)
        send_discord_notification(final_summary)

    # ------------------------------------------------------------------
    # Internal helpers (ported from original scripts)
    # ------------------------------------------------------------------
    def _chunk_accounts(self, ids: Sequence[str], max_workers: int) -> list[list[str]]:
        if not ids:
            return []
        max_workers = max(1, max_workers)
        chunk_size = max(_MIN_ACCOUNTS_PER_GROUP, math.ceil(len(ids) / max_workers))
        return [list(ids[i: i + chunk_size]) for i in range(0, len(ids), chunk_size)]

    def _execute_single_privy_account_trading(
        self,
        account_id: str,
        account_manager,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        notification_message = f"Privy Account {account_id or 'Default'}:\n"
        account_failed = False
        trades_executed = 0

        order_manager = self._adapter.create_order_manager(account_id)
        privy_account = account_manager.get_account_info(account_id)
        if privy_account is None:
            logger.error("Privy account %s not found via account manager", account_id)
            raise RuntimeError(f"Account info unavailable: {account_id}")

        portfolio_manager = self._adapter.create_portfolio_manager(account_id, attempt)
        holding_positions: List[Dict[str, Any]] = portfolio_manager.get_positions_summary()
        current_time_utc = datetime.now(timezone.utc)

        positions_closed = 0
        closed_symbols: set[str] = set()
        holding_period = privy_account.holding_hour_period
        position_size = privy_account.position_size_percentage
        leverage = privy_account.leverage

        if holding_period and holding_period > 0:
            for pos in holding_positions:
                open_timestamp = pos.get("open_timestamp_utc")
                if not open_timestamp or not isinstance(open_timestamp, str):
                    continue
                open_time_utc = datetime.fromisoformat(open_timestamp)
                time_difference = current_time_utc - open_time_utc
                symbol = pos["symbol"].split("/")[0]
                logger.info(
                    "Auto-close check -> symbol=%s, opened=%s, now=%s, held=%s, threshold=%sh, account_id=%s",
                    symbol,
                    open_time_utc,
                    current_time_utc,
                    time_difference,
                    holding_period,
                    account_id,
                )
                if time_difference > timedelta(hours=holding_period):
                    logger.info("Closing position due to max holding period: %s", symbol)
                    order_manager.close_position_by_symbol(symbol)
                    notification_message += f"Closed old position: {symbol}\n"
                    positions_closed += 1
                    closed_symbols.add(symbol)

        balance_data = portfolio_manager._get_balance()  # Uses cache to avoid repeated API calls
        account_value = float(balance_data.get("account_value", 0) or 0)
        if account_value <= 0:
            logger.warning("Skip trading for %s (account_value = %.2f)", account_id, account_value)
            notification_message += "Skipped: balance is zero\n"
            return self._build_summary(notification_message, True, trades_executed, 0)

        signal_adapter = KolSignalAdapter(crypto_user_wallet_id=account_id)
        dynamic_usdc_amount = portfolio_manager.get_equity_based_usdc_amount(
            percentage=position_size,
            base_amount=1.0,
            leverage=leverage,
        )
        signals: List[KolSignal] = signal_adapter.get_signals(
            usdc_amount=dynamic_usdc_amount,
            use_market_filter=False
        )
        for sig in signals:
            sig.symbol = map_k_symbol(sig.symbol)

        logger.info("Prepared %s signals for Privy account %s", len(signals), account_id or "default")
        if not signals:
            notification_message += "No signals generated\n"
            return self._build_summary(notification_message, True, trades_executed, 0)

        if closed_symbols:
            holding_positions = [
                pos
                for pos in holding_positions
                if not isinstance(pos.get("symbol"), str)
                or pos["symbol"].split("/")[0] not in closed_symbols
            ]

        filtered_duplicated = portfolio_manager.drop_duplicate_signals(signals)
        filtered_position_in_port = portfolio_manager.filter_out_position_in_portfolio(
            filtered_duplicated,
            holding_positions,
        )

        positions_count = portfolio_manager.positions_count()
        signal_should_open, signal_should_close = portfolio_manager.categorize_signals(
            filtered_position_in_port,
            holding_positions,
        )

        if signal_should_close:
            logger.info(
                "Signals flagged for closing are ignored in this direct runner: %s",
                [sig.symbol for sig in signal_should_close],
            )

        available_slots = self.max_allowed_positions - positions_count
        if available_slots <= 0:
            notification_message += f"Portfolio full ({positions_count} positions)\n"
            signal_should_open = []
        elif len(signal_should_open) > available_slots:
            notification_message += f"Limited to {available_slots} new positions\n"
            signal_should_open = list(signal_should_open)[:available_slots]

        executor = self._adapter.create_executor(account_id)
        for sig in signal_should_open:
            symbol = sig.symbol.split("/")[0]
            if not executor.is_symbol_supported(symbol):
                logger.info(
                    "Skipping unsupported Hyperliquid symbol %s for account %s", symbol, account_id
                )
                notification_message += f"Skipped {symbol}: unsupported on Hyperliquid\n"
                log_trade_event(
                    source="privy_direct",
                    account_id=str(account_id or "default"),
                    wallet_id=getattr(privy_account, "wallet_id", None),
                    symbol=symbol,
                    side=sig.side,
                    base_size=None,
                    usdc_value=sig.target_usdc_amount,
                    price=None,
                    leverage=leverage,
                    event="direct",
                    status="skipped",
                )
                continue

            if sig.target_usdc_amount and not self.risk_controller.validate_position(sig.target_usdc_amount * leverage):
                logger.warning("Risk controller blocked trade %s %s", sig.side, symbol)
                notification_message += f"Skipped {symbol}: risk controller rejected position\n"
                continue

            try:
                time.sleep(random.uniform(0.2, 0.6))
                logger.info(
                    "Attempting to execute trade: %s %s $%s",
                    sig.side.upper(),
                    symbol,
                    sig.target_usdc_amount,
                )
                result = executor.execute_trade(
                    symbol=symbol,
                    side=sig.side,
                    target_usdc_amount=sig.target_usdc_amount,
                    leverage=leverage,
                )
                success = bool(isinstance(result, dict) and result.get("success"))
                base_size = (result or {}).get("calculated_size") if isinstance(result, dict) else None
                execution_price = (result or {}).get("execution_price") if isinstance(result, dict) else None
                error_detail: str | None = None
                insufficient_balance = False

                if not success:
                    raw_error = (result or {}).get("error") if isinstance(result, dict) else "Order not confirmed"
                    error_detail = raw_error
                    if isinstance(error_detail, str) and "insufficient" in error_detail.lower() and "balance" in error_detail.lower():
                        error_detail = error_detail.replace("Insufficient", "Insufficient!")
                        insufficient_balance = True

                trade_status = "success" if success else "failed"
                if success:
                    logger.info(
                        "Trade executed successfully: %s %s $%s",
                        sig.side.upper(),
                        symbol,
                        sig.target_usdc_amount,
                    )
                    notification_message += f"{sig.side.upper()} {symbol}: ${sig.target_usdc_amount}\n"
                    trades_executed += 1
                else:
                    message = error_detail or "Unknown error"
                    if insufficient_balance:
                        trade_status = "skipped"
                        notification_message += f"Skipped {symbol}: {message}\n"
                        logger.warning("Skipped %s due to insufficient balance: %s", symbol, message)
                    else:
                        account_failed = True
                        notification_message += f"Failed {symbol}: {message}\n"
                        logger.error("Added to notification: Failed %s: %s", symbol, message)

                log_trade_event(
                    source="privy_direct",
                    account_id=str(account_id or "default"),
                    wallet_id=getattr(privy_account, "wallet_id", None),
                    symbol=symbol,
                    side=sig.side,
                    base_size=base_size,
                    usdc_value=sig.target_usdc_amount,
                    price=execution_price,
                    leverage=leverage,
                    event="direct",
                    status=trade_status,
                )
            except UnsupportedHyperliquidSymbol:
                log_trade_event(
                    source="privy_direct",
                    account_id=str(account_id or "default"),
                    wallet_id=getattr(privy_account, "wallet_id", None),
                    symbol=symbol,
                    side=sig.side,
                    base_size=None,
                    usdc_value=sig.target_usdc_amount,
                    price=None,
                    leverage=leverage,
                    event="direct",
                    status="skipped",
                )
                notification_message += f"Skipped {symbol}: unsupported on Hyperliquid\n"
                logger.info("Added to notification: Skipped %s (unsupported on Hyperliquid)", symbol)
            except Exception as exc:
                error_msg = str(exc)
                insufficient_balance = "insufficient" in error_msg.lower() and "balance" in error_msg.lower()
                if insufficient_balance:
                    error_msg = error_msg.replace("Insufficient", "Insufficient!")
                trade_status = "skipped" if insufficient_balance else "failed"
                if insufficient_balance:
                    notification_message += f"Skipped {symbol}: {error_msg}\n"
                    logger.warning("Skipped %s due to insufficient balance: %s", symbol, error_msg)
                else:
                    account_failed = True
                    notification_message += f"Failed {symbol}: {error_msg}\n"
                    logger.error("Added to notification: Failed %s: %s", symbol, error_msg)
                log_trade_event(
                    source="privy_direct",
                    account_id=str(account_id or "default"),
                    wallet_id=getattr(privy_account, "wallet_id", None),
                    symbol=symbol,
                    side=sig.side,
                    base_size=None,
                    usdc_value=sig.target_usdc_amount,
                    price=None,
                    leverage=leverage,
                    event="direct",
                    status=trade_status,
                )

        signals_considered = len(signal_should_open)
        return self._build_summary(notification_message, not account_failed, trades_executed, signals_considered)

    def _trading_operation(self, account_id: str, account_manager) -> Dict[str, Any]:
        return sdk_safe_execution(
            account_id=account_id,
            operation=lambda: self._execute_single_privy_account_trading(account_id, account_manager, attempt=1),
            timeout=120,
        )

    
    def _process_privy_account_sequentially(
        self,
        account_id: str,
        account_manager,
        account_index: int = 0,
    ) -> tuple[str, str, str, bool]:
        logger.info("Starting direct trading run for account: %s", account_id)
        if account_index > 0:
            pre_connection_delay = random.uniform(0.3, 0.8)
            logger.info("Pre-connection stability delay: %.1fs", pre_connection_delay)
            time.sleep(pre_connection_delay)

        try:
            result = execute_with_websocket_retry(
                account_id=account_id,
                operation=lambda: self._trading_operation(account_id, account_manager),
                max_retries=5,
            )
            if result is None:
                raise RuntimeError("WebSocket-enhanced retry attempts exhausted")
        except Exception as exc:
            error_msg = (
                f"Privy Account {account_id}:\n"
                "Failed after WebSocket-enhanced retry attempts\n"
                f"Reason: {exc}\n"
            )
            logger.error(
                "WebSocket-enhanced retry attempts failed for account %s: %s",
                account_id,
                exc,
            )
            return account_id, error_msg, "failed", True

        post_processing_delay = random.uniform(0.2, 0.6)
        logger.info("Post-processing cleanup delay: %.1fs", post_processing_delay)
        time.sleep(post_processing_delay)

        notification_value = result.get("notification", "") if isinstance(result, dict) else str(result or "")
        account_success = bool(result.get("success", True)) if isinstance(result, dict) else True
        status = "success" if account_success else "failed"
        return account_id, str(notification_value or ""), status, False
    def _process_group_sequential(
        self,
        group_ids: Sequence[str],
        account_manager,
        group_index: int,
    ) -> list[tuple[str, str, str, bool]]:
        group_results = []
        for offset, account_id in enumerate(group_ids):
            try:
                processed_id, notification, status, was_retried = self._process_privy_account_sequentially(
                    account_id,
                    account_manager,
                    offset,
                )
            except Exception as exc:
                error_msg = (
                    f"Privy Account {account_id}:\n"
                    "Failed after WebSocket-enhanced retry attempts\n"
                    f"Reason: {exc}\n"
                )
                logger.error(
                    "[group %s] Sequential run failed for account %s: %s",
                    group_index,
                    account_id,
                    exc,
                )
                group_results.append((account_id, error_msg, "failed", True))
            else:
                group_results.append(
                    (
                        processed_id or account_id,
                        (notification or "").strip(),
                        status,
                        was_retried,
                    )
                )
        return group_results

    async def _process_privy_account_sequential(
        self,
        account_ids: Sequence[str],
    ) -> List[Tuple[str, str, str, bool]]:
        account_manager = self._adapter.get_account_manager()
        results: List[Tuple[str, str, str, bool]] = []

        total = len(account_ids)
        logger.info(
            "[seq] Starting sequential processing of %s accounts",
            total,
        )

        for index, account_id in enumerate(account_ids):
            logger.info("[seq] Starting trading run for account: %s", account_id)
            try:
                processed_id, notification, status, was_retried = self._process_privy_account_sequentially(
                    account_id,
                    account_manager,
                    index,
                )
            except Exception as exc:
                error_msg = (
                    f"Privy Account {account_id}:\n"
                    "Failed after WebSocket-enhanced retry attempts\n"
                    f"Reason: {exc}\n"
                )
                logger.error(
                    "[seq] Sequential run failed for account %s: %s",
                    account_id,
                    exc,
                )
                results.append((account_id, error_msg, "failed", True))
                processed_id = account_id
                status = "failed"
            else:
                results.append(
                    (
                        processed_id or account_id,
                        (notification or "").strip(),
                        status,
                        was_retried,
                    )
                )

            progress = ((index + 1) / total) * 100 if total else 100.0
            logger.info(
                "[seq] Progress: %s/%s (%.1f%%) - Account %s completed with status: %s",
                index + 1,
                total,
                progress,
                processed_id or account_id,
                status,
            )

            await asyncio.sleep(0)  # ปล่อย control ให้ event loop

        logger.info("[seq] Completed sequential processing of all %s accounts", total)
        return results
    async def _process_privy_account_parallel(
        self,
        account_ids: Sequence[str],
        max_concurrent: int,
    ) -> list[tuple[str, str, str, bool]]:
        account_manager = self._adapter.get_account_manager()
        chunks = self._chunk_accounts(account_ids, max_concurrent)

        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(
                None,
                lambda g=chunk, idx=grp_idx: self._process_group_sequential(g, account_manager, idx),
            )
            for grp_idx, chunk in enumerate(chunks)
        ]

        results: list[tuple[str, str, str, bool]] = []
        completed = 0
        total = len(tasks)
        logger.info(
            "[async] Starting grouped processing of %s accounts (%s groups, max %s workers)",
            len(account_ids),
            len(chunks),
            max_concurrent,
        )

        for completed_task in asyncio.as_completed(tasks):
            group_result = await completed_task
            results.extend(group_result)
            completed += 1
            progress = (completed / total) * 100
            logger.info(
                "[async] Progress: %s/%s groups (%.1f%%)",
                completed,
                total,
                progress,
            )

        logger.info("[async] Completed processing of all %s accounts", len(account_ids))
        return results

    # async def _process_privy_account_parallel(
    #     self,
    #     account_ids: Sequence[str],
    #     max_concurrent: int,
    # ) -> List[Tuple[str, str, str, bool]]:
    #     semaphore = asyncio.Semaphore(max_concurrent)
    #     account_manager = self._adapter.get_account_manager()

    #     async def process_single(account_id: str, index: int) -> Tuple[str, str, str, bool]:
    #         async with semaphore:
    #             logger.info("[async] Starting trading run for account: %s", account_id)
    #             loop = asyncio.get_event_loop()
    #             try:
    #                 result = await loop.run_in_executor(
    #                     None,
    #                     lambda: execute_with_websocket_retry(
    #                         account_id=account_id,
    #                         operation=lambda: self._trading_operation(account_id, account_manager),
    #                         max_retries=5,
    #                     ),
    #                 )
    #                 if result is None:
    #                     raise RuntimeError("WebSocket-enhanced retry attempts exhausted")
    #             except Exception as exc:
    #                 error_msg = (
    #                     f"Privy Account {account_id}:\n"
    #                     "Failed after WebSocket-enhanced retry attempts\n"
    #                     f"Reason: {exc}\n"
    #                 )
    #                 logger.error("WebSocket-enhanced retry attempts failed for account %s: %s", account_id, exc)
    #                 return account_id, error_msg, "failed", True

    #             notification_value = result.get("notification", "") if isinstance(result, dict) else str(result or "")
    #             account_success = bool(result.get("success", True)) if isinstance(result, dict) else True
    #             status = "success" if account_success else "failed"
    #             return account_id, str(notification_value or ""), status, False

    #     tasks = [asyncio.create_task(process_single(account_id, idx)) for idx, account_id in enumerate(account_ids)]
    #     results: List[Tuple[str, str, str, bool]] = []
    #     completed = 0
    #     total = len(tasks)
    #     logger.info("[async] Starting parallel processing of %s accounts (max concurrent: %s)", total, max_concurrent)
    #     for completed_task in asyncio.as_completed(tasks):
    #         try:
    #             result = await completed_task
    #             results.append(result)
    #             completed += 1
    #             progress = (completed / total) * 100
    #             logger.info(
    #                 "[async] Progress: %s/%s (%.1f%%) - Account %s completed with status: %s",
    #                 completed,
    #                 total,
    #                 progress,
    #                 result[0],
    #                 result[2],
    #             )
    #         except Exception as exc:  # pragma: no cover - defensive
    #             completed += 1
    #             progress = (completed / total) * 100
    #             logger.error("[async] Task failed unexpectedly: %s", exc)
    #             results.append(("unknown", f"Async processing error: {exc}", "failed", True))
    #             logger.info(
    #                 "[async] Progress: %s/%s (%.1f%%) - Account unknown failed",
    #                 completed,
    #                 total,
    #                 progress,
    #             )
    #     logger.info("[async] Completed parallel processing of all %s accounts", total)
    #     return results

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------
    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        if minutes > 0:
            return f"{minutes}m {secs}s"
        return f"{secs}s"

    @staticmethod
    def _build_summary(
        notification_message: str,
        success: bool,
        trades_executed: int,
        signals_considered: int,
    ) -> Dict[str, Any]:
        return {
            "notification": notification_message,
            "success": success,
            "trades_executed": trades_executed,
            "signals_considered": signals_considered,
        }

    @staticmethod
    def _summarize_results(
        results: Iterable[Tuple[str, str, str, bool]]
    ) -> Tuple[List[str], int, List[str], List[str]]:
        notifications: List[str] = []
        failed: List[str] = []
        retried: List[str] = []
        completed = 0
        for account_id, notification, status, was_retried in results:
            if notification:
                notifications.append(notification.strip())
            if status == "success":
                completed += 1
            else:
                failed.append(account_id)
            if was_retried:
                retried.append(account_id)
        return notifications, completed, failed, retried

    @staticmethod
    def _log_account_result(group_name: str, account, account_id: str, status: str) -> None:
        log_trade_event(
            source="privy_direct",
            account_id=str(account_id or "unknown"),
            wallet_id=getattr(account, "wallet_id", None),
            symbol=group_name,
            side="info",
            base_size=None,
            usdc_value=None,
            price=None,
            leverage=None,
            event=f"group-{group_name}",
            status=status,
        )


__all__ = ["HyperliquidPrivyRunner"]




if __name__ == "__main__":  # pragma: no cover
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Run Hyperliquid Privy trading workflows.")
    parser.add_argument(
        "--mode",
        choices=["multi", "single"],
        default="multi",
        help="Run multi-account (async) or single-account execution.",
    )
    parser.add_argument(
        "--account-id",
        help="Account ID to run in single mode. Required when --mode single.",
    )
    parser.add_argument(
        "--wallet-type",
        default="copytrade",
        help="Wallet type to pass to the runner (default: copytrade)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit of accounts when running in multi mode.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=30,
        help="Maximum concurrent workers for multi mode (default: 30).",
    )

    args = parser.parse_args()

    runner = HyperliquidPrivyRunner(wallet_type=args.wallet_type)

    if args.mode == "multi":
        asyncio.run(runner.run_multi(limit=args.limit, max_workers=args.max_workers))
    else:
        if not args.account_id:
            raise SystemExit("--account-id is required when running in single mode")
        runner.run_single(account_id=args.account_id, wallet_type=args.wallet_type)

