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
        description="Open delta-neutral spread: Long Asterdex / Short Hyperliquid with limit + slippage buffer."
    )
    parser.add_argument("symbol", help="Base symbol, e.g., HEMI")
    parser.add_argument("notional", type=float, help="Notional per leg in quote (USDT/USDC), e.g., 500")
    args = parser.parse_args()

    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()
    execu = ExecutionManager()

    print(f"[Open] symbol={args.symbol} notional={args.notional}")
    res = execu.open_spread(args.symbol, args.notional, exchange_long=aster, exchange_short=hyper)
    print(res)


if __name__ == "__main__":
    main()
