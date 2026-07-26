import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

url_us = "https://api.binance.us/api/v3/klines"
params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 3}

try:
    r = requests.get(url_us, params=params, headers=headers, timeout=5)
    print("Binance US Status:", r.status_code)
    print("Binance US Data:", r.json()[:1])
except Exception as e:
    print("Binance US Error:", e)

url_cg = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true"
try:
    r2 = requests.get(url_cg, headers=headers, timeout=5)
    print("CoinGecko Status:", r2.status_code)
    print("CoinGecko Data:", r2.json())
except Exception as e:
    print("CoinGecko Error:", e)
