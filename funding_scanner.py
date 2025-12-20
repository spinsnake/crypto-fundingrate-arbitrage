import pandas as pd

from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.adapters.lighter import LighterAdapter
from src.config import (
    TARGET_MONTHLY_RETURN,
    MIN_MONTHLY_RETURN,
    SCAN_EXCHANGES,
    ENABLE_VOLUME_FILTER,
    ENABLE_DELIST_FILTER,
    MIN_VOLUME_ASTER_USDT,
    MIN_VOLUME_HL_USDT,
    MIN_VOLUME_LIGHTER_USDT,
)

EXCHANGE_REGISTRY = {
    "asterdex": {"name": "Asterdex", "adapter": AsterdexAdapter, "min_volume": MIN_VOLUME_ASTER_USDT},
    "hyperliquid": {"name": "Hyperliquid", "adapter": HyperliquidAdapter, "min_volume": MIN_VOLUME_HL_USDT},
    "lighter": {"name": "Lighter", "adapter": LighterAdapter, "min_volume": MIN_VOLUME_LIGHTER_USDT},
}


def _resolve_scan_exchange_keys() -> list[str]:
    keys = [str(k).lower() for k in SCAN_EXCHANGES]
    keys = [k for k in keys if k in EXCHANGE_REGISTRY]
    if len(keys) != 2 or len(set(keys)) != 2:
        print("[Config] SCAN_EXCHANGES invalid. Using ['hyperliquid', 'asterdex'].")
        return ["hyperliquid", "asterdex"]
    return keys

def main():
    print("--- Starting Funding Rate Scanner ---")
    print(f"Target: > {TARGET_MONTHLY_RETURN}% Monthly Return")
    min_return = MIN_MONTHLY_RETURN / 100
    
    # 1. Fetch Data
    ex_keys = _resolve_scan_exchange_keys()
    ex_a_key, ex_b_key = ex_keys[0], ex_keys[1]
    ex_a_cfg = EXCHANGE_REGISTRY[ex_a_key]
    ex_b_cfg = EXCHANGE_REGISTRY[ex_b_key]
    ex_a_name = ex_a_cfg["name"]
    ex_b_name = ex_b_cfg["name"]
    print(f"Pair: {ex_a_name} vs {ex_b_name}")

    ex_a = ex_a_cfg["adapter"]()
    ex_b = ex_b_cfg["adapter"]()

    print(f"Fetching {ex_a_name} data...")
    ex_a_data = ex_a.get_all_funding_rates()
    print(f"Got {len(ex_a_data)} symbols from {ex_a_name}")
    
    print(f"Fetching {ex_b_name} data...")
    ex_b_data = ex_b.get_all_funding_rates()
    print(f"Got {len(ex_b_data)} symbols from {ex_b_name}")
    
    # 2. Match & Calculate
    opportunities = []
    
    # Iterate through common symbols
    common_symbols = set(ex_a_data.keys()) & set(ex_b_data.keys())
    print(f"Analyzing {len(common_symbols)} common pairs...")
    
    for symbol in common_symbols:
        rate_a = ex_a_data[symbol]
        rate_b = ex_b_data[symbol]

        if ENABLE_DELIST_FILTER:
            if not rate_a.is_active or not rate_b.is_active:
                continue

        if ENABLE_VOLUME_FILTER:
            min_a = ex_a_cfg["min_volume"]
            min_b = ex_b_cfg["min_volume"]
            if min_a and rate_a.volume_24h < min_a:
                continue
            if min_b and rate_b.volume_24h < min_b:
                continue
        
        # Calculate Diff
        diff = abs(rate_a.rate - rate_b.rate)
        
        # Project Returns
        daily_return = diff * 3
        monthly_return = daily_return * 30
        
        # Determine Strategy Direction
        # If HL > Aster: Short HL (Receive), Long Aster (Pay)
        # If Aster > HL: Short Aster (Receive), Long HL (Pay)
        if rate_b.rate > rate_a.rate:
            direction = f"Short {ex_b_name} / Long {ex_a_name}"
            net_rate_per_round = rate_b.rate - rate_a.rate
        else:
            direction = f"Short {ex_a_name} / Long {ex_b_name}"
            net_rate_per_round = rate_a.rate - rate_b.rate
            
        # Filter by minimum monthly return (config-driven)
        if monthly_return > min_return:
            opportunities.append({
                'Symbol': symbol,
                'Monthly %': round(monthly_return * 100, 2),
                'Daily %': round(daily_return * 100, 2),
                'Spread (8h)': round(net_rate_per_round * 100, 4),
                'Direction': direction,
                f'{ex_a_name} Rate': rate_a.rate,
                f'{ex_b_name} Rate': rate_b.rate,
                f'{ex_a_name} Price': rate_a.mark_price,
                f'{ex_b_name} Price': rate_b.mark_price,
                f'{ex_a_name} Vol': round(rate_a.volume_24h, 2),
                f'{ex_b_name} Vol': round(rate_b.volume_24h, 2),
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
    
    display_cols = [
        'Symbol',
        'Monthly %',
        'Spread (8h)',
        'Direction',
        f'{ex_a_name} Rate',
        f'{ex_b_name} Rate',
        f'{ex_a_name} Price',
        f'{ex_b_name} Price',
    ]
    print(df[display_cols].head(20))
    
    # Save to CSV
    df.to_csv("funding_opportunities.csv", index=False)
    print("\nFull results saved to 'funding_opportunities.csv'")

if __name__ == "__main__":
    main()
