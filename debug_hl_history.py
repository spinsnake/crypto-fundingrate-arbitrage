import requests
import json
import time

HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz"

def debug_hl():
    endpoint = "/info"
    # 30 days ago
    start_time = int((time.time() - (30 * 24 * 60 * 60)) * 1000)
    
    payload = {
        "type": "fundingHistory",
        "coin": "APT",
        "startTime": start_time
    }
    
    print(f"Fetching debug data for APT...")
    try:
        response = requests.post(f"{HYPERLIQUID_API_URL}{endpoint}", json=payload)
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            print("\n[SUCCESS] Got data. First record keys:")
            first_item = data[0]
            print(json.dumps(first_item, indent=4))
        else:
            print("\n[WARNING] Data is empty or not a list.")
            print(data)
            
    except Exception as e:
        print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    debug_hl()
