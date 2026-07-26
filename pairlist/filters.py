from typing import List, Optional
import pandas as pd
import logging

from pairlist.base import IPairlistHandler

logger = logging.getLogger(__name__)


class PriceFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.min_price = self.config.get("min_price", 0.000001)
        self.max_price = self.config.get("max_price", 100000.0)
        self.max_value = self.config.get("max_value", None)
        self.low_price_ratio = self.config.get("low_price_ratio", None)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if tickers is None:
            return pairlist or []
        result = []
        for sym in (pairlist or []):
            ticker = tickers.get(sym, {})
            price = ticker.get("last") or ticker.get("close")
            if price is None:
                continue
            if price < self.min_price or price > self.max_price:
                continue
            if self.low_price_ratio is not None:
                high = ticker.get("high", price)
                if high > 0 and price / high < self.low_price_ratio:
                    continue
            result.append(sym)
        return result


class SpreadFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.max_spread_ratio = self.config.get("max_spread_ratio", 0.005)
        self.max_spread_percent = self.config.get("max_spread_percent", None)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if tickers is None:
            return pairlist or []
        max_spread = self.max_spread_percent / 100.0 if self.max_spread_percent else self.max_spread_ratio
        result = []
        for sym in (pairlist or []):
            ticker = tickers.get(sym, {})
            bid = ticker.get("bid")
            ask = ticker.get("ask")
            if bid is None or ask is None or bid <= 0:
                result.append(sym)
                continue
            spread = (ask - bid) / bid
            if spread <= max_spread:
                result.append(sym)
        return result


class VolatilityFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.lookback_days = self.config.get("lookback_days", 7)
        self.min_volatility = self.config.get("min_volatility", 0.0)
        self.max_volatility = self.config.get("max_volatility", None)
        self._cache: dict[str, float] = {}

    def filter_pairlist_with_df(
        self, pairlist: List[str], dfs: dict[str, pd.DataFrame] = None
    ) -> List[str]:
        result = []
        for sym in pairlist:
            df = (dfs or {}).get(sym)
            if df is None or len(df) < 20:
                result.append(sym)
                continue
            returns = df["Close"].pct_change().dropna()
            vol = returns.std()
            if self.min_volatility and vol < self.min_volatility:
                continue
            if self.max_volatility and vol > self.max_volatility:
                continue
            result.append(sym)
        return result


class AgeFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.min_days_listed = self.config.get("min_days_listed", 7)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        return pairlist or []


class OffsetFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.offset = self.config.get("offset", 0)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if pairlist is None:
            return []
        return pairlist[self.offset:]


class ShuffleFilter(IPairlistHandler):
    import random

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.seed = self.config.get("seed", None)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if pairlist is None:
            return []
        result = list(pairlist)
        if self.seed is not None:
            self.random.seed(self.seed)
        self.random.shuffle(result)
        return result


class PerformanceFilter(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.sort = self.config.get("sort", "desc")
        self._performance: dict[str, float] = {}

    def update_performance(self, performance: dict[str, float]):
        self._performance.update(performance)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if pairlist is None:
            return []
        scored = [(sym, self._performance.get(sym, 0)) for sym in pairlist]
        scored.sort(key=lambda x: x[1], reverse=(self.sort == "desc"))
        return [s[0] for s in scored]
