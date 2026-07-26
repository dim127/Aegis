from typing import List, Optional, Dict
import pandas as pd
import logging

from pairlist.base import IPairlistHandler
from pairlist.static import StaticPairList
from pairlist.volume import VolumePairList
from pairlist.filters import (
    PriceFilter,
    SpreadFilter,
    VolatilityFilter,
    AgeFilter,
    OffsetFilter,
    ShuffleFilter,
    PerformanceFilter,
)
from pairlist.hyperliquid import HyperliquidVolumePairList, HyperliquidMajorPairList, HyperliquidSpotFilter

logger = logging.getLogger(__name__)

HANDLER_MAP = {
    "StaticPairList": StaticPairList,
    "VolumePairList": VolumePairList,
    "PriceFilter": PriceFilter,
    "SpreadFilter": SpreadFilter,
    "VolatilityFilter": VolatilityFilter,
    "AgeFilter": AgeFilter,
    "OffsetFilter": OffsetFilter,
    "ShuffleFilter": ShuffleFilter,
    "PerformanceFilter": PerformanceFilter,
    "HyperliquidVolumePairList": HyperliquidVolumePairList,
    "HyperliquidMajorPairList": HyperliquidMajorPairList,
    "HyperliquidSpotFilter": HyperliquidSpotFilter,
}


class PairlistManager:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.handlers: List[IPairlistHandler] = []
        self.blacklist = set(self.config.get("blacklist", []))
        self._build_handlers()

    def _build_handlers(self):
        handler_configs = self.config.get("pairlist_handlers", [])
        for hcfg in handler_configs:
            if isinstance(hcfg, str):
                method = hcfg
                params = {}
            else:
                method = hcfg.get("method", "")
                params = hcfg.get("parameters", {})
            handler_class = HANDLER_MAP.get(method)
            if handler_class:
                self.handlers.append(handler_class(params))
                logger.info(f"Pairlist handler loaded: {method}")
            else:
                logger.warning(f"Unknown pairlist handler: {method}")

    def refresh_pairlist(
        self, tickers: dict = None, dfs: dict[str, pd.DataFrame] = None
    ) -> List[str]:
        pairlist = None
        for handler in self.handlers:
            try:
                if isinstance(handler, VolatilityFilter) and dfs is not None:
                    pairlist = handler.filter_pairlist_with_df(pairlist or [], dfs)
                else:
                    pairlist = handler.filter_pairlist(pairlist or [], tickers)
                logger.debug(
                    f"  {handler.__class__.__name__}: {len(pairlist) if pairlist else 0} pairs"
                )
            except Exception as e:
                logger.error(f"  {handler.__class__.__name__} failed: {e}")

        if pairlist is None:
            pairlist = self.config.get("static_pairs", [])

        return [p for p in pairlist if p not in self.blacklist]

    def update_performance(self, performance: dict[str, float]):
        for handler in self.handlers:
            if isinstance(handler, PerformanceFilter):
                handler.update_performance(performance)
