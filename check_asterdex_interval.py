
import requests
import json

def check_funding_interval():
    url = "https://fapi.asterdex.com/fapi/v3/exchangeInfo"
    try:
        print("Fetching Exchange Info...")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # Check first few symbols
        for s in data['symbols'][:5]:
            print(f"Symbol: {s['symbol']}")
            # Print keys that might contain funding info
            print(f"  Funding Interval: {s.get('fundingIntervalHours', 'Not Found')}")
            print(f"  MsgAuth: {s.get('msgAuth', 'N/A')}") # Sometimes hidden here
            
            # Print raw keys to see if we missed anything obvious
            # print(f"  Keys: {list(s.keys())}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_funding_interval()
