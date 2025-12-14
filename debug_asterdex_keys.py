
import requests
import json

def check_all_keys():
    url = "https://fapi.asterdex.com/fapi/v3/exchangeInfo"
    try:
        print("Fetching Exchange Info...")
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        symbols = data.get('symbols', [])
        if not symbols:
            print("No symbols found.")
            return

        # Check the first symbol in detail
        first_sym = symbols[0]
        print(f"First Symbol JSON: {json.dumps(first_sym, indent=2)}")

            
        # Check if any symbol has a different structure regarding funding
        print(f"\nScanning {len(symbols)} symbols for 'funding' keywords in keys...")
        found_keys = set()
        for s in symbols:
            for k in s.keys():
                if 'fund' in k.lower() or 'interval' in k.lower() or 'period' in k.lower():
                    found_keys.add(k)
        
        print(f"Found potential keys: {found_keys}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_all_keys()
