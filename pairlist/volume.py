from typing import List
import ccxt
import logging

from pairlist.base import IPairlistHandler

logger = logging.getLogger(__name__)


class VolumePairList(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.number_assets = self.config.get("number_assets", 20)
        self.sort_key = self.config.get("sort_key", "quoteVolume")
        self.min_volume = self.config.get("min_volume", 0)
        self.exchange_name = self.config.get("exchange", "binance")
        self.quote_currency = self.config.get("quote_currency", "USDT")
        self._tickers_cache = None

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if tickers is not None:
            return self._filter_by_tickers(tickers)
        try:
            exchange_class = getattr(ccxt, self.exchange_name)
            exchange = exchange_class({"enableRateLimit": True})
            markets = exchange.load_markets()
            tickers_data = exchange.fetch_tickers()

            pairs_with_vol = []
            for symbol, ticker in tickers_data.items():
                if not symbol.endswith(f"/{self.quote_currency}"):
                    continue
                if symbol not in markets:
                    continue
                volume = ticker.get(self.sort_key, 0) or 0
                if volume < self.min_volume:
                    continue
                pairs_with_vol.append((symbol, volume))

            pairs_with_vol.sort(key=lambda x: x[1], reverse=True)
            top_pairs = [p[0] for p in pairs_with_vol[:self.number_assets]]
            logger.info(
                f"VolumePairList: {len(top_pairs)} pairs selected (top {self.number_assets} by volume)"
            )
            return top_pairs
        except Exception as e:
            logger.error(f"VolumePairList failed: {e}")
            return pairlist or []

    def _filter_by_tickers(self, tickers: dict) -> List[str]:
        pairs_with_vol = [
            (sym, data.get(self.sort_key, 0) or 0)
            for sym, data in tickers.items()
            if sym.endswith(f"/{self.quote_currency}")
            and (data.get(self.sort_key, 0) or 0) >= self.min_volume
        ]
        pairs_with_vol.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in pairs_with_vol[:self.number_assets]]
