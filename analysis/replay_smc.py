"""Deterministic closed-candle replay for validating SMC decisions offline."""


def replay_closed_candles(strategy, raw_15m: list, raw_1m: list, timestamps) -> list[dict]:
    results = []
    for timestamp in timestamps:
        df_15m = strategy._ohlcv_to_df(raw_15m, "15m", now=timestamp)
        df_1m = strategy._ohlcv_to_df(raw_1m, "1m", now=timestamp)
        setups = []
        if df_15m is not None and df_1m is not None:
            for direction in ("long", "short"):
                setup = strategy._check_direction(df_15m, df_1m, direction)
                if setup.get("valid"):
                    setups.append(setup)
        results.append({"timestamp": timestamp, "setups": setups})
    return results
