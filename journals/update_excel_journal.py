import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_FILE = os.path.join(BASE_DIR, "TRADING_JOURNAL_DAILY.xlsx")
CSV_FILE = os.path.join(BASE_DIR, "TRADING_JOURNAL_DAILY.csv")


def update_sol_status():
    if os.path.exists(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
        df.loc[df["Asset / Pair"] == "SOL/USDT", "Status"] = "CLOSED (SL)"
        df.loc[
            df["Asset / Pair"] == "SOL/USDT", "Catatan & Alasan Setup"
        ] = "Hit SL ($73.75) due to Liquidity Sweep and BTC drop ($64.1k)."

        df.to_csv(CSV_FILE, index=False)
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        print("Excel Trading Journal updated SOL status to CLOSED (SL).")


if __name__ == "__main__":
    update_sol_status()
