import yfinance as yf

def test_fetch():
    print("Fetching AAPL data via yfinance...")
    ticker = yf.Ticker("AAPL")
    df = ticker.history(period="1d", interval="1m")
    print("Data fetched successfully:")
    print(df.head())

if __name__ == "__main__":
    test_fetch()
