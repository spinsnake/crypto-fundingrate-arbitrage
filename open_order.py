import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Make src importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from src.adapters.lighter import LighterAdapter  # noqa: E402
from src.core.execution_manager import ExecutionManager  # noqa: E402
from src.config import DEFAULT_LEVERAGE, SAFETY_BUFFER  # noqa: E402

SYMBOL = "RESOLV"
# Fallback notional if balances not available
NOTIONAL_FALLBACK = 560  # per leg in quote
DIRECTION = "LONG_LIGHTER_SHORT_HL"  # See DIRECTION_MAP for options

EXCHANGE_REGISTRY = {
    "asterdex": AsterdexAdapter,
    "hyperliquid": HyperliquidAdapter,
    "lighter": LighterAdapter,
}

DIRECTION_MAP = {
    "LONG_HL_SHORT_ASTER": ("hyperliquid", "asterdex"),
    "LONG_ASTER_SHORT_HL": ("asterdex", "hyperliquid"),
    "LONG_LIGHTER_SHORT_HL": ("lighter", "hyperliquid"),
    "LONG_HL_SHORT_LIGHTER": ("hyperliquid", "lighter"),
    "LONG_LIGHTER_SHORT_ASTER": ("lighter", "asterdex"),
    "LONG_ASTER_SHORT_LIGHTER": ("asterdex", "lighter"),
}


def within_window_bkk(window_minutes: int = 30) -> tuple[bool, float, str]:
    targets = [7, 15, 23]
    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(timezone.utc).astimezone(bkk_tz)
    today = now_bkk.date()
    candidates = [
        datetime(year=today.year, month=today.month, day=today.day, hour=h, minute=0, tzinfo=bkk_tz)
        for h in targets
    ]
    next_dt = None
    for t in candidates:
        if t > now_bkk:
            next_dt = t
            break
    if next_dt is None:
        next_dt = datetime(year=today.year, month=today.month, day=today.day, hour=targets[0], minute=0, tzinfo=bkk_tz) + timedelta(days=1)
    diff_minutes = (next_dt - now_bkk).total_seconds() / 60
    return 0 <= diff_minutes <= window_minutes, diff_minutes, next_dt.strftime("%H:%M")


def _has_open_position(exchange, symbol: str) -> bool:
    try:
        positions = exchange.get_open_positions()
    except Exception as e:
        print(f"[Open] {exchange.get_name()} get_open_positions failed: {e}")
        return False
    sym = symbol.upper()
    for pos in positions:
        if str(pos.get("symbol", "")).upper() == sym and float(pos.get("quantity", 0) or 0) > 0:
            return True
    return False


def main():
    ok, mins, target_str = within_window_bkk()
    # if not ok:
    #     print(f"[Open] Too early. Next payout {target_str} BKK in {mins:.1f} mins. Allowed window: last 30 mins before payout.")
    #     return

    execu = ExecutionManager()
    exchanges = {key: cls() for key, cls in EXCHANGE_REGISTRY.items()}

    # Determine long/short based on DIRECTION
    if DIRECTION not in DIRECTION_MAP:
        raise ValueError(f"Unknown DIRECTION '{DIRECTION}'. Options: {list(DIRECTION_MAP.keys())}")
    long_key, short_key = DIRECTION_MAP[DIRECTION]
    exchange_long = exchanges[long_key]
    exchange_short = exchanges[short_key]
    long_name = exchange_long.get_name()
    short_name = exchange_short.get_name()

    if _has_open_position(exchange_long, SYMBOL) or _has_open_position(exchange_short, SYMBOL):
        print(f"[Open] {SYMBOL} already open on {long_name} or {short_name}. Skipping.")
        return

    # Auto-calc notional per leg from balances (use min equity across exchanges)
    bal_long = exchange_long.get_balance()
    bal_short = exchange_short.get_balance()
    notional = NOTIONAL_FALLBACK
    if bal_long > 0 and bal_short > 0:
        base_capital = min(bal_long, bal_short) * SAFETY_BUFFER
        notional = base_capital * DEFAULT_LEVERAGE
    print(f"[Open] symbol={SYMBOL} notional={notional:.2f} direction={DIRECTION}")
    print(
        f"[Open] Balances -> {long_name}: {bal_long:.4f}, {short_name}: {bal_short:.4f} "
        f"(leverage {DEFAULT_LEVERAGE}x, buffer {SAFETY_BUFFER*100:.0f}%)"
    )
    print(f"[Open] Long on {long_name}, Short on {short_name}")
    print(f"[Open] Next payout {target_str} BKK in {mins:.1f} mins")
    res = execu.open_spread(SYMBOL, notional, exchange_long=exchange_long, exchange_short=exchange_short)
    # Summarize per exchange
    long_res = res.get("long", {})
    short_res = res.get("short", {})
    long_status = long_res.get("status", long_res.get("response", {}).get("status", "unknown"))
    short_status = short_res.get("status", short_res.get("response", {}).get("status", "unknown"))
    print(f"[Summary] {long_name} open: {long_status}")
    print(f"[Summary] {short_name} open: {short_status}")
    print(res)


if __name__ == "__main__":
    main()
