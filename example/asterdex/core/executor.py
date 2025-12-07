from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Optional

from trading_core.exchanges.asterdex.core.client import AsterdexFuturesClient
from trading_core.exchanges.hyperliquid.script.tp_sl_utils import calculate_tp_sl_prices


class AsterdexFutureExecution:
    """Simple executor for placing market orders on Asterdex."""

    def __init__(
        self,
        client: AsterdexFuturesClient,
        account_id: str,
        *,
        symbol_registry=None,
    ) -> None:
        self.client = client
        self.account_id = account_id
        self._symbol_registry = symbol_registry

    def execute_trade(
        self,
        *,
        symbol: str,
        side: str,
        target_usdc_amount: float,
        leverage: float = 1.0,
        reduce_only: bool = False,
        position_side: str | None = None,
        tp_percentage: Optional[float] = None,
        sl_percentage: Optional[float] = None,
        order_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        
        symbol_normalized = self._normalize_symbol(symbol)
        if target_usdc_amount <= 0:
            raise ValueError("target_usdc_amount must be positive")
        if leverage <= 0:
            raise ValueError("leverage must be positive")
        if side.lower() not in {"buy", "sell"}:
            raise ValueError(f"Invalid side: {side}")
        if not self.is_symbol_supported(symbol_normalized):
            raise ValueError(f"Symbol not supported on Asterdex: {symbol}")

        mark_price = self._get_mark_price(symbol_normalized)
        notional = target_usdc_amount * max(leverage, 1.0)
        quantity = notional / mark_price
        quantity = self._quantize_quantity(symbol_normalized, quantity)
        if quantity <= 0:
            raise ValueError("Calculated quantity is zero after quantization")

        self._ensure_min_notional(symbol_normalized, quantity, mark_price)

        payload: Dict[str, Any] = {
            "symbol": symbol_normalized,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": self._format_quantity(symbol_normalized, quantity),
        }
        if reduce_only:
            payload["reduceOnly"] = "true"
        if position_side:
            payload["positionSide"] = position_side.upper()
        result = self.client.place_order(payload)

        if isinstance(result, dict):
            order_status = str(result.get("status", "")).upper()
            success = order_status and order_status not in {"REJECTED", "EXPIRED"}
            if success and order_manager and (tp_percentage or sl_percentage):
                
                base_size = None
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

                price_basis = None
                avg_price = result.get("avgPrice") or result.get("price")
                try:
                    if avg_price is not None:
                        price_val = float(avg_price)
                        price_basis = price_val if price_val > 0 else None
                except (TypeError, ValueError):
                    price_basis = None

                if price_basis is None:
                    try:
                        price_basis = self._get_mark_price(symbol_normalized)
                    except Exception:  # noqa: BLE001
                        price_basis = None

                if price_basis and (tp_percentage or sl_percentage):
                    calc_tp, calc_sl = calculate_tp_sl_prices(
                        entry_price=price_basis,
                        side=side,
                        tp_percentage=tp_percentage or 0,
                        sl_percentage=sl_percentage or 0,
                    )
                    tp_price = calc_tp if tp_percentage and calc_tp and calc_tp > 0 else None
                    sl_price = calc_sl if sl_percentage and calc_sl and calc_sl > 0 else None

                    if (tp_price and tp_price > 0) or (sl_price and sl_price > 0):
                        quantity_for_tp_sl = base_size
                        if quantity_for_tp_sl is None:
                            try:
                                positions = order_manager.client.position_risk(symbol_normalized)
                                for pos in positions:
                                    if str(pos.get("symbol", "")).upper() == symbol_normalized:
                                        qty_val = abs(float(pos.get("positionAmt", 0) or 0))
                                        if qty_val > 0:
                                            quantity_for_tp_sl = qty_val
                                        break
                            except Exception:  # noqa: BLE001
                                quantity_for_tp_sl = None

                        tp_sl_attempt: Dict[str, Any] | None = None
                        try:
                            tp_sl_results = order_manager.place_tp_sl_orders(
                                symbol=symbol_normalized,
                                entry_side=side,
                                tp_price=tp_price,
                                sl_price=sl_price,
                                position_side=position_side or "BOTH",
                                quantity=quantity_for_tp_sl,
                            )
                            tp_sl_attempt = {
                                "tp_price": tp_price,
                                "sl_price": sl_price,
                                "results": tp_sl_results,
                            }
                        except Exception as exc:  # noqa: BLE001
                            tp_sl_attempt = {
                                "tp_price": tp_price,
                                "sl_price": sl_price,
                                "results": None,
                                "error": str(exc),
                            }
                        if tp_sl_attempt and isinstance(result, dict):
                            result["tp_sl"] = (
                                tp_sl_attempt
                                if not isinstance(result.get("tp_sl"), dict)
                                else {
                                    **result["tp_sl"],
                                    **{k: v for k, v in tp_sl_attempt.items() if v is not None},
                                }
                            )

        return result
    def _normalize_symbol(self, symbol: str) -> str:
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

    def _get_mark_price(self, symbol: str) -> float:
        data = self.client.mark_price(symbol)
        price: Optional[float] = None
        if isinstance(data, dict):
            for key in ("markPrice", "indexPrice", "price"):
                value = data.get(key)
                if value is not None:
                    price = float(value)
                    break
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                if str(item.get("symbol", "")).upper() == symbol:
                    value = item.get("markPrice") or item.get("price")
                    if value is not None:
                        price = float(value)
                        break
        if price is None or price <= 0:
            raise ValueError(f"Unable to fetch mark price for {symbol}")
        return price

    def _get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self._symbol_registry:
            return None
        return self._symbol_registry.get_symbol_info(symbol)

    def _quantize_quantity(self, symbol: str, quantity: float) -> float:
        info = self._get_symbol_info(symbol)
        if not info:
            return quantity
        step = None
        min_qty = 0.0
        max_qty = None
        for filt in info.get("filters", []):
            if isinstance(filt, dict) and filt.get("filterType") == "LOT_SIZE":
                step = filt.get("stepSize")
                min_qty = float(filt.get("minQty", 0) or 0)
                max_qty_value = filt.get("maxQty")
                if max_qty_value is not None:
                    try:
                        max_qty = float(max_qty_value)
                    except (TypeError, ValueError):
                        max_qty = None
                break
        if step:
            step_decimal = Decimal(str(step))
            quantity = float(Decimal(str(quantity)).quantize(step_decimal, rounding=ROUND_DOWN))
        if min_qty and quantity < min_qty:
            raise ValueError(f"Quantity {quantity} below minQty {min_qty} for {symbol}")
        if max_qty and quantity > max_qty:
            raise ValueError(f"Quantity {quantity} exceeds maxQty {max_qty} for {symbol}")
        return quantity

    def _ensure_min_notional(self, symbol: str, quantity: float, mark_price: float) -> None:
        info = self._get_symbol_info(symbol)
        if not info:
            return
        min_notional = 0.0
        for filt in info.get("filters", []):
            if isinstance(filt, dict) and filt.get("filterType") == "MIN_NOTIONAL":
                try:
                    min_notional = float(filt.get("notional", 0) or 0)
                except (TypeError, ValueError):
                    min_notional = 0.0
                break
        if min_notional:
            notional = quantity * mark_price
            if notional < min_notional:
                raise ValueError(
                    f"Notional {notional} below minNotional {min_notional} for {symbol}"
                )

    def _format_quantity(self, symbol: str, quantity: float) -> str:
        info = self._get_symbol_info(symbol)
        decimals = 8
        if info:
            for filt in info.get("filters", []):
                if isinstance(filt, dict) and filt.get("filterType") == "LOT_SIZE":
                    step = filt.get("stepSize")
                    if step:
                        step_decimal = Decimal(str(step))
                        decimals = max(0, -step_decimal.as_tuple().exponent)
                    break
        formatted = f"{quantity:.{decimals}f}".rstrip("0").rstrip(".")
        return formatted if formatted else "0"

    def is_symbol_supported(self, symbol: str) -> bool:
        if not self._symbol_registry:
            return True
        return self._symbol_registry.is_symbol_supported(symbol)
# placeholder to modify via apply_patch
