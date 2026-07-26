from typing import List, Optional
import logging

from pairlist.base import IPairlistHandler

logger = logging.getLogger(__name__)


class HyperliquidVolumePairList(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.number_assets = self.config.get("number_assets", 30)
        self.min_volume = self.config.get("min_volume", 100000)
        self.min_price = self.config.get("min_price", 0.000001)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if not tickers:
            logger.warning("HyperliquidVolumePairList: no tickers provided, fetching live")
            tickers = self._fetch_tickers()
            if not tickers:
                return pairlist or []

        perp_pairs = {
            sym: data for sym, data in tickers.items()
            if sym.endswith(":USDC")
        }

        scored = []
        for sym, data in perp_pairs.items():
            vol = data.get("quoteVolume") or 0
            last = data.get("last")
            if vol < self.min_volume:
                continue
            if last is not None and last < self.min_price:
                continue
            scored.append((sym, vol))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = [s[0] for s in scored[:self.number_assets]]
        logger.info(f"HyperliquidVolumePairList: {len(top)} pairs (top {self.number_assets} by volume)")
        return top

    def _fetch_tickers(self) -> Optional[dict]:
        try:
            import ccxt
            exchange = ccxt.hyperliquid({"enableRateLimit": True, "timeout": 15000})
            return exchange.fetch_tickers()
        except Exception as e:
            logger.error(f"HyperliquidVolumePairList fetch failed: {e}")
            return None


class HyperliquidSpotFilter(IPairlistHandler):
    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        if pairlist is None:
            return []
        return [s for s in pairlist if s.endswith(":USDC")]


class HyperliquidMajorPairList(IPairlistHandler):
    MAJOR_PAIRS = [
        "BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC",
        "BNB/USDC:USDC", "XRP/USDC:USDC", "ADA/USDC:USDC",
        "AVAX/USDC:USDC", "DOGE/USDC:USDC", "LINK/USDC:USDC",
        "DOT/USDC:USDC", "ARB/USDC:USDC", "OP/USDC:USDC",
        "ATOM/USDC:USDC", "SUI/USDC:USDC", "APT/USDC:USDC",
    ]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.pairs = self.config.get("pairs", self.MAJOR_PAIRS)

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        blacklist = set(self.config.get("blacklist", []))
        return [p for p in self.pairs if p not in blacklist]
