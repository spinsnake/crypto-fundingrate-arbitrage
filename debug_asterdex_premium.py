
import requests
import json
import time

def check_premium_index():
    url = "https://fapi.asterdex.com/fapi/v3/premiumIndex"
    try:
        print("Fetching Premium Index...")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        print(f"Total symbols: {len(data)}")
        
        target_symbols = ["TNSRUSDT", "BTCUSDT", "ETHUSDT"]
        
        for item in data:
            sym = item.get('symbol')
            if sym in target_symbols:
                nft = int(item.get('nextFundingTime', 0))
                print(f"Symbol: {sym}")
                print(f"  Next Funding Time: {nft}")
                
                # Human readable
                remaining_ms = nft - int(time.time()*1000)
                remaining_hrs = remaining_ms / 1000 / 3600
                print(f"  Remaining Hours: {remaining_hrs:.4f}")
                
                # Check alignment
                # 8h intervals are at 00, 08, 16 UTC. 
                # UTC time of nft:
                nft_sec = nft / 1000
                struct = time.gmtime(nft_sec)
                print(f"  UTC Time: {struct.tm_hour:02d}:{struct.tm_min:02d}")


    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_premium_index()
