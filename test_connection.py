import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure src is importable
ROOT = Path(__file__).parent
sys.path.append(str(ROOT))

load_dotenv()

from src.adapters.asterdex import AsterdexAdapter  # noqa: E402
from src.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402


def main():
    aster = AsterdexAdapter()
    hyper = HyperliquidAdapter()

    print("[Test] Asterdex connection:", "OK" if aster.test_connection() else "FAIL")
    print("[Test] Hyperliquid connection:", "OK" if hyper.test_connection() else "FAIL")


if __name__ == "__main__":
    main()
