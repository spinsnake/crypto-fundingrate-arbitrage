import requests
import pandas as pd
import json
import time
from datetime import datetime

# --- Configuration ---
SYMBOLS = ["APT", "ATOM", "DOT"]
ASTERDEX_API_URL = "https://fapi.asterdex.com"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"
DAYS_TO_BACKTEST = 30

def get_timestamp_ms_ago(days):
    return int((time.time() - (days * 24 * 60 * 60)) * 1000)

def fetch_asterdex_history(symbol):
    endpoint = "/fapi/v3/fundingRate"
    pair = f"{symbol}USDT"
    start_time = get_timestamp_ms_ago(DAYS_TO_BACKTEST)
    
    params = {
        "symbol": pair,
        "startTime": start_time,
        "limit": 1000 
    }
    try:
        response = requests.get(f"{ASTERDEX_API_URL}{endpoint}", params=params)
        data = response.json()
        df = pd.DataFrame(data)
        if df.empty: return pd.DataFrame()
        
        df['fundingTime'] = pd.to_numeric(df['fundingTime'])
        df['fundingRate'] = pd.to_numeric(df['fundingRate'])
        df = df.rename(columns={'fundingTime': 'time', 'fundingRate': 'rate'})
        df['source'] = 'Asterdex'
        return df[['time', 'rate', 'source']]
    except Exception as e:
        print(f"[Asterdex] Error: {e}")
        return pd.DataFrame()

def fetch_hyperliquid_history(symbol):
    endpoint = "/info"
    start_time = get_timestamp_ms_ago(DAYS_TO_BACKTEST)
    payload = {
        "type": "fundingHistory",
        "coin": symbol,
        "startTime": start_time
    }
    try:
        response = requests.post(f"{HYPERLIQUID_API_URL}{endpoint}", json=payload)
        data = response.json()
        df = pd.DataFrame(data)
        if df.empty: return pd.DataFrame()
        
        df['time'] = pd.to_numeric(df['time'])
        df['fundingRate'] = pd.to_numeric(df['fundingRate'])
        df = df.rename(columns={'fundingRate': 'rate'})
        df['source'] = 'Hyperliquid'
        return df[['time', 'rate', 'source']]
    except Exception as e:
        print(f"[Hyperliquid] Error: {e}")
        return pd.DataFrame()

def run_backtest():
    print("--- Starting Backtest (User Mode) ---")
    final_results = {}
    
    for symbol in SYMBOLS:
        print(f"\nProcessing {symbol}...")
        
        # Fetch
        df_aster = fetch_asterdex_history(symbol)
        df_hl = fetch_hyperliquid_history(symbol)
        
        if df_aster.empty or df_hl.empty:
            print(f"Skipping {symbol} (No Data)")
            continue
            
        # Merge & Align
        # Sort by time
        df_aster = df_aster.sort_values('time')
        df_hl = df_hl.sort_values('time')
        
        # Use merge_asof to find nearest timestamp
        df_merged = pd.merge_asof(
            df_aster, 
            df_hl, 
            on='time', 
            suffixes=('_aster', '_hl'),
            direction='nearest',
            tolerance=3600000 # 1 hour tolerance
        )
        
        # Calculate Spread
        df_merged['spread'] = (df_merged['rate_aster'] - df_merged['rate_hl']).abs()
        
        # Calculate Cumulative PnL
        df_merged['cum_pnl'] = df_merged['spread'].cumsum()
        
        # Stats
        total_pnl = df_merged['spread'].sum()
        days = (df_merged['time'].max() - df_merged['time'].min()) / (1000 * 60 * 60 * 24)
        if days < 1: days = 1
        monthly_proj = (total_pnl / days) * 30
        
        result_data = {
            "symbol": symbol,
            "total_pnl_percent": total_pnl * 100,
            "days_analyzed": days,
            "monthly_projected_percent": monthly_proj * 100,
            "data_points": len(df_merged)
        }
        final_results[symbol] = result_data
        
        print(f"  -> Total PnL: {total_pnl*100:.2f}%")
        print(f"  -> Monthly Proj: {monthly_proj*100:.2f}%")

    # Save to JSON
    with open('backtest_results.json', 'w') as f:
        json.dump(final_results, f, indent=4)
    print("\n[SUCCESS] Results saved to 'backtest_results.json'")

if __name__ == "__main__":
    run_backtest()
