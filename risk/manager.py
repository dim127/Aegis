from datetime import datetime
from typing import List, Optional, Dict
import logging

from risk.base import IProtection, ProtectionResult
from risk.stoploss_guard import StoplossGuard
from risk.max_drawdown import MaxDrawdown
from risk.low_profit_pairs import LowProfitPairs
from risk.cooldown import CooldownPeriod
from risk.position_sizer import PositionSizer

logger = logging.getLogger(__name__)

PROTECTION_MAP = {
    "StoplossGuard": StoplossGuard,
    "MaxDrawdown": MaxDrawdown,
    "LowProfitPairs": LowProfitPairs,
    "CooldownPeriod": CooldownPeriod,
}


class RiskManager:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.protections: List[IProtection] = []
        self.position_sizer = PositionSizer(self.config.get("position_sizing", {}))
        self._build_protections()

    def _build_protections(self):
        protection_configs = self.config.get("protections", [])
        for pcfg in protection_configs:
            if isinstance(pcfg, str):
                method = pcfg
                params = {}
            else:
                method = pcfg.get("method", "")
                params = pcfg.get("parameters", {})
            protection_class = PROTECTION_MAP.get(method)
            if protection_class:
                self.protections.append(protection_class(params))
                logger.info(f"Protection loaded: {method}")
            else:
                logger.warning(f"Unknown protection: {method}")

    def check_entry(
        self,
        pair: str,
        trades: List[Dict] = None,
        current_time: datetime = None,
        **kwargs,
    ) -> ProtectionResult:
        trades = trades or []
        current_time = current_time or datetime.utcnow()
        for protection in self.protections:
            result = protection.check(
                pair=pair,
                trades=trades,
                current_time=current_time,
                **kwargs,
            )
            if result.stop:
                return result
        return ProtectionResult(stop=False)

    def on_exit(self, pair: str, profit: float, time: datetime = None):
        current_time = time or datetime.utcnow()
        for p in self.protections:
            if isinstance(p, StoplossGuard) and profit < 0:
                p.record_stoploss(pair, profit, current_time)
            if isinstance(p, CooldownPeriod):
                p.record_exit(pair, current_time)

    def update_balance(self, balance: float):
        for p in self.protections:
            if isinstance(p, MaxDrawdown):
                p.update_balance(balance)

    def all_protections_active(self) -> List[str]:
        return [p.__class__.__name__ for p in self.protections]
