import requests
import pandas as pd
import time

# --- Configuration ---
from src.config import (
    ASTERDEX_API_URL,
    HYPERLIQUID_API_URL,
    MIN_VOLUME_USDT,
    TARGET_MONTHLY_RETURN,
    MIN_MONTHLY_RETURN,
)

def fetch_asterdex_all_funding():
    """Fetch funding rates for ALL symbols from Asterdex"""
    endpoint = "/fapi/v3/premiumIndex"
    try:
        # Calling without symbol parameter to get all
        response = requests.get(f"{ASTERDEX_API_URL}{endpoint}")
        response.raise_for_status()
        data = response.json()
        
        rates = {}
        for item in data:
            symbol = item['symbol']
            # Asterdex symbols are like BTCUSDT. Remove USDT to match HL.
            if symbol.endswith("USDT"):
                base_symbol = symbol[:-4]
                rates[base_symbol] = {
                    'rate': float(item.get('lastFundingRate', 0)),
                    'mark_price': float(item.get('markPrice', 0))
                }
        return rates
    except Exception as e:
        print(f"[Asterdex] Error fetching all funding: {e}")
        return {}

def fetch_hyperliquid_all_funding():
    """Fetch funding rates for ALL symbols from Hyperliquid"""
    endpoint = "/info"
    payload = {"type": "metaAndAssetCtxs"}
    try:
        response = requests.post(f"{HYPERLIQUID_API_URL}{endpoint}", json=payload)
        response.raise_for_status()
        data = response.json()
        
        universe = data[0]["universe"]
        asset_ctxs = data[1]
        
        rates = {}
        for i, asset in enumerate(universe):
            name = asset["name"]
            ctx = asset_ctxs[i]
            
            # Check volume (approximate via dayNtlVlm which is notional volume)
            # Hyperliquid API structure might vary, relying on 'dayNtlVlm' if available or just proceed
            # For now, we'll just get the rate and filter later if we can get volume data
            
            rates[name] = {
                'rate': float(ctx.get('funding', 0)),
                'mark_price': float(ctx.get('markPx', 0))
                # 'volume': float(ctx.get('dayNtlVlm', 0)) # If available
            }
        return rates
    except Exception as e:
        print(f"[Hyperliquid] Error fetching all funding: {e}")
        return {}

def main():
    print("--- Starting Funding Rate Scanner ---")
    print(f"Target: > {TARGET_MONTHLY_RETURN}% Monthly Return")
    min_return = MIN_MONTHLY_RETURN / 100
    
    # 1. Fetch Data
    print("Fetching Asterdex data...")
    aster_data = fetch_asterdex_all_funding()
    print(f"Got {len(aster_data)} symbols from Asterdex")
    
    print("Fetching Hyperliquid data...")
    hl_data = fetch_hyperliquid_all_funding()
    print(f"Got {len(hl_data)} symbols from Hyperliquid")
    
    # 2. Match & Calculate
    opportunities = []
    
    # Iterate through common symbols
    common_symbols = set(aster_data.keys()) & set(hl_data.keys())
    print(f"Analyzing {len(common_symbols)} common pairs...")
    
    for symbol in common_symbols:
        aster = aster_data[symbol]
        hl = hl_data[symbol]
        
        aster_rate = aster['rate']
        hl_rate = hl['rate']
        
        # Calculate Diff
        diff = abs(aster_rate - hl_rate)
        
        # Project Returns
        daily_return = diff * 3
        monthly_return = daily_return * 30
        
        # Determine Strategy Direction
        # If HL > Aster: Short HL (Receive), Long Aster (Pay)
        # If Aster > HL: Short Aster (Receive), Long HL (Pay)
        if hl_rate > aster_rate:
            direction = "Short HL / Long Aster"
            net_rate_per_round = hl_rate - aster_rate
        else:
            direction = "Short Aster / Long HL"
            net_rate_per_round = aster_rate - hl_rate
            
        # Filter by minimum monthly return (config-driven)
        if monthly_return > min_return:
            opportunities.append({
                'Symbol': symbol,
                'Monthly %': round(monthly_return * 100, 2),
                'Daily %': round(daily_return * 100, 2),
                'Spread (8h)': round(net_rate_per_round * 100, 4),
                'Direction': direction,
                'Aster Rate': aster_rate,
                'HL Rate': hl_rate,
                'Price': hl['mark_price']
            })
    
    # 3. Display Results
    if not opportunities:
        print("No opportunities found matching criteria.")
        return

    df = pd.DataFrame(opportunities)
    df = df.sort_values(by='Monthly %', ascending=False)
    
    print("\n--- Top Opportunities ---")
    # Adjust pandas display
    pd.set_option('display.max_rows', None)
    pd.set_option('display.width', 1000)
    pd.set_option('display.max_columns', None)
    
    print(df[['Symbol', 'Monthly %', 'Spread (8h)', 'Direction', 'Price']].head(20))
    
    # Save to CSV
    df.to_csv("funding_opportunities.csv", index=False)
    print("\nFull results saved to 'funding_opportunities.csv'")

if __name__ == "__main__":
    main()
