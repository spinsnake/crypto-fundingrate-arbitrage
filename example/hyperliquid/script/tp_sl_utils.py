"""
TP/SL calculation utilities for Privy trading.
Consolidates all take-profit and stop-loss calculation logic.
"""

from typing import Dict, Tuple
from trading_core.log.logger import logger


def calculate_tp_sl_prices(
    entry_price: float,
    side: str,
    tp_percentage: float = 3.0,
    sl_percentage: float = 4.0,
) -> Tuple[float, float]:
    """
    Calculate take-profit and stop-loss prices based on entry price and percentages.
    
    Args:
        entry_price: Entry price of the position
        side: 'buy' or 'sell' indicating position direction
        tp_percentage: Take-profit percentage (e.g., 3.0 for 3%)
        sl_percentage: Stop-loss percentage (e.g., 4.0 for 4%)
    
    Returns:
        Tuple of (tp_price, sl_price)
    """
    if side.lower() == "buy":
        tp_price = entry_price * (1 + tp_percentage / 100)
        sl_price = entry_price * (1 - sl_percentage / 100)
    elif side.lower() == "sell":
        tp_price = entry_price * (1 - tp_percentage / 100)
        sl_price = entry_price * (1 + sl_percentage / 100)
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'.")
    
    # Round to 4 decimal places for crypto prices
    tp_price = round(tp_price, 4)
    sl_price = round(sl_price, 4)
    
    logger.info(f"Calculated TP/SL: TP=${tp_price}, SL=${sl_price}")
    return tp_price, sl_price


def calculate_tp_sl_from_config(
    entry_price: float,
    side: str,
    wallet_config: Dict,
    symbol: str = None,
) -> Tuple[float, float]:
    """
    Calculate TP/SL prices using wallet configuration.
    
    Args:
        entry_price: Entry price of the position
        side: 'buy' or 'sell' indicating position direction
        wallet_config: Wallet configuration dictionary
        symbol: Optional symbol for logging
    
    Returns:
        Tuple of (tp_price, sl_price)
    """
    # Get TP/SL percentages from config with defaults
    tp_percentage = float(wallet_config.get("tp_percentage", 3.0))
    sl_percentage = float(wallet_config.get("sl_percentage", 4.0))
    
    tp_price, sl_price = calculate_tp_sl_prices(
        entry_price=entry_price,
        side=side,
        tp_percentage=tp_percentage,
        sl_percentage=sl_percentage,
    )
    
    symbol_msg = f" for {symbol}" if symbol else ""
    logger.info(
        f"Calculated TP/SL{symbol_msg} from wallet config: "
        f"SL=${sl_price} ({sl_percentage}%), TP=${tp_price} ({tp_percentage}%)"
    )
    
    return tp_price, sl_price


def validate_tp_sl_prices(
    entry_price: float,
    tp_price: float,
    sl_price: float,
    side: str,
) -> bool:
    """
    Validate that TP and SL prices are properly positioned relative to entry price.
    
    Args:
        entry_price: Entry price of the position
        tp_price: Take-profit price
        sl_price: Stop-loss price
        side: 'buy' or 'sell' indicating position direction
    
    Returns:
        True if prices are valid, False otherwise
    """
    if side.lower() == "buy":
        # For long positions: SL < Entry < TP
        is_valid = sl_price < entry_price < tp_price
    elif side.lower() == "sell":
        # For short positions: TP < Entry < SL
        is_valid = tp_price < entry_price < sl_price
    else:
        return False
    
    if not is_valid:
        logger.warning(
            f"Invalid TP/SL configuration: "
            f"Entry=${entry_price}, TP=${tp_price}, SL=${sl_price}, Side={side}"
        )
    
    return is_valid