import logging
import time
from typing import Type, List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd

from strategy.base import IStrategy
from backtesting.engine import BacktestingEngine, BacktestConfig, BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class StrategyBacktestResult:
    strategy_name: str
    results: Dict[str, BacktestResult]
    total_profit: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    total_trades: int = 0
    execution_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "total_profit": round(self.total_profit, 2),
            "win_rate": round(self.win_rate, 1),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 1),
            "sharpe": round(self.sharpe, 2),
            "total_trades": self.total_trades,
            "execution_time": round(self.execution_time, 1),
        }


@dataclass
class BacktestComparison:
    strategy_results: List[StrategyBacktestResult] = field(default_factory=list)

    def add(self, result: StrategyBacktestResult):
        self.strategy_results.append(result)

    def best_by(self, metric: str = "total_profit") -> Optional[StrategyBacktestResult]:
        results = [r for r in self.strategy_results if r.total_trades > 0]
        if not results:
            return None
        return max(results, key=lambda r: getattr(r, metric, 0))

    def summary(self) -> pd.DataFrame:
        rows = [r.to_dict() for r in self.strategy_results]
        return pd.DataFrame(rows).sort_values("total_profit", ascending=False)

    def to_dict(self) -> dict:
        return {
            "strategies": [r.to_dict() for r in self.strategy_results],
            "best_strategy": self.best_by().strategy_name if self.best_by() else None,
        }


class BacktestRunner:
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.engine = BacktestingEngine(config=self.config)

    def run_strategy(
        self,
        strategy_cls: Type[IStrategy],
        pairs: List[str],
        timerange: str = "180d",
        interval: str = "1h",
        strategy_params: dict = None,
    ) -> StrategyBacktestResult:
        strategy_params = strategy_params or {}
        start = time.time()

        results = self.engine.run(
            strategy_cls=strategy_cls,
            pairs=pairs,
            timerange=timerange,
            interval=interval,
            strategy_params=strategy_params,
        )

        elapsed = time.time() - start
        strategy_name = strategy_cls.__name__

        all_trades = []
        for r in results.values():
            all_trades.extend(r.trades)

        trades_data = [t for t in all_trades if not t.is_open]
        total_profit = sum(t.profit_abs for t in trades_data)
        wins = len([t for t in trades_data if t.profit_abs > 0])
        total = len(trades_data) if trades_data else 0

        gross_profit = sum(t.profit_abs for t in trades_data if t.profit_abs > 0)
        gross_loss = abs(sum(t.profit_abs for t in trades_data if t.profit_abs < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)

        max_dd = max((r.max_drawdown for r in results.values()), default=0.0)
        sharpe = max((r.sharpe_ratio for r in results.values()), default=0.0)

        return StrategyBacktestResult(
            strategy_name=strategy_name,
            results=results,
            total_profit=total_profit,
            win_rate=(wins / total * 100) if total > 0 else 0,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            sharpe=sharpe,
            total_trades=total,
            execution_time=elapsed,
        )

    def compare_strategies(
        self,
        strategies: List[Tuple[Type[IStrategy], str, dict]],
        pairs: List[str],
        timerange: str = "180d",
        interval: str = "1h",
    ) -> BacktestComparison:
        comparison = BacktestComparison()
        for strategy_cls, name, params in strategies:
            logger.info(f"Running backtest for strategy: {name}")
            result = self.run_strategy(
                strategy_cls=strategy_cls,
                pairs=pairs,
                timerange=timerange,
                interval=interval,
                strategy_params=params,
            )
            result.strategy_name = name
            comparison.add(result)
            logger.info(f"  Result: profit={result.total_profit:.2f}, "
                       f"trades={result.total_trades}, wr={result.win_rate:.1f}%")
        return comparison
