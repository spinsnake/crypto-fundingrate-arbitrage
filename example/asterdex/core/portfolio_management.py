from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from trading_core.adapters.signals.kol.signal_adapter import KolSignal
from trading_core.exchanges.asterdex.core.client import AsterdexFuturesClient


class AsterdexPortfolioManagement:
    """
    Simplified portfolio management for Asterdex trading.

    Provides helper methods similar to the Privy portfolio manager so the runner
    can reuse the same control flow while the deeper logic is iterated on.
    """

    def __init__(
        self,
        client: AsterdexFuturesClient,
        account_id: str,
        *,
        attempt: int = 1,
        wallet_created_at: datetime | str | None = None,
    ) -> None:
        self.client = client
        self.account_id = account_id
        self.attempt = attempt
        self._wallet_created_at_ms = self._to_epoch_ms(wallet_created_at)
        self._activity_cache: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Balance / positions
    # ------------------------------------------------------------------
    def _get_balance(self) -> Dict[str, Any]:
        try:
            raw_balance = self.client.futures_balance()
        except Exception as exc:  # pragma: no cover - defensive
            return {"error": str(exc)}
        return self._normalise_balance(raw_balance)

    def compute_account_value(
        self,
        *,
        balance_data: Dict[str, Any] | None = None,
        collateral_assets: tuple[str, ...] = ("USDC", "USDT"),
    ) -> float:
        """
        Estimate account value for sizing orders.

        Args:
            balance_data: Optional pre-fetched balance snapshot; if not provided,
                this method will call `_get_balance()`.
            collateral_assets: Tuple of asset symbols to include in the sum when
                summary fields are not populated. Defaults to ("USDC",).
        """
        snapshot = balance_data or self._get_balance()
        value = snapshot.get("account_value") or snapshot.get("total_wallet_balance")
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass

        total = 0.0
        for asset in snapshot.get("assets", []):
            symbol = str(asset.get("asset", "")).upper()
            if collateral_assets and symbol not in collateral_assets:
                continue

            amount = (
                asset.get("crossWalletBalance")
                or asset.get("walletBalance")
                or asset.get("balance")
                or 0
            )
            try:
                total += float(amount)
            except (TypeError, ValueError):
                continue
        return total

    def calculate_balances_usdt(
        self,
        *,
        account_info: Optional[Dict[str, Any]] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        balance_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base_snapshot: Dict[str, Any] = {}
        if balance_data is not None:
            base_snapshot = self._normalise_balance(balance_data)
        elif snapshot is not None:
            base_snapshot = dict(snapshot)
        else:
            base_snapshot = self._get_balance()

        info: Dict[str, Any] = {}
        if isinstance(account_info, dict):
            info = dict(account_info)
        elif isinstance(snapshot, dict):
            info = dict(snapshot)

        total_wallet = self._safe_float(
            base_snapshot.get("total_wallet_balance") or base_snapshot.get("totalWalletBalance")
        )
        available_balance = self._safe_float(
            base_snapshot.get("available_balance") or base_snapshot.get("availableBalance")
        )
        total_margin_balance = self._safe_float(
            base_snapshot.get("total_margin_balance") or base_snapshot.get("totalMarginBalance")
        )
        total_unrealized = self._safe_float(
            base_snapshot.get("total_unrealized_pnl") or base_snapshot.get("totalUnrealizedProfit")
        )
        total_initial_margin = self._safe_float(
            base_snapshot.get("total_initial_margin") or base_snapshot.get("totalInitialMargin")
        )
        total_open_order_margin = self._safe_float(
            base_snapshot.get("total_open_order_margin") or base_snapshot.get("totalOpenOrderInitialMargin")
        )
        total_position_margin = self._safe_float(
            base_snapshot.get("total_position_margin") or base_snapshot.get("totalPositionInitialMargin")
        )
        max_withdraw = self._safe_float(
            base_snapshot.get("max_withdraw_amount") or base_snapshot.get("maxWithdrawAmount")
        )

        total_free = available_balance
        total_locked = max(total_wallet - total_free, 0.0)

        assets = base_snapshot.get("assets")
        if not isinstance(assets, list):
            assets = []

        enriched_assets: List[Dict[str, Any]] = []
        total_value = 0.0
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            entry = dict(asset)
            wallet_balance = self._safe_float(
                asset.get("walletBalance")
                or asset.get("crossWalletBalance")
                or asset.get("balance")
                or asset.get("availableBalance")
                or asset.get("total")
            )
            available_asset = self._safe_float(
                asset.get("availableBalance") or asset.get("maxWithdrawAmount") or wallet_balance
            )
            locked_asset = max(wallet_balance - available_asset, 0.0)

            entry.setdefault("walletBalance", wallet_balance)
            entry.setdefault("availableBalance", available_asset)
            entry.setdefault("balance", wallet_balance)
            entry.setdefault("maxWithdrawAmount", available_asset)
            entry["free"] = available_asset
            entry["locked"] = locked_asset
            entry["total"] = wallet_balance
            entry["price_usdt"] = 1.0
            entry["value_usdt"] = wallet_balance

            total_value += wallet_balance
            enriched_assets.append(entry)

        total_value_usdt = total_wallet if total_wallet else total_value

        return {
            "total_free": total_free,
            "total_locked": total_locked,
            "available_balance": available_balance,
            "total_wallet_balance": total_wallet,
            "total_margin_balance": total_margin_balance,
            "total_unrealized_pnl": total_unrealized,
            "total_initial_margin": total_initial_margin,
            "total_open_order_margin": total_open_order_margin,
            "total_position_margin": total_position_margin,
            "max_withdraw_amount": max_withdraw,
            "account_value": total_wallet,
            "assets": enriched_assets,
            "total_value_usdt": total_value_usdt,
        }

    @staticmethod
    def _safe_float(value: Any) -> float:
        if value in (None, "", "0", 0):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------
    def drop_duplicate_signals(self, signals: Sequence[KolSignal]) -> List[KolSignal]:
        unique: Dict[str, KolSignal] = {}
        for signal in signals:
            unique[signal.symbol] = signal
        return list(unique.values())

    def filter_out_position_in_portfolio(
        self,
        signals: Sequence[KolSignal],
        holding_positions: Iterable[Dict[str, Any]],
    ) -> List[KolSignal]:
        def _normalize(symbol: str) -> str:
            if not symbol:
                return ""
            cleaned = symbol.upper()
            if "/" in cleaned:
                cleaned = cleaned.split("/", 1)[0]
            if ":" in cleaned:
                cleaned = cleaned.split(":", 1)[0]
            for suffix in ("USDT", "USDC", "USD"):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
                    break
            return cleaned

        open_symbols = {
            _normalize(pos.get("symbol", ""))
            for pos in holding_positions
            if isinstance(pos, dict) and pos.get("symbol")
        }

    def _normalise_balance(self, raw_balance: Any) -> Dict[str, Any]:
        def _to_float(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        payload = raw_balance
        if isinstance(raw_balance, dict) and "data" in raw_balance:
            payload = raw_balance.get("data") or {}

        summary: Dict[str, Any] = {}
        assets: List[Dict[str, Any]] = []

        if isinstance(payload, dict):
            assets = payload.get("assets") or []
            summary = payload
        elif isinstance(payload, list):
            assets = payload

        if assets and not summary:
            primary = assets[0]
            summary = {
                "totalWalletBalance": primary.get("walletBalance"),
                "availableBalance": primary.get("availableBalance", primary.get("walletBalance")),
                "totalMarginBalance": primary.get("marginBalance"),
                "totalUnrealizedProfit": primary.get("unrealizedProfit"),
                "totalInitialMargin": primary.get("initialMargin"),
                "totalOpenOrderInitialMargin": primary.get("openOrderInitialMargin"),
                "totalPositionInitialMargin": primary.get("positionInitialMargin"),
            }

        result = {
            "total_wallet_balance": _to_float(summary.get("totalWalletBalance")),
            "available_balance": _to_float(summary.get("availableBalance")),
            "total_margin_balance": _to_float(summary.get("totalMarginBalance")),
            "total_unrealized_pnl": _to_float(summary.get("totalUnrealizedProfit")),
            "total_initial_margin": _to_float(summary.get("totalInitialMargin")),
            "total_open_order_margin": _to_float(summary.get("totalOpenOrderInitialMargin")),
            "total_position_margin": _to_float(summary.get("totalPositionInitialMargin")),
            "account_value": _to_float(summary.get("totalWalletBalance")),
            "assets": assets,
        }
        return result

    def get_positions_summary(self) -> List[Dict[str, Any]]:
        try:
            return self.client.position_risk()
        except Exception as exc:  # pragma: no cover - defensive
            return [{"error": str(exc)}]

    def positions_count(self) -> int:
        positions = self.get_positions_summary()
        count = 0
        for position in positions:
            try:
                qty = float(position.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty != 0:
                count += 1
        return count

    def get_equity_based_usdc_amount(
        self,
        *,
        percentage: float,
        base_amount: float = 1.0,
        leverage: float = 1.0,
    ) -> float:
        balance = self._get_balance()
        wallet_balance = self.compute_account_value(
            balance_data=balance,
            collateral_assets=("USDC", "USDT", "USDF", "USDBC", "USD1", "CUSDT", "VUSDT"),
        )
        notional = wallet_balance * max(percentage, 0.0) * max(leverage, 0.0)
        return max(notional, base_amount)

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------
    def drop_duplicate_signals(self, signals: Sequence[KolSignal]) -> List[KolSignal]:
        unique: Dict[str, KolSignal] = {}
        for signal in signals:
            unique[signal.symbol] = signal
        return list(unique.values())

    def filter_out_position_in_portfolio(
        self,
        signals: Sequence[KolSignal],
        holding_positions: Iterable[Dict[str, Any]],
    ) -> List[KolSignal]:
        def _normalize(symbol: str) -> str:
            if not symbol:
                return ""
            cleaned = symbol.upper()
            if "/" in cleaned:
                cleaned = cleaned.split("/", 1)[0]
            if ":" in cleaned:
                cleaned = cleaned.split(":", 1)[0]
            for suffix in ("USDT", "USDC", "USD"):
                if cleaned.endswith(suffix):
                    cleaned = cleaned[: -len(suffix)]
                    break
            return cleaned

        open_symbols = {
            _normalize(pos.get("symbol", ""))
            for pos in holding_positions
            if isinstance(pos, dict) and pos.get("symbol")
        }

        filtered: List[KolSignal] = []
        for signal in signals:
            normalized_signal = _normalize(signal.symbol)
            if normalized_signal and normalized_signal in open_symbols:
                continue
            filtered.append(signal)
        return filtered

    def categorize_signals(
        self,
        candidate_signals: Sequence[KolSignal],
        holding_positions: Iterable[Dict[str, Any]],
    ) -> Tuple[List[KolSignal], List[KolSignal]]:
        # Placeholder: treat all incoming signals as new openings, none for closing.
        return list(candidate_signals), []

    def filter_open_positions(
        self,
        positions: Iterable[Dict[str, Any]],
        eps: float = 1e-9,
    ) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for pos in positions:
            try:
                qty = float(pos.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                qty = 0.0
            if abs(qty) <= eps:
                continue

            if self._wallet_created_at_ms is not None:
                symbol = str(pos.get("symbol", "")).upper()
                if not symbol:
                    continue
                if not self._has_trade_activity_after_cutoff(symbol, self._wallet_created_at_ms):
                    continue

            result.append(pos)
        return result

    def _has_trade_activity_after_cutoff(self, symbol: str, cutoff_ms: int) -> bool:
        api_symbol = self._normalize_symbol_for_api(symbol)
        if api_symbol is None:
            return True
        cached = self._activity_cache.get(api_symbol)
        if cached is not None:
            return cached
        try:
            trades = self.client.user_trades(symbol=api_symbol, start_time=cutoff_ms, limit=1)  # type: ignore[arg-type]
        except Exception:
            self._activity_cache[api_symbol] = True
            return True
        if not isinstance(trades, list):
            self._activity_cache[api_symbol] = True
            return True
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            trade_time = self._safe_int(
                trade.get("time")
                or trade.get("updateTime")
                or trade.get("T")
                or trade.get("timestamp")
            )
            if trade_time is not None and trade_time >= cutoff_ms:
                self._activity_cache[api_symbol] = True
                return True
        self._activity_cache[api_symbol] = False
        return False

    @staticmethod
    def _normalize_symbol_for_api(symbol: str) -> Optional[str]:
        if not symbol:
            return None
        cleaned = symbol.upper()
        for delimiter in ("/", "-", ":"):
            if delimiter in cleaned:
                base, quote = cleaned.split(delimiter, 1)
                cleaned = f"{base}{quote}"
                break
        return cleaned or None

    @staticmethod
    def _to_epoch_ms(value: datetime | str | None) -> Optional[int]:
        if value is None:
            return None
        dt: datetime
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if not text:
                return None
            text = text.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
