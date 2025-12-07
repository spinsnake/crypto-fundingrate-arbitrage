from __future__ import annotations

from typing import Any, Dict, Optional

from trading_core.log.logger import logger
from trading_core.exchanges.asterdex.core.client import AsterdexFuturesClient


class AsterdexOrderManagement:
    """Minimal order management wrapper around the Asterdex REST client."""

    def __init__(self, client: AsterdexFuturesClient, account_id: str) -> None:
        self.client = client
        self.account_id = account_id

    def close_position(
        self,
        symbol: str,
        position_amount: float,
        *,
        position_side: str = "BOTH",
    ) -> Dict[str, Any]:
        qty = abs(position_amount)
        if qty <= 0:
            raise ValueError("Position amount must be non-zero to close a position")

        side = "SELL" if position_amount > 0 else "BUY"
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "quantity": f"{qty:g}",
            "reduceOnly": "true",
        }
        if position_side:
            payload["positionSide"] = position_side.upper()
        return self.client.place_order(payload)

    def close_position_by_symbol(
        self,
        symbol: str,
        *,
        position_side: str | None = None,
    ) -> Dict[str, Any]:
        symbol_upper = symbol.upper()
        positions = self.client.position_risk(symbol_upper)
        position_amt = 0.0
        derived_side = position_side or "BOTH"
        for pos in positions:
            if str(pos.get("symbol", "")).upper() != symbol_upper:
                continue
            try:
                position_amt = float(pos.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                position_amt = 0.0
            derived_side = pos.get("positionSide", derived_side)
            break
        if position_amt == 0:
            raise ValueError(f"No open position to close for {symbol_upper}")
        return self.close_position(symbol_upper, position_amt, position_side=derived_side)

    def _place_trigger_order(
        self,
        *,
        symbol: str,
        side: str,
        trigger_price: float,
        order_type: str,
        position_side: str = "BOTH",
        quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "stopPrice": f"{trigger_price:g}",
            "reduceOnly": "true",
            "workingType": "MARK_PRICE",
            "timeInForce": "GTC",
            "priceProtect": "false",
        }

        if quantity is not None and quantity > 0:
            payload["quantity"] = f"{quantity:g}"
        else:
            payload["closePosition"] = "true"

        if position_side:
            payload["positionSide"] = position_side.upper()
        return self.client.place_order(payload)

    def place_tp_sl_orders(
        self,
        *,
        symbol: str,
        entry_side: str,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
        position_side: str = "BOTH",
        quantity: Optional[float] = None,
    ) -> Dict[str, Any]:
        exit_side = "SELL" if entry_side.lower() == "buy" else "BUY"
        results: Dict[str, Any] = {
            "tp": None,
            "sl": None,
            "tp_error": None,
            "sl_error": None,
        }

        if tp_price is not None and tp_price > 0:
            last_error: Optional[str] = None
            for attempt in range(1, 4):
                try:
                    results["tp"] = self._place_trigger_order(
                        symbol=symbol,
                        side=exit_side,
                        trigger_price=tp_price,
                        order_type="TAKE_PROFIT_MARKET",
                        position_side=position_side,
                        quantity=quantity,
                    )
                    tp_resp = results["tp"]
                    if isinstance(tp_resp, dict):
                        status = str(tp_resp.get("status", "") or "").upper()
                        code = tp_resp.get("code")
                        msg = tp_resp.get("msg")
                        if (
                            code not in (None, 0)
                            or status in {"REJECTED", "EXPIRED", "CANCELED"}
                            or (msg and not status)
                        ):
                            results["tp_error"] = msg or str(tp_resp)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    logger.error(
                        "AsterdexOrderManagement: failed to place TP order for %s (attempt %s/3): %s",
                        symbol,
                        attempt,
                        exc,
                    )
            if results["tp"] is None and last_error:
                results["tp_error"] = last_error

        if sl_price is not None and sl_price > 0:
            last_error = None
            for attempt in range(1, 4):
                try:
                    results["sl"] = self._place_trigger_order(
                        symbol=symbol,
                        side=exit_side,
                        trigger_price=sl_price,
                        order_type="STOP_MARKET",
                        position_side=position_side,
                        quantity=quantity,
                    )
                    sl_resp = results["sl"]
                    if isinstance(sl_resp, dict):
                        status = str(sl_resp.get("status", "") or "").upper()
                        code = sl_resp.get("code")
                        msg = sl_resp.get("msg")
                        if (
                            code not in (None, 0)
                            or status in {"REJECTED", "EXPIRED", "CANCELED"}
                            or (msg and not status)
                        ):
                            results["sl_error"] = msg or str(sl_resp)
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    logger.error(
                        "AsterdexOrderManagement: failed to place SL order for %s (attempt %s/3): %s",
                        symbol,
                        attempt,
                        exc,
                    )
            if results["sl"] is None and last_error:
                results["sl_error"] = last_error

        return results

    def cancel_open_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if symbol:
            return self.client.cancel_all(symbol.upper())
        raise ValueError("Symbol is required to cancel orders on Asterdex")

    def find_stale_aster_triggers_service(
        account_id: str,
        wallet_type: str = "copytrade",
    ) -> Dict[str, Any] | JSONResponse:
        """
        Inspect Asterdex trigger orders (TP/SL) and flag ones without matching open positions.
        """
        if not account_id:
            return JSONResponse(
                status_code=400,
                content={"error": "account_id is required"},
            )

        try:
            adapter = AsterdexAdapter(account_id=account_id, wallet_type=wallet_type)

            # Ensure the client/session is initialised
            adapter.create_order_manager(account_id)

            portfolio_manager = adapter.create_portfolio_manager(account_id, attempt=1)
            positions_summary = portfolio_manager.get_positions_summary()
            open_positions = portfolio_manager.filter_open_positions(positions_summary)

            active_symbols: set[str] = set()
            for position in open_positions:
                raw_symbol = str(position.get("symbol", "")).upper()
                if not raw_symbol:
                    continue
                base_symbol = raw_symbol.split("/")[0]
                active_symbols.add(base_symbol)

            # Fetch all open orders for the account
            open_orders = adapter.client.open_orders() if adapter.client else []  # type: ignore[attr-defined]

            trigger_orders: List[Dict[str, Any]] = []
            stale_by_symbol: Dict[str, List[Dict[str, Any]]] = {}

            for order in open_orders or []:
                order_type = str(order.get("type", "")).upper()
                reduce_only_flag = str(order.get("reduceOnly", "")).lower() == "true"
                if order_type not in {"TAKE_PROFIT_MARKET", "STOP_MARKET"} or not reduce_only_flag:
                    continue

                symbol = str(order.get("symbol", "")).upper()
                base_symbol = symbol.split("/")[0] if "/" in symbol else symbol
                trigger_orders.append(order)

                if base_symbol not in active_symbols:
                    stale_by_symbol.setdefault(symbol, []).append(order)

            stale_count = sum(len(orders) for orders in stale_by_symbol.values())

            return {
                "status": "ok",
                "account_id": account_id,
                "wallet_type": wallet_type,
                "active_position_symbols": sorted(active_symbols),
                "trigger_order_count": len(trigger_orders),
                "stale_trigger_count": stale_count,
                "stale_triggers_by_symbol": stale_by_symbol,
                "has_stale_triggers": stale_count > 0,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to inspect Asterdex triggers for account %s", account_id)
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(exc),
                    "account_id": account_id,
                },
            )

__all__ = ["AsterdexOrderManagement"]
