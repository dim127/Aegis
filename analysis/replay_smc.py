"""Deterministic closed-candle replay for validating SMC decisions offline."""


def replay_closed_candles(strategy, raw_15m: list, raw_1m: list, timestamps,
                          tf_htf: str = "15m", tf_ltf: str = "1m") -> list[dict]:
    """Replay SMC decisions at the given timestamps.

    For each timestamp both dataframes are truncated to the candles that have
    closed by that time (identical semantics to live scanning) and the
    strategy is evaluated for both directions.
    """
    results = []
    for timestamp in timestamps:
        df_15m = strategy._ohlcv_to_df(raw_15m, tf_htf, now=timestamp)
        df_1m = strategy._ohlcv_to_df(raw_1m, tf_ltf, now=timestamp)
        setups = []
        if df_15m is not None and df_1m is not None:
            for direction in ("long", "short"):
                setup = strategy._check_direction(df_15m, df_1m, direction, tf_htf, tf_ltf)
                if setup.get("valid"):
                    setups.append(setup)
        results.append({"timestamp": timestamp, "setups": setups})
    return results
