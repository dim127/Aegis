import yfinance as yf
import pandas as pd
from indicators import add_ta_indicators, compute_scoring


def run_backtest_on_coin(symbol: str, period: str = "365d", threshold: int = 70, fng_score: int = 50, funding_rate: float = 0.005) -> dict:
    df = yf.Ticker(symbol).history(period=period, interval="1h")
    if df.empty or len(df) < 100:
        return {"symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "profit": 0.0}

    add_ta_indicators(df)
    df.dropna(inplace=True)

    trades = []
    active_trade = None

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

        if score_long >= threshold and not trend_down:
            entry = row["Close"] - (atr * 0.5)
            sl = entry - (atr * 1.5)
            tp = entry + (atr * 3.0)
            active_trade = {"type": "LONG", "entry": entry, "sl": sl, "tp": tp, "result": None}
        elif score_short >= threshold and not trend_up:
            entry = row["Close"] + (atr * 0.5)
            sl = entry + (atr * 1.5)
            tp = entry - (atr * 3.0)
            active_trade = {"type": "SHORT", "entry": entry, "sl": sl, "tp": tp, "result": None}

    total = len(trades)
    if total == 0:
        return {"symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "profit": 0.0}

    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = total - wins
    profit = (wins * 6.0) - (losses * 3.0)
    return {
        "symbol": symbol,
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round((wins / total) * 100, 2),
        "profit": round(profit, 2),
    }


def validate_thresholds():
    test_coins = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "LINK-USD"]
    thresholds = [50, 60, 70, 80]

    print("=" * 80)
    print("SCORING WEIGHT VALIDATION — MULTI-COIN BACKTEST")
    print("=" * 80)

    for threshold in thresholds:
        print(f"\n--- Threshold: {threshold} ---")
        total_trades = 0
        total_wins = 0
        total_profit = 0.0
        active_coins = 0

        for coin in test_coins:
            result = run_backtest_on_coin(coin, period="365d", threshold=threshold)
            if result["trades"] > 0:
                active_coins += 1
                total_trades += result["trades"]
                total_wins += result["wins"]
                total_profit += result["profit"]
                print(f"  {coin:>10} : {result['trades']:>3} trades | "
                      f"WR {result['win_rate']:>5.1f}% | "
                      f"PnL ${result['profit']:>+6.2f}")

        if total_trades > 0:
            combined_wr = (total_wins / total_trades) * 100
            print(f"  {'─'*50}")
            print(f"  {'TOTAL':>10} : {total_trades:>3} trades | "
                  f"WR {combined_wr:>5.1f}% | "
                  f"PnL ${total_profit:>+6.2f} | "
                  f"Coins: {active_coins}")
        else:
            print(f"  No trades triggered for any coin.")


def validate_weights():
    print("\n" + "=" * 80)
    print("FULL VALIDATION (Threshold=70, Multi-Coin)")
    print("=" * 80)

    all_coins = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
                  "ADA-USD", "AVAX-USD", "DOGE-USD", "LINK-USD", "DOT-USD"]

    grand_total = 0
    grand_wins = 0
    grand_profit = 0.0
    active = 0

    for coin in all_coins:
        result = run_backtest_on_coin(coin, period="365d", threshold=70)
        if result["trades"] > 0:
            active += 1
            grand_total += result["trades"]
            grand_wins += result["wins"]
            grand_profit += result["profit"]
            print(f"  {coin:>10} : {result['trades']:>3} trades | "
                  f"WR {result['win_rate']:>5.1f}% | "
                  f"PnL ${result['profit']:>+6.2f}")
        else:
            print(f"  {coin:>10} : No trades")

    if grand_total > 0:
        combined_wr = (grand_wins / grand_total) * 100
        print(f"  {'─'*50}")
        print(f"  {'TOTAL':>10} : {grand_total:>3} trades | "
              f"WR {combined_wr:>5.1f}% | "
              f"PnL ${grand_profit:>+6.2f} | "
              f"Active coins: {active}/{len(all_coins)}")
    else:
        print("  No trades across all coins.")


if __name__ == "__main__":
    validate_thresholds()
    validate_weights()
