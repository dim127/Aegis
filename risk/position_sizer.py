import logging

logger = logging.getLogger(__name__)


class PositionSizer:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.risk_per_trade = self.config.get("risk_per_trade", 0.01)
        self.max_position_size = self.config.get("max_position_size", None)
        self.min_position_size = self.config.get("min_position_size", None)

    def calculate_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: float = 1.0,
        side: str = "long",
    ) -> float:
        risk_amount = capital * self.risk_per_trade
        price_distance = abs(entry_price - stop_loss_price)
        if price_distance == 0 or entry_price == 0:
            logger.warning("PositionSizer: price_distance or entry_price is 0")
            return 0.0
        size = (risk_amount / price_distance) * leverage
        if side == "short":
            size = (risk_amount * entry_price) / (price_distance * entry_price)
            size = risk_amount / price_distance if price_distance > 0 else 0.0
            size *= leverage
        if self.max_position_size is not None:
            size = min(size, self.max_position_size)
        if self.min_position_size is not None and size < self.min_position_size:
            size = 0.0
        return max(size, 0.0)

    def calculate_stake_amount(
        self,
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        leverage: float = 1.0,
    ) -> float:
        size = self.calculate_size(capital, entry_price, stop_loss_price, leverage)
        return size * entry_price / leverage if leverage > 0 else size * entry_price
