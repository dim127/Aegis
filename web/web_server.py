import os
import json
import asyncio
import httpx
import yfinance as yf
import pandas as pd
from http.server import HTTPServer, SimpleHTTPRequestHandler
from indicators import ema, rsi
from config import get_web_positions
from web.server import (
    get_derivatives_metrics,
    get_liquidation_zones,
    get_defillama_onchain_data,
    get_market_sentiment,
)

PORT = 5050
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
_loop = None


def get_event_loop():
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


class TradingDashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            self.handle_api_data()
        else:
            super().do_GET()

    def handle_api_data(self):
        loop = get_event_loop()

        pos_data = get_web_positions()
        POSITION_SIDE = list(pos_data.keys())[0]
        pos = pos_data[POSITION_SIDE]
        TP1 = pos["tp"]
        SL = pos["sl"]
        ENTRY_AVG = pos["entry"]

        btc_price = 65000.0
        change_24h = 0.0
        vol_24h = 23500000000.0

        async def fetch_coinbase():
            try:
                async with httpx.AsyncClient(timeout=5.0, headers=HEADERS) as client:
                    res = await client.get(COINBASE_SPOT_URL)
                    if res.status_code == 200:
                        return float(res.json()["data"]["amount"])
            except Exception as e:
                print("Coinbase price fetch error:", e)
            return 65000.0

        try:
            btc_price = loop.run_until_complete(fetch_coinbase())
        except Exception as e:
            print("Coinbase price fetch error:", e)

        candles = []
        ema9_series = []
        ema21_series = []
        rsi_series = []
        rsi_val = 35.0

        try:
            ticker = yf.Ticker("BTC-USD")
            df = ticker.history(period="1d", interval="5m")
            if not df.empty:
                df.iloc[-1, df.columns.get_loc("Close")] = btc_price
                if btc_price > df.iloc[-1]["High"]:
                    df.iloc[-1, df.columns.get_loc("High")] = btc_price
                if btc_price < df.iloc[-1]["Low"]:
                    df.iloc[-1, df.columns.get_loc("Low")] = btc_price

                df["EMA9"] = ema(df["Close"], 9)
                df["EMA21"] = ema(df["Close"], 21)
                df["RSI"] = rsi(df["Close"])

                rsi_val = float(df["RSI"].iloc[-1])

                for idx, row in df.iterrows():
                    time_sec = int(idx.timestamp())
                    candles.append(
                        {
                            "time": time_sec,
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                        }
                    )
                    if not pd.isna(row["EMA9"]):
                        ema9_series.append({"time": time_sec, "value": float(row["EMA9"])})
                    if not pd.isna(row["EMA21"]):
                        ema21_series.append({"time": time_sec, "value": float(row["EMA21"])})
                    if not pd.isna(row["RSI"]):
                        rsi_series.append({"time": time_sec, "value": float(row["RSI"])})
        except Exception as e:
            print("Error fetching OHLCV for web:", e)

        funding_rate = 0.0058

        try:
            liq_raw = loop.run_until_complete(get_liquidation_zones(btc_price))
            liq_data = json.loads(liq_raw)
            short_liq_target = float(
                liq_data.get("short_liquidation_magnet_zones", {}).get("100x_high_risk", 65484.0)
            )
            long_liq_danger = float(
                liq_data.get("long_liquidation_magnet_zones", {}).get("100x_high_risk", 64187.0)
            )
        except Exception:
            short_liq_target = 65484.0
            long_liq_danger = 64187.0

        fear_and_greed = "31"
        fng_desc = "Fear"
        eth_tvl = 41500000000.0

        win_rate = 0.0
        total_trades = 0
        total_pnl = 0.0
        try:
            journal_path = os.path.join(STATIC_DIR, "..", "..", "journals", "TRADING_JOURNAL_DAILY.csv")
            if os.path.exists(journal_path):
                df_journal = pd.read_csv(journal_path)
                closed_trades = df_journal[df_journal["Status"] == "Closed"]
                total_trades = len(closed_trades)
                if total_trades > 0:
                    wins = len(closed_trades[closed_trades["PnL"] > 0])
                    win_rate = (wins / total_trades) * 100.0
                    total_pnl = closed_trades["PnL"].sum()
        except Exception as e:
            print("Error reading journal for analytics:", e)

        btc_filter_status = "FAIL"
        if len(ema9_series) > 0 and len(ema21_series) > 0:
            last_ema9 = ema9_series[-1]["value"]
            last_ema21 = ema21_series[-1]["value"]
            if last_ema9 > last_ema21 and rsi_val > 50:
                btc_filter_status = "PASS"

        current_sl = SL
        auto_be_active = False
        if POSITION_SIDE == "LONG":
            be_trigger_price = ENTRY_AVG + (TP1 - ENTRY_AVG) * 0.50
            if btc_price >= be_trigger_price:
                auto_be_active = True
                current_sl = ENTRY_AVG
        else:
            be_trigger_price = ENTRY_AVG - (ENTRY_AVG - TP1) * 0.50
            if btc_price <= be_trigger_price:
                auto_be_active = True
                current_sl = ENTRY_AVG

        if POSITION_SIDE == "LONG":
            total_range = TP1 - ENTRY_AVG
            current_gain = btc_price - ENTRY_AVG
            sl_distance = btc_price - current_sl
        else:
            total_range = ENTRY_AVG - TP1
            current_gain = ENTRY_AVG - btc_price
            sl_distance = current_sl - btc_price

        tp_progress = max(0.0, min(100.0, (current_gain / total_range) * 100)) if total_range > 0 else 0

        response_payload = {
            "position_side": POSITION_SIDE,
            "btc_price": btc_price,
            "change_24h": change_24h,
            "vol_24h": vol_24h,
            "tp_progress": tp_progress,
            "sl_distance": sl_distance,
            "funding_rate": funding_rate,
            "short_liq_target": short_liq_target,
            "long_liq_danger": long_liq_danger,
            "fear_and_greed": fear_and_greed,
            "fng_desc": fng_desc,
            "eth_tvl": eth_tvl,
            "rsi_val": rsi_val,
            "candles": candles,
            "ema9_series": ema9_series,
            "ema21_series": ema21_series,
            "rsi_series": rsi_series,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "btc_filter_status": btc_filter_status,
            "auto_be_active": auto_be_active,
            "current_sl": current_sl,
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(response_payload).encode("utf-8"))


def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, TradingDashboardHandler)
    print(f"Web Dashboard running at http://localhost:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
