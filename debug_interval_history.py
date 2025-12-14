
import requests
import time

def check_funding_interval_history():
    base_url = "https://fapi.asterdex.com"
    endpoint = "/fapi/v1/fundingRate"
    
    symbols = ["TNSRUSDT", "BTCUSDT", "ETHUSDT"]
    
    for symbol in symbols:
        try:
            print(f"Checking {symbol}...")
            # Fetch last 2 funding rates
            params = {"symbol": symbol, "limit": 2}
            resp = requests.get(f"{base_url}{endpoint}", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if len(data) < 2:
                print(f"  Not enough history to determine interval.")
                continue
                
            t1 = data[-1]['fundingTime']
            t2 = data[-2]['fundingTime']
            
            diff_ms = t1 - t2
            diff_hours = diff_ms / 1000 / 3600
            
            print(f"  Last: {t1} | Prev: {t2}")
            print(f"  Diff: {diff_ms} ms = {diff_hours:.2f} hours")
            print(f"  Detected Interval: {int(round(diff_hours))}h")
            print("-" * 20)
            
        except Exception as e:
            print(f"Error checking {symbol}: {e}")

if __name__ == "__main__":
    check_funding_interval_history()
