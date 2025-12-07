import sys
from pathlib import Path
from dotenv import load_dotenv

# Make src importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from src.core.execution_manager import ExecutionManager  # noqa: E402

SYMBOL = "MOODENG"
NOTIONAL = 520  # per leg in quote (USDT/USDC)

def main():
    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()
    execu = ExecutionManager()

    print(f"[Open] symbol={SYMBOL} notional={NOTIONAL}")
    res = execu.open_spread(SYMBOL, NOTIONAL, exchange_long=aster, exchange_short=hyper)
    print(res)


if __name__ == "__main__":
    main()
