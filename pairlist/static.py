from typing import List
from pairlist.base import IPairlistHandler


class StaticPairList(IPairlistHandler):
    def __init__(self, config: dict = None):
        super().__init__(config)
        self.pairs = self.config.get("pairs", [])

    def filter_pairlist(self, pairlist: List[str] = None, tickers: dict = None) -> List[str]:
        blacklist = set(self.config.get("blacklist", []))
        return [p for p in self.pairs if p not in blacklist]
