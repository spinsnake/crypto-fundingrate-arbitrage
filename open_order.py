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
from src.core.execution_manager import ExecutionManager  # noqa: E402

SYMBOL = "MOODENG"
NOTIONAL = 560  # per leg in quote (USDT/USDC)


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


def main():
    ok, mins, target_str = within_window_bkk()
    if not ok:
        print(f"[Open] Too early. Next payout {target_str} BKK in {mins:.1f} mins. Allowed window: last 30 mins before payout.")
        return

    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()
    execu = ExecutionManager()

    print(f"[Open] symbol={SYMBOL} notional={NOTIONAL} (next payout {target_str} BKK in {mins:.1f} mins)")
    res = execu.open_spread(SYMBOL, NOTIONAL, exchange_long=aster, exchange_short=hyper)
    # Summarize per exchange
    long_res = res.get("long", {})
    short_res = res.get("short", {})
    aster_status = long_res.get("status", long_res.get("response", {}).get("status", "unknown"))
    hyper_status = short_res.get("status", short_res.get("response", {}).get("status", "unknown"))
    print(f"[Summary] Asterdex open: {aster_status}")
    print(f"[Summary] Hyperliquid open: {hyper_status}")
    print(res)


if __name__ == "__main__":
    main()
