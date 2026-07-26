import ccxt

print("Testing CCXT Binance Futures Connection...")
try:
    exchange = ccxt.binanceusdm({'enableRateLimit': True})
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='5m', limit=3)
    print("CCXT Binance Futures Data:", ohlcv)
except Exception as e:
    print("Binance Futures CCXT Error:", e)
    # Try OKX or Bybit if Binance WAF blocks IP
    print("Testing Bybit/OKX CCXT fallback...")
    try:
        bybit = ccxt.bybit({'enableRateLimit': True})
        ohlcv_bybit = bybit.fetch_ohlcv('BTC/USDT', timeframe='5m', limit=3)
        print("Bybit Futures Data:", ohlcv_bybit)
    except Exception as ex:
        print("Bybit Error:", ex)
