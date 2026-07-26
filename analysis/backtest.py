import yfinance as yf
import pandas as pd
from config import SCORING_STRICT_THRESHOLD
from indicators import add_ta_indicators, compute_scoring


def run_backtest(symbol="DOGE-USD", period="730d"):
    print(f"Downloading historical data for {symbol} ({period})...")
    df = yf.Ticker(symbol).history(period=period, interval="1h")

    if df.empty:
        print("Failed to download data.")
        return

    print(f"Downloaded {len(df)} historical candles. Calculating indicators...")

    add_ta_indicators(df)
    df.dropna(inplace=True)

    print("Starting Simulation Engine (Scanning for V3.0 Setups)...")

    trades = []
    active_trade = None
    fng_score = 50
    funding_rate = 0.005

    for i in range(1, len(df)):
        if active_trade is not None:
            high = df["High"].iloc[i]
            low = df["Low"].iloc[i]

            if active_trade["type"] == "LONG":
                if low <= active_trade["sl"]:
                    active_trade["result"] = "LOSS"
                    trades.append(active_trade)
                    active_trade = None
                    continue
                elif high >= active_trade["tp"]:
                    active_trade["result"] = "WIN"
                    trades.append(active_trade)
                    active_trade = None
                    continue
            else:
                if high >= active_trade["sl"]:
                    active_trade["result"] = "LOSS"
                    trades.append(active_trade)
                    active_trade = None
                    continue
                elif low <= active_trade["tp"]:
                    active_trade["result"] = "WIN"
                    trades.append(active_trade)
                    active_trade = None
                    continue
            continue

        row = df.iloc[i - 1].copy()
        row["Vol_24h_Avg"] = row.get("Vol_24h_Avg", row["Volume"])

        bos_window = df.iloc[max(0, i - 10):i - 1]
        price = row["Close"]
        high_window = bos_window["High"].max()
        low_window = bos_window["Low"].min()
        bullish_bos = bool(price > high_window) if len(bos_window) >= 5 else False
        bearish_bos = bool(price < low_window) if len(bos_window) >= 5 else False

        score_long, score_short, trend_up, trend_down = compute_scoring(
            row, fng_score=fng_score, funding_rate=funding_rate,
            bos_info={"bullish_bos": bullish_bos, "bearish_bos": bearish_bos},
            ob_info={}, fvg_info={},
        )

        atr = row["ATRr_14"]

        if score_long >= SCORING_STRICT_THRESHOLD and not trend_down:
            entry = row["Close"] - (atr * 0.5)
            sl = entry - (atr * 1.5)
            tp = entry + (atr * 3.0)
            active_trade = {"type": "LONG", "entry": entry, "sl": sl, "tp": tp, "result": None}

        elif score_short >= SCORING_STRICT_THRESHOLD and not trend_up:
            entry = row["Close"] + (atr * 0.5)
            sl = entry + (atr * 1.5)
            tp = entry - (atr * 3.0)
            active_trade = {"type": "SHORT", "entry": entry, "sl": sl, "tp": tp, "result": None}

    total_trades = len(trades)
    if total_trades == 0:
        print(f"\nNo setups met the strict criteria (Score >= {SCORING_STRICT_THRESHOLD}) in the last 2 years.")
        return

    wins = len([t for t in trades if t["result"] == "WIN"])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100

    capital = 30.0
    risk = 3.0
    reward = 6.0

    for t in trades:
        if t["result"] == "WIN":
            capital += reward
        else:
            capital -= risk

    print("\n" + "=" * 50)
    print("BACKTEST SIMULATION RESULTS (2 YEARS)")
    print("=" * 50)
    print(f"Coin: {symbol} (1-Hour Candles)")
    print(f"Total Trades Executed: {total_trades}")
    print(f"Total WIN: {wins}")
    print(f"Total LOSS: {losses}")
    print(f"Win-Rate (Accuracy): {win_rate:.2f}%")
    print(f"Starting Capital: $30.00")
    print(f"Ending Capital: ${capital:,.2f}")

    if capital > 30:
        print(f"Net Profit: +${(capital - 30):,.2f} (ROI: {((capital - 30) / 30) * 100:.2f}%)")
    else:
        print(f"Net Loss: -${(30 - capital):,.2f}")
    print("=" * 50)


if __name__ == "__main__":
    run_backtest()
