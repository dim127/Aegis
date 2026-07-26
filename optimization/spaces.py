from typing import Dict, Any, List, Optional, Callable
import random


class Dimension:
    def __init__(self, name: str):
        self.name = name

    def sample(self) -> Any:
        raise NotImplementedError

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})"


class Integer(Dimension):
    def __init__(self, name: str, low: int, high: int):
        super().__init__(name)
        self.low = low
        self.high = high

    def sample(self) -> int:
        return random.randint(self.low, self.high)


class Float(Dimension):
    def __init__(self, name: str, low: float, high: float):
        super().__init__(name)
        self.low = low
        self.high = high

    def sample(self) -> float:
        return random.uniform(self.low, self.high)


class Categorical(Dimension):
    def __init__(self, name: str, choices: List[Any]):
        super().__init__(name)
        self.choices = choices

    def sample(self) -> Any:
        return random.choice(self.choices)


class Boolean(Dimension):
    def __init__(self, name: str):
        super().__init__(name)

    def sample(self) -> bool:
        return random.choice([True, False])


class HyperoptSpace:
    def __init__(self):
        self.dimensions: List[Dimension] = []

    def add(self, dim: Dimension):
        self.dimensions.append(dim)
        return self

    def sample(self) -> Dict[str, Any]:
        return {d.name: d.sample() for d in self.dimensions}

    def to_dict(self) -> List[Dict]:
        return [
            {
                "name": d.name,
                "type": d.__class__.__name__.lower(),
                **{k: v for k, v in d.__dict__.items() if k != "name"},
            }
            for d in self.dimensions
        ]

    @classmethod
    def from_strategy(cls, strategy) -> "HyperoptSpace":
        space = cls()
        if hasattr(strategy, "scoring_threshold"):
            space.add(Integer("scoring_threshold", 55, 75))
        if hasattr(strategy, "atr_sl_multiplier"):
            space.add(Float("atr_sl_multiplier", 1.0, 3.0))
        if hasattr(strategy, "atr_tp_multiplier"):
            space.add(Float("atr_tp_multiplier", 2.0, 5.0))
        if hasattr(strategy, "rsi_oversold"):
            space.add(Integer("rsi_oversold", 25, 40))
        if hasattr(strategy, "rsi_overbought"):
            space.add(Integer("rsi_overbought", 60, 75))
        if hasattr(strategy, "max_open_trades"):
            space.add(Integer("max_open_trades", 1, 6))
        if hasattr(strategy, "stoploss"):
            space.add(Float("stoploss", -0.1, -0.02))
        if hasattr(strategy, "trailing_stop_positive"):
            space.add(Float("trailing_stop_positive", 0.005, 0.05))
        if hasattr(strategy, "trailing_stop_positive_offset"):
            space.add(Float("trailing_stop_positive_offset", 0.01, 0.08))
        if hasattr(strategy, "position_adjustment_enable"):
            space.add(Boolean("position_adjustment_enable"))
        return space
