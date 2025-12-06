import requests
import json
import time

# --- Configuration ---
SYMBOL = "ETH" # Test symbol
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"

def fetch_asterdex_funding(symbol):
    """Fetch current funding rate from Asterdex V3"""
    endpoint = "/fapi/v3/premiumIndex"
    # Asterdex uses USDT pairs usually, e.g., ETHUSDT
    pair = f"{symbol}USDT" 
    try:
        response = requests.get(f"{ASTERDEX_API_URL}{endpoint}", params={"symbol": pair})
        response.raise_for_status()
        data = response.json()
        # Data format: {"symbol": "ETHUSDT", "lastFundingRate": "0.0001", ...}
        return float(data.get("lastFundingRate", 0))
    except Exception as e:
        print(f"[Asterdex] Error fetching funding: {e}")
        return None

def fetch_hyperliquid_funding(symbol):
    """Fetch current funding rate from Hyperliquid"""
    endpoint = "/info"
    payload = {"type": "metaAndAssetCtxs"}
    try:
        response = requests.post(f"{HYPERLIQUID_API_URL}{endpoint}", json=payload)
        response.raise_for_status()
        data = response.json()
        # Parse response to find the symbol
        universe = data[0]["universe"]
        asset_ctxs = data[1]
        
        # Find index of symbol
        try:
            idx = next(i for i, asset in enumerate(universe) if asset["name"] == symbol)
            funding_rate = float(asset_ctxs[idx]["funding"])
            return funding_rate
        except StopIteration:
            print(f"[Hyperliquid] Symbol {symbol} not found")
            return None
    except Exception as e:
        print(f"[Hyperliquid] Error fetching funding: {e}")
        return None

def main():
    print(f"--- Starting POC for {SYMBOL} ---")
    
    # 1. Fetch Asterdex
    print("Fetching Asterdex Data...")
    aster_rate = fetch_asterdex_funding(SYMBOL)
    print(f"Asterdex Funding Rate: {aster_rate}")

    # 2. Fetch Hyperliquid
    print("Fetching Hyperliquid Data...")
    hl_rate = fetch_hyperliquid_funding(SYMBOL)
    print(f"Hyperliquid Funding Rate: {hl_rate}")

    # 3. Compare
    if aster_rate is not None and hl_rate is not None:
        diff = abs(aster_rate - hl_rate)
        print(f"\n--- Result ---")
        print(f"Funding Diff: {diff:.6f}")
        
        # Simple Strategy Check
        # If HL > Aster: Short HL, Long Aster
        if hl_rate > aster_rate:
            print(f"Strategy: Short Hyperliquid ({hl_rate}) / Long Asterdex ({aster_rate})")
            print(f"Potential Profit: {hl_rate - aster_rate:.6f} per 8h")
        else:
            print(f"Strategy: Short Asterdex ({aster_rate}) / Long Hyperliquid ({hl_rate})")
            print(f"Potential Profit: {aster_rate - hl_rate:.6f} per 8h")
    else:
        print("\n[Error] Could not fetch data from both exchanges.")

if __name__ == "__main__":
    main()
