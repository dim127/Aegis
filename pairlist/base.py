from abc import ABC, abstractmethod
from typing import List, Optional
import pandas as pd


class IPairlistHandler(ABC):
    def __init__(self, config: dict = None):
        self.config = config or {}

    @abstractmethod
    def filter_pairlist(self, pairlist: List[str], tickers: dict = None) -> List[str]:
        ...

    def filter_pairlist_with_df(
        self, pairlist: List[str], dfs: dict[str, pd.DataFrame] = None
    ) -> List[str]:
        return self.filter_pairlist(pairlist, tickers=None)
