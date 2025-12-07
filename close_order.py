import sys
from pathlib import Path
import argparse
from dotenv import load_dotenv

# Make src importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from src.core.execution_manager import ExecutionManager  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Close delta-neutral spread: Sell Asterdex long / Buy back Hyperliquid short with limit + slippage buffer."
    )
    parser.add_argument("symbol", help="Base symbol, e.g., HEMI")
    parser.add_argument("qty_long", type=float, help="Quantity to close on Asterdex (long leg), base units")
    parser.add_argument("qty_short", type=float, help="Quantity to close on Hyperliquid (short leg), base units")
    args = parser.parse_args()

    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()
    execu = ExecutionManager()

    print(f"[Close] symbol={args.symbol} qty_long={args.qty_long} qty_short={args.qty_short}")
    res = execu.close_spread(
        args.symbol,
        qty_long=args.qty_long,
        qty_short=args.qty_short,
        exchange_long=aster,
        exchange_short=hyper,
    )
    print(res)


if __name__ == "__main__":
    main()
