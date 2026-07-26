import logging
import random
import time
import warnings
from typing import Type, List, Dict, Optional, Callable
from datetime import datetime

from optimization.losses import LOSS_FUNCTIONS
from optimization.spaces import HyperoptSpace, Dimension, Integer as OptInt, Float as OptFloat, Categorical as OptCat, Boolean as OptBool
from optimization.results import HyperoptEpoch, HyperoptResults
from strategy.base import IStrategy
from backtesting.engine import BacktestingEngine, BacktestConfig

logger = logging.getLogger(__name__)


class HyperoptEngine:
    def __init__(
        self,
        strategy_cls: Type[IStrategy],
        pairs: List[str],
        timerange: str = "180d",
        interval: str = "1h",
        config: dict = None,
    ):
        self.strategy_cls = strategy_cls
        self.pairs = pairs
        self.timerange = timerange
        self.interval = interval
        self.config = config or {}
        self.results = HyperoptResults()
        self.space: Optional[HyperoptSpace] = None
        self.backtest_config = BacktestConfig(
            start_capital=self.config.get("start_capital", 1000.0),
            fee=self.config.get("fee", 0.0007),
            slippage=self.config.get("slippage", 0.0005),
            leverage=self.config.get("leverage", 1.0),
            max_open_trades=self.config.get("max_open_trades", 3),
            stake_amount=self.config.get("stake_amount", 30.0),
        )
        self.loss_fn_name = self.config.get("loss_function", "sharpe")
        self.loss_fn = LOSS_FUNCTIONS.get(self.loss_fn_name, LOSS_FUNCTIONS["sharpe"])

    def _build_space(self) -> HyperoptSpace:
        strategy = self.strategy_cls()
        return HyperoptSpace.from_strategy(strategy)

    def _apply_params(self, strategy: IStrategy, params: Dict):
        for k, v in params.items():
            if hasattr(strategy, k):
                setattr(strategy, k, v)

    def _run_epoch(self, params: Dict, epoch: int) -> HyperoptEpoch:
        strategy = self.strategy_cls()
        self._apply_params(strategy, params)

        engine = BacktestingEngine(config=self.backtest_config)
        results = engine.run(
            strategy_cls=self.strategy_cls,
            pairs=self.pairs,
            timerange=self.timerange,
            interval=self.interval,
            strategy_params=params,
        )

        all_trades = []
        total_profit = 0.0
        total_wins = 0
        total_trades_count = 0
        peak = 1000.0
        max_dd = 0.0

        for pair, result in results.items():
            for t in result.trades:
                trade_data = {
                    "pair": pair,
                    "profit_ratio": t.profit_ratio,
                    "profit_abs": t.profit_abs,
                    "duration": t.duration.total_seconds() if t.duration else 0,
                    "side": t.side.value if t.side else "long",
                }
                all_trades.append(trade_data)
                total_profit += t.profit_abs
                total_trades_count += 1
                if t.profit_abs > 0:
                    total_wins += 1

        win_rate = total_wins / total_trades_count if total_trades_count > 0 else 0.0

        loss_value = self.loss_fn(all_trades)

        epoch_result = HyperoptEpoch(
            epoch=epoch,
            params=params.copy(),
            loss=loss_value,
            results=all_trades,
            total_profit=total_profit,
            win_rate=win_rate,
            profit_factor=0.0,
            max_drawdown=0.0,
            total_trades=total_trades_count,
        )
        return epoch_result

    def optimize(
        self,
        epochs: int = 100,
        space: Optional[HyperoptSpace] = None,
        random_state: Optional[int] = None,
        early_stop: Optional[int] = None,
        verbose: bool = True,
    ) -> HyperoptResults:
        if space:
            self.space = space
        else:
            self.space = self._build_space()

        if random_state is not None:
            random.seed(random_state)

        self.results = HyperoptResults()
        best_loss = -float("inf")
        no_improve = 0
        start_time = time.time()

        for i in range(epochs):
            params = self.space.sample()
            try:
                epoch_result = self._run_epoch(params, i + 1)
                self.results.add_epoch(epoch_result)

                if epoch_result.loss > best_loss:
                    best_loss = epoch_result.loss
                    no_improve = 0
                else:
                    no_improve += 1

                if verbose:
                    elapsed = time.time() - start_time
                    logger.info(
                        f"Epoch {i + 1}/{epochs} | "
                        f"Loss: {epoch_result.loss:.4f} | "
                        f"Trades: {epoch_result.total_trades} | "
                        f"Profit: {epoch_result.total_profit:.2f} | "
                        f"Best: {best_loss:.4f} | "
                        f"Elapsed: {elapsed:.0f}s"
                    )

                if early_stop and no_improve >= early_stop:
                    logger.info(f"Early stop after {i + 1} epochs (no improvement for {early_stop})")
                    break

            except Exception as e:
                logger.error(f"Epoch {i + 1} failed: {e}")
                continue

        return self.results

    def optimize_with_skopt(
        self,
        epochs: int = 100,
        space: Optional[HyperoptSpace] = None,
        n_initial_points: int = 10,
        acq_func: str = "gp_hedge",
        verbose: bool = True,
    ) -> HyperoptResults:
        try:
            from skopt import gp_minimize
            from skopt.space import Integer, Real, Categorical as SkCategorical
        except ImportError:
            logger.warning("scikit-optimize not installed, falling back to random search")
            return self.optimize(epochs, space, verbose=verbose)

        if space:
            self.space = space
        else:
            self.space = self._build_space()

        skopt_dims = []
        dim_names = []
        for d in self.space.dimensions:
            dim_names.append(d.name)
            if isinstance(d, OptInt):
                skopt_dims.append(Integer(d.low, d.high, name=d.name))
            elif isinstance(d, OptFloat):
                skopt_dims.append(Real(d.low, d.high, name=d.name))
            elif isinstance(d, OptCat):
                skopt_dims.append(SkCategorical(d.choices, name=d.name))
            elif isinstance(d, OptBool):
                skopt_dims.append(SkCategorical([True, False], name=d.name))

        def objective(params):
            param_dict = dict(zip(dim_names, params))
            for d in self.space.dimensions:
                if isinstance(d, OptInt):
                    param_dict[d.name] = int(param_dict[d.name])
            epoch_result = self._run_epoch(param_dict, 0)
            return -epoch_result.loss

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = gp_minimize(
                objective,
                skopt_dims,
                n_calls=epochs,
                n_initial_points=n_initial_points,
                acq_func=acq_func,
                random_state=self.config.get("random_state", None),
                verbose=verbose,
            )

        self.results = HyperoptResults()
        best_params = dict(zip(dim_names, result.x))
        for d in self.space.dimensions:
            if isinstance(d, OptInt):
                best_params[d.name] = int(best_params[d.name])

        best_epoch = self._run_epoch(best_params, 0)
        best_epoch.epoch = 1
        self.results.add_epoch(best_epoch)
        return self.results
