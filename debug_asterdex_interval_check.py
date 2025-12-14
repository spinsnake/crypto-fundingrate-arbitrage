
import requests
import time
import math

def verify_interval_logic():
    url = "https://fapi.asterdex.com/fapi/v3/premiumIndex"
    try:
        print("Fetching Premium Index...")
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        candidates = ["TNSRUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
        
        current_ts = int(time.time() * 1000)
        
        print(f"Current Time: {current_ts} (UTC: {time.gmtime(current_ts/1000).tm_hour}:{time.gmtime(current_ts/1000).tm_min})")
        print("-" * 50)
        
        for item in data:
            sym = item.get('symbol')
            if sym not in candidates:
                continue
                
            nft = int(item.get('nextFundingTime', 0))
            if nft == 0:
                print(f"{sym}: No nextFundingTime")
                continue

            # Check alignment with 8h (00, 08, 16 UTC)
            # 8h in ms = 8 * 3600 * 1000 = 28800000
            # Timestamp % (24h) 
            # Actually just check hour of day
            nft_sec = nft / 1000
            struct = time.gmtime(nft_sec)
            hour = struct.tm_hour
            
            is_8h_boundary = (hour % 8 == 0) and (struct.tm_min == 0)
            
            interval_str = "8h (Standard)" if is_8h_boundary else "1h (Non-Standard)"
            factor = 1 if is_8h_boundary else 8
            
            print(f"Symbol: {sym}")
            print(f"  Next Funding: {struct.tm_hour:02d}:{struct.tm_min:02d} UTC")
            print(f"  Is 8h Boundary? {is_8h_boundary}")
            print(f"  Duced Interval: {interval_str}")
            print(f"  Normalization Factor: x{factor}")
            print("-" * 20)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify_interval_logic()
