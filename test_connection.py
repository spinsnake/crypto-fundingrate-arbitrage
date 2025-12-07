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
    try:
        aster = AsterdexAdapter()
    except Exception as e:
        print(f"[Test] Asterdex init failed: {e}")
        aster = None
    try:
        hyper = HyperliquidAdapter()
    except Exception as e:
        print(f"[Test] Hyperliquid init failed: {e}")
        hyper = None

    if aster:
        try:
            print("[Test] Asterdex connection:", "OK" if aster.test_connection() else "FAIL")
        except Exception as e:
            print(f"[Test] Asterdex connection check failed: {e}")
    else:
        print("[Test] Asterdex connection: FAIL (init error)")

    if hyper:
        try:
            hl_ok = hyper.test_connection()
            print("[Test] Hyperliquid connection:", "OK" if hl_ok else "FAIL")
            print(hyper.get_open_positions())
        except Exception as e:
            print(f"[Test] Hyperliquid connection check failed: {e}")
    else:
        print("[Test] Hyperliquid connection: FAIL (init error)")


if __name__ == "__main__":
    main()
    sys.exit(0)
