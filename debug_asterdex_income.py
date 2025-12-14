
import os
import time
import hmac
import hashlib
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("asterdex_api_key")
API_SECRET = os.getenv("asterdex_api_secret")
BASE_URL = "https://fapi.asterdex.com"

def get_income():
    symbol = "TNSRUSDT"
    endpoint = "/fapi/v1/income"
    # Look back 24 hours
    start_time = int((time.time() - 24*3600) * 1000)
    end_time = int(time.time() * 1000)
    timestamp = int(time.time() * 1000)
    
    params = {
        "symbol": symbol,
        "incomeType": "FUNDING_FEE",
        "startTime": start_time,
        "endTime": end_time,
        "limit": 50,
        "timestamp": timestamp,
        "recvWindow": 5000
    }
    
    query = urllib.parse.urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BASE_URL}{endpoint}?{query}&signature={signature}"
    
    headers = {"X-MBX-APIKEY": API_KEY}
    
    print(f"Fetching income for {symbol}...")
    try:
        resp = requests.get(url, headers=headers)
        print(f"Status: {resp.status_code}")
        data = resp.json()
        for item in data:
            print(f"Time: {item.get('time')} | Income: {item.get('income')} | Asset: {item.get('asset')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_income()
