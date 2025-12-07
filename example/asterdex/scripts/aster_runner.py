"""Asterdex runner modelled."""

from __future__ import annotations

import asyncio
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from requests.exceptions import ProxyError
from trading_core.core.cex_account_manager import CexAccountManager as AsterdexAccountManager
from trading_core.adapters.signals.kol.signal_adapter import (
    KolSignalAdapter,
    KolSignal,
)
from trading_core.core.base import ExchangeRunner
from trading_core.core.risk import RiskController
from trading_core.exchanges.asterdex.core.adapter import AsterdexAdapter
from trading_core.log import logger
from trading_core.log.trade_logging import log_trade_event
from trading_core.utils.discord import send_discord_notification
from trading_core.utils.proxy import ProxySettings, pop_proxy_override, push_proxy_override
from trading_core.utils.proxy.proxy_pool import next_proxy
from fastapi.responses import JSONResponse


class AsterdexRunner(ExchangeRunner):
    """High-level runner for Asterdex accounts."""

    name = "asterdex"
    supported_modes = ("default",)

    def __init__(
        self,
        wallet_type: str = "copytrade",
        max_allowed_positions: int = 20,
        risk_controller: Optional[RiskController] = None,
    ) -> None:
        self.wallet_type = wallet_type
        self.max_allowed_positions = max_allowed_positions
        self.risk_controller = risk_controller or RiskController()
        

    # ------------------------------------------------------------------
    # ExchangeRunner API
    # ------------------------------------------------------------------
    async def run_multi(
        self,
        limit: Optional[int] = None,
        delay_between_accounts: Tuple[float, float] = (0.3, 0.8),
        max_workers: int = 4,
    ) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._run_multi_sync,
            limit,
            delay_between_accounts,
            max_workers,
        )

    def _run_multi_sync(
        self,
        limit: Optional[int],
        delay_between_accounts: Tuple[float, float],
        max_workers: int,
    ) -> List[Dict[str, Any]]:
        start_time = time.time()

        account_manager = AsterdexAccountManager(exchange="asterdex")
        accounts = account_manager.get_all_accounts()
        if not accounts:
            logger.warning("AsterdexRunner: no accounts available for multi-run")
            return []

        if limit:
            accounts = accounts[:limit]

        total_accounts = len(accounts)
        max_workers = max(1, max_workers or 1)
        results_map: Dict[str, Dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_account: Dict[Any, str] = {}
            for idx, account in enumerate(accounts, start=1):
                account_id = str(account.id)
                future = executor.submit(
                    self._process_account_thread,
                    account_id,
                    idx,
                    total_accounts,
                    delay_between_accounts,
                )
                future_to_account[future] = account_id

            completed = 0
            for future in as_completed(future_to_account):
                account_id = future_to_account[future]
                try:
                    result = future.result()
                    if not isinstance(result, dict):
                        raise TypeError("Worker returned non-dict result")
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception("AsterdexRunner: account %s worker failed: %s", account_id, exc)
                    result = {
                        "notification": str(exc),
                        "success": False,
                        "trades_executed": 0,
                        "signals_considered": 0,
                        "account_id": account_id,
                    }
                result.setdefault("account_id", account_id)
                results_map[account_id] = result
                completed += 1
                logger.info(
                    "AsterdexRunner: completed %s/%s accounts (account_id=%s)",
                    completed,
                    total_accounts,
                    account_id,
                )

        ordered_results: List[Dict[str, Any]] = []
        for account in accounts:
            account_id = str(account.id)
            ordered_results.append(
                results_map.get(
                    account_id,
                    {
                        "account_id": account_id,
                        "notification": "No result returned for account",
                        "success": False,
                        "trades_executed": 0,
                        "signals_considered": 0,
                    },
                )
            )

        self._notify_multi_results(ordered_results, start_time)
        return ordered_results

    def _process_account_thread(
        self,
        account_id: str,
        account_index: int,
        total_accounts: int,
        delay_between_accounts: Tuple[float, float],
    ) -> Dict[str, Any]:
        logger.info(
            "AsterdexRunner: processing account %s (%s/%s)",
            account_id,
            account_index,
            total_accounts,
        )
        try:
            result = self._execute_single_account_trading(account_id=account_id, attempt=1)
            if not isinstance(result, dict):
                raise TypeError("Runner returned non-dict result")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("AsterdexRunner: account %s failed: %s", account_id, exc)
            result = {
                "notification": str(exc),
                "success": False,
                "trades_executed": 0,
                "signals_considered": 0,
                "account_id": account_id,
            }
        else:
            result.setdefault("account_id", account_id)

        low, high = delay_between_accounts
        try:
            low_val = float(low)
            high_val = float(high)
        except (TypeError, ValueError):
            low_val = high_val = 0.0
        if high_val < low_val:
            low_val, high_val = high_val, low_val
        if high_val > 0 or low_val > 0:
            time.sleep(random.uniform(low_val, high_val))
        return result

    def _notify_multi_results(self, results: Sequence[Dict[str, Any]], start_time: float) -> None:
        if not results:
            return

        elapsed = time.time() - start_time
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        duration_parts: List[str] = []
        if hours:
            duration_parts.append(f"{hours}h")
        if minutes:
            duration_parts.append(f"{minutes}m")
        duration_parts.append(f"{seconds}s")
        formatted_duration = " ".join(duration_parts)

        success_count = sum(1 for item in results if item.get("success"))
        failure_ids = [str(item.get("account_id", "?")) for item in results if not item.get("success")]

        detail_lines: List[str] = []
        for item in results:
            account_id = str(item.get("account_id", "unknown"))
            detail_lines.append(f"Aster Account {account_id}:")
            notification = (item.get("notification") or "").strip()
            if notification:
                for line in notification.splitlines():
                    stripped = line.strip()
                    if stripped:
                        detail_lines.append(f"  {stripped}")
            else:
                detail_lines.append("  No updates")
            detail_lines.append("")

        summary_lines = [
            "aster_multi_runner - FINAL SUMMARY - Multi-Account Asterdex Trading Completed",
            f"- Total Time: {formatted_duration} | Accounts: {len(results)}",
            f"- Success: {success_count} | Failed: {len(results) - success_count}",
        ]
        if failure_ids:
            summary_lines.append(f"- Failed accounts: {', '.join(failure_ids)}")

        message_lines = detail_lines + summary_lines
        while message_lines and not message_lines[-1]:
            message_lines.pop()
        send_discord_notification("\n".join(message_lines))

    def run_single(
        self,
        *,
        account_id: str,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        return self._execute_single_account_trading(account_id=account_id, attempt=attempt)

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------
    def _execute_single_account_trading(
        self,
        *,
        account_id: str,
        attempt: int,
    ) -> Dict[str, Any]:
      
        proxy = self._select_proxy()
        push_proxy_override(proxy)
        adapter: Optional[AsterdexAdapter] = None
        try:
            adapter = AsterdexAdapter(account_id=account_id)
            adapter.apply_proxy(proxy)

            # Clear all closse's TPSL pending order
            self.clear_all_stale_aster_triggers(account_id=account_id)
            
            order_manager = adapter.create_order_manager(account_id)
            account_setting = adapter.get_setting()
            
            tp_percentage, sl_percentage = self._extract_tp_sl(account_setting, account_id)

            portfolio_manager = adapter.create_portfolio_manager(account_id, attempt)
            balance_data = portfolio_manager._get_balance()
            positions_summary: List[Dict[str, Any]] = portfolio_manager.get_positions_summary()

            account_value = portfolio_manager.compute_account_value(
                balance_data=balance_data,
                collateral_assets=("USDC",),
            )
            logger.debug("AsterdexRunner: account %s value: %s", account_id, account_value)
            leverage = account_setting.leverage
            logger.debug("AsterdexRunner: account %s leverage: %s", account_id, leverage)

            notification_lines: List[str] = []
            trades_executed = 0
            account_failed = False

            holding_positions = portfolio_manager.filter_open_positions(positions_summary)
            holding_period = account_setting.holding_hour_period
            closed_symbols = self._close_expired_positions(
                account_id=account_id,
                holding_period_hours=holding_period,
                holding_positions=holding_positions,
                order_manager=order_manager,
                notification_lines=notification_lines,
            )

            if account_value <= 0:
                logger.warning(
                    "AsterdexRunner: skip trading for %s (account_value = %.2f)",
                account_id,
                    account_value,
                )
                notification_lines.append(
                    f"Skipped trading: account_value={account_value:.2f}\n"
                )
                notification_message = "".join(notification_lines)
                summary = self._build_summary(notification_message, False, 0, 0)
                summary["account_id"] = account_id
                return summary

            signal_adapter = KolSignalAdapter(crypto_user_wallet_id=account_id)
            dynamic_usdc_amount = portfolio_manager.get_equity_based_usdc_amount(
                percentage=account_setting.position_size_percentage,
                base_amount=1.0,
                leverage=leverage,
            )

            signals: List[KolSignal] = signal_adapter.get_signals(
                usdc_amount=dynamic_usdc_amount,
                use_market_filter=False,
            )
            # MOCK signal
            # signals = [
            #     KolSignal(
            #         symbol="HYPE/USDC:USDC",
            #         side="buy",
            #         order_type="market",
            #         target_usdc_amount=dynamic_usdc_amount,
            #     ),
            # ]
            logger.info(
                "AsterdexRunner: prepared %s signals for account %s",
                len(signals),
                account_id or "default",
            )
            if not signals:
                logger.info("AsterdexRunner: no signals for %s", account_id)
                notification_message = "".join(notification_lines)
                summary = self._build_summary(notification_message, True, 0, 0)
                summary["account_id"] = account_id
                return summary

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
                    "AsterdexRunner: close signals ignored in direct runner: %s",
                    [sig.symbol for sig in signal_should_close],
                )

            available_slots = self.max_allowed_positions - positions_count
            if available_slots <= 0:
                notification_lines.append(f"Portfolio full ({positions_count} positions)\n")
                signal_should_open = []
            elif len(signal_should_open) > available_slots:
                notification_lines.append(f"Limited to {available_slots} new positions\n")
                signal_should_open = list(signal_should_open)[:available_slots]

            executor = adapter.create_executor(account_id)

            for sig in signal_should_open:
                symbol = sig.symbol.split("/")[0]
                if not executor.is_symbol_supported(symbol):
                    logger.info(
                        "AsterdexRunner: skipping unsupported symbol %s for %s",
                        symbol,
                        account_id,
                    )
                    notification_lines.append(f"Skipped {symbol}: unsupported on Asterdex\n")
                    log_trade_event(
                        source="privy_direct",
                        account_id=str(account_id or "default"),
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

                if sig.target_usdc_amount and not self.risk_controller.validate_position(
                    sig.target_usdc_amount * leverage
                ):
                    logger.warning(
                        "AsterdexRunner: risk controller blocked %s %s",
                        sig.side,
                        symbol,
                    )
                    notification_lines.append(
                        f"Skipped {symbol}: risk controller rejected position\n"
                    )
                    continue

                try:
                    try:
                        normalized_symbol = executor._normalize_symbol(symbol)
                    except Exception:  # noqa: BLE001
                        normalized_symbol = symbol.upper()
                    cancel_result = order_manager.cancel_open_orders(normalized_symbol)
                    logger.info(
                        "AsterdexRunner: cancelled pending orders for %s: %s",
                        normalized_symbol,
                        cancel_result,
                    )

                    time.sleep(random.uniform(0.2, 0.6))
                    logger.info(
                        "AsterdexRunner: executing trade %s %s $%s",
                        sig.side.upper(),
                        symbol,
                        sig.target_usdc_amount,
                    )

                    try:
                        result = executor.execute_trade(
                            symbol=symbol,
                            side=sig.side,
                            target_usdc_amount=sig.target_usdc_amount,
                            leverage=leverage,
                            tp_percentage=tp_percentage,
                            sl_percentage=sl_percentage,
                            order_manager=order_manager,
                        )
                    except ProxyError as proxy_exc:
                        logger.warning(
                            "AsterdexRunner: proxy request failed for %s (%s), retrying without proxy",
                            symbol,
                            proxy_exc,
                        )
                        adapter.apply_proxy(ProxySettings())
                        result = executor.execute_trade(
                            symbol=symbol,
                            side=sig.side,
                            target_usdc_amount=sig.target_usdc_amount,
                            leverage=leverage,
                            tp_percentage=tp_percentage,
                            sl_percentage=sl_percentage,
                            order_manager=order_manager,
                        )

                    success = False
                    base_size = None
                    execution_price = None
                    order_status = None
                    error_detail: Optional[str] = None

                    if isinstance(result, dict):
                        order_status = str(result.get("status", "")).upper() or None
                        if order_status and order_status not in {"REJECTED", "EXPIRED"}:
                            success = True

                        executed_qty = result.get("executedQty") or result.get("cumQty")
                        orig_qty = result.get("origQty")
                        try:
                            if executed_qty is not None:
                                qty_val = float(executed_qty)
                                base_size = qty_val if qty_val > 0 else None
                            if base_size is None and orig_qty is not None:
                                qty_val = float(orig_qty)
                                base_size = qty_val if qty_val > 0 else None
                        except (TypeError, ValueError):
                            base_size = None

                        avg_price = result.get("avgPrice") or result.get("price")
                        try:
                            if avg_price is not None:
                                price_val = float(avg_price)
                                execution_price = price_val if price_val > 0 else None
                        except (TypeError, ValueError):
                            execution_price = None

                        error_detail = result.get("error") or result.get("msg")

                    insufficient_balance = False
                    if not success:
                        if error_detail is None and isinstance(result, dict):
                            error_detail = result.get("error") or result.get("msg")
                        if isinstance(error_detail, str):
                            lower_detail = error_detail.lower()
                            if "insufficient" in lower_detail and "balance" in lower_detail:
                                error_detail = error_detail.replace("Insufficient", "Insufficient!")
                                insufficient_balance = True

                    trade_status = "success" if success else "failed"
                    if success:
                        logger.info(
                            "AsterdexRunner: trade executed %s %s $%s",
                            sig.side.upper(),
                            symbol,
                            sig.target_usdc_amount,
                        )
                        notification_lines.append(
                            f"{sig.side.upper()} {symbol}: ${sig.target_usdc_amount}\n"
                        )
                        trades_executed += 1
                    else:
                        message = error_detail or "Unknown error"
                        if insufficient_balance:
                            trade_status = "skipped"
                            notification_lines.append(f"Skipped {symbol}: {message}\n")
                            logger.warning(
                                "AsterdexRunner: skipped %s insufficient balance: %s",
                                symbol,
                                message,
                            )
                        else:
                            account_failed = True
                            notification_lines.append(f"Failed {symbol}: {message}\n")
                            logger.error(
                                "AsterdexRunner: failed %s: %s",
                                symbol,
                                message,
                            )

                    tp_sl_info = result.get("tp_sl") if isinstance(result, dict) else None
                    if tp_sl_info:
                        issues: List[str] = []
                        if isinstance(tp_sl_info, dict):
                            tp_sl_results = tp_sl_info.get("results")
                            if tp_sl_info.get("error"):
                                issues.append(str(tp_sl_info["error"]))
                            if isinstance(tp_sl_results, dict):
                                tp_price = tp_sl_info.get("tp_price")
                                tp_error_msg = tp_sl_results.get("tp_error")
                                tp_entry = tp_sl_results.get("tp")
                                if tp_price and (tp_error_msg or not tp_entry):
                                    issues.append(
                                        f"TP not placed (target={tp_price}): {tp_error_msg or 'no response'}"
                                    )
                                sl_price = tp_sl_info.get("sl_price")
                                sl_error_msg = tp_sl_results.get("sl_error")
                                sl_entry = tp_sl_results.get("sl")
                                if sl_price and (sl_error_msg or not sl_entry):
                                    issues.append(
                                        f"SL not placed (target={sl_price}): {sl_error_msg or 'no response'}"
                                    )
                        if issues:
                            notification_lines.append(
                                f"TP/SL issues for {symbol}: " + "; ".join(issues) + "\n"
                            )

                    log_trade_event(
                        source="privy_direct",
                        account_id=str(account_id or "default"),
                        symbol=symbol,
                        side=sig.side,
                        base_size=base_size,
                        usdc_value=sig.target_usdc_amount,
                        price=execution_price,
                        leverage=leverage,
                        event="direct",
                        status=trade_status,
                    )
                except Exception as exc:
                    error_msg = str(exc)
                    response_text = ""
                    response = getattr(exc, "response", None)
                    if response is not None:
                        try:
                            response_text = response.text or ""
                        except Exception:  # noqa: BLE001
                            response_text = ""
                    combined_msg = f"{error_msg} {response_text}".strip()
                    lower_msg = combined_msg.lower()
                    insufficient_notional = (
                        "minqty" in lower_msg
                        or ("quantity" in lower_msg and "below" in lower_msg)
                        or "minnotional" in lower_msg
                        or "min notional" in lower_msg
                        or ("insufficient" in lower_msg and "balance" in lower_msg)
                    )
                    trade_status = "skipped" if insufficient_notional else "failed"
                    if insufficient_notional:
                        logger.info(
                            "AsterdexRunner: skipped %s due to min notional: %s",
                            symbol,
                            combined_msg,
                        )
                        notification_lines.append(f"Skipped {symbol}: {combined_msg}\n")
                    else:
                        account_failed = True
                        logger.error(
                            "AsterdexRunner: failed to execute %s: %s",
                            symbol,
                            combined_msg,
                        )
                        notification_lines.append(f"Failed {symbol}: {combined_msg}\n")
                    log_trade_event(
                        source="privy_direct",
                        account_id=str(account_id or "default"),
                        symbol=symbol,
                        side=sig.side,
                        base_size=None,
                        usdc_value=sig.target_usdc_amount,
                        price=None,
                        leverage=leverage,
                        event="direct",
                        status=trade_status,
                    )
                    continue

            signals_considered = len(signal_should_open)
            notification_message = "".join(notification_lines)
            summary = self._build_summary(
                notification_message, not account_failed, trades_executed, signals_considered
            )
            logger.info("AsterdexRunner summary: %s", summary)
            summary["account_id"] = account_id
            return summary
        finally:
            with suppress(Exception):
                if adapter is not None:
                    adapter.apply_proxy(ProxySettings())
            with suppress(RuntimeError):
                pop_proxy_override()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_tp_sl(account_setting: Any, account_id: str) -> Tuple[Optional[float], Optional[float]]:
        tp_percentage: Optional[float] = None
        sl_percentage: Optional[float] = None
        if account_setting:
            try:
                if account_setting.tp_percentage is not None:
                    tp_percentage = float(account_setting.tp_percentage)
            except (TypeError, ValueError):
                logger.warning(
                    "AsterdexRunner: invalid tp_percentage for %s, skipping TP orders",
                    account_id,
                )
                tp_percentage = None
            try:
                if account_setting.sl_percentage is not None:
                    sl_percentage = float(account_setting.sl_percentage)
            except (TypeError, ValueError):
                logger.warning(
                    "AsterdexRunner: invalid sl_percentage for %s, skipping SL orders",
                    account_id,
                )
                sl_percentage = None
        else:
            logger.warning("AsterdexRunner: account setting not found for %s", account_id)
        return tp_percentage, sl_percentage

    @staticmethod
    def _close_expired_positions(
        *,
        account_id: str,
        holding_period_hours: Optional[int],
        holding_positions: Sequence[Dict[str, Any]],
        order_manager,
        notification_lines: List[str],
    ) -> set[str]:
        closed_symbols: set[str] = set()
        if not holding_period_hours or holding_period_hours <= 0:
            return closed_symbols

        current_time_utc = datetime.now(timezone.utc)
        for pos in holding_positions:
            raw_ts = pos.get("updateTime")
            if not raw_ts:
                continue
            try:
                open_time_utc = datetime.fromtimestamp(int(raw_ts) / 1000, tz=timezone.utc)
            except (ValueError, OSError):
                continue

            time_difference = current_time_utc - open_time_utc
            symbol = str(pos.get("symbol", "")).upper()
            logger.info(
                "AsterdexRunner: auto-close check symbol=%s held=%s threshold=%sh account_id=%s",
                symbol,
                time_difference,
                holding_period_hours,
                account_id,
            )
            # holding_period_hours = 10 / 60
            if time_difference > timedelta(hours=holding_period_hours):
                try:
                    position_amt = float(pos.get("positionAmt", 0) or 0)
                except (TypeError, ValueError):
                    position_amt = 0
                if position_amt == 0:
                    continue

                logger.info(
                    "AsterdexRunner: closing position due to holding period %s (qty=%s)",
                    symbol,
                    position_amt,
                )
                position_side = pos.get("positionSide", "BOTH")
                order_manager.close_position(symbol, position_amt, position_side=position_side)
                notification_lines.append(f"Closed old position: {symbol}\n")
                closed_symbols.add(symbol)
                # ============= cancel TP SL =========== #
                try:
                    normalized_symbol = symbol.split("/")[0]  # หรือใช้เมธอด normalize ที่มีอยู่ใน executor
                    order_manager.cancel_open_orders(normalized_symbol)
                    notification_lines.append(f"Cleared pending TP/SL for {normalized_symbol}\n")
                except Exception as cancel_exc:  # noqa: BLE001
                            logger.warning(
                        "AsterdexRunner: failed to cancel leftover orders for %s: %s",
                        symbol,
                        cancel_exc,
                    )
        return closed_symbols

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
    def clear_all_stale_aster_triggers(
        account_id: str,
        wallet_type: str = "copytrade",
    ) -> Dict[str, Any] | JSONResponse:
        if not account_id:
            return JSONResponse(
                status_code=400,
                content={"error": "account_id is required"},
            )

        try:
            adapter = AsterdexAdapter(account_id=account_id, wallet_type=wallet_type)

            # ให้แน่ใจว่ามี client/manager พร้อมใช้งานก่อน
            order_manager = adapter.create_order_manager(account_id)

            stale_info = adapter.find_stale_triggers()
            if not stale_info.get("has_stale_triggers"):
                stale_info["cancel_results"] = {}
                return stale_info

            cancel_results: Dict[str, Any] = {}
            for symbol, orders in stale_info.get("stale_triggers_by_symbol", {}).items():
                try:
                    # API ของ Aster ใช้รูปแบบ SYMBOLUSDT ไม่มี slash อยู่แล้ว
                    cancel_results[symbol] = order_manager.cancel_open_orders(symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to cancel stale triggers for %s: %s", symbol, exc)
                    cancel_results[symbol] = {"error": str(exc)}

            stale_info["cancel_results"] = cancel_results
            return stale_info

        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to clear stale Asterdex triggers for %s", account_id)
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(exc),
                    "account_id": account_id,
                },
            )

    def _select_proxy(self, attempts: int = 3) -> ProxySettings:
        """Select a healthy proxy if available, otherwise fall back to direct connection."""
        for attempt in range(1, attempts + 1):
            proxy = next_proxy()
            if not proxy or not proxy.is_configured:
                logger.info("AsterdexRunner: no proxy configured, using direct connection")
                return proxy
            try:
                response = requests.get(
                    "https://fapi.asterdex.com/fapi/v1/ping",
                    proxies=proxy.as_requests_proxies(),
                    timeout=2,
                )
                if response.status_code == 200:
                    logger.info(
                        "AsterdexRunner: proxy %s:%s passed health check",
                        proxy.host,
                        proxy.port,
                    )
                    return proxy
            except Exception as exc:
                            logger.warning(
                    "AsterdexRunner: proxy %s:%s failed health check (%s) [attempt %s/%s]",
                    proxy.host,
                    proxy.port,
                    exc,
                    attempt,
                    attempts,
                )
        logger.warning("AsterdexRunner: all proxy attempts failed, falling back to direct connection")
        return ProxySettings()


__all__ = ["AsterdexRunner"]


