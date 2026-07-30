import ccxt
import time

try:
    h = ccxt.hyperliquid()
    
    print("=== 🔶 BNB (LONG) ===")
    bnb_candles = h.fetch_ohlcv('BNB/USDC:USDC', '1m', limit=500)
    bnb_low = min([c[3] for c in bnb_candles])
    bnb_high = max([c[2] for c in bnb_candles])
    bnb_current = bnb_candles[-1][4]
    bnb_entry = 568.74
    bnb_sl = 567.48
    bnb_tp = 573.75
    
    print(f"Current price: ${bnb_current}")
    if bnb_low <= bnb_sl:
        print("STATUS: STOP LOSS HIT ❌")
    elif bnb_high >= bnb_tp:
        print("STATUS: TAKE PROFIT HIT 🎯")
    elif bnb_current > bnb_entry:
        print(f"STATUS: ACTIVE (FLOATING PROFIT 📈 +${bnb_current - bnb_entry:.2f} / coin)")
    else:
        print(f"STATUS: ACTIVE (FLOATING LOSS 📉 -${bnb_entry - bnb_current:.2f} / coin)")
    
    print("\n=== 🔷 SOL (SHORT) ===")
    sol_candles = h.fetch_ohlcv('SOL/USDC:USDC', '1m', limit=105)
    sol_low = min([c[3] for c in sol_candles])
    sol_high = max([c[2] for c in sol_candles])
    sol_current = sol_candles[-1][4]
    sol_entry = 73.62
    sol_sl = 73.92
    sol_tp = 72.46
    
    print(f"Current price: ${sol_current}")
    if sol_high >= sol_sl:
        print("STATUS: STOP LOSS HIT ❌")
    elif sol_low <= sol_tp:
        print("STATUS: TAKE PROFIT HIT 🎯")
    elif sol_current < sol_entry:
        print(f"STATUS: ACTIVE (FLOATING PROFIT 📈 +${sol_entry - sol_current:.2f} / coin)")
    else:
        print(f"STATUS: ACTIVE (FLOATING LOSS 📉 -${sol_current - sol_entry:.2f} / coin)")

except Exception as e:
    print(f"Error fetching data: {e}")
