from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Type
from enum import Enum
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging

from strategy.base import IStrategy

logger = logging.getLogger(__name__)


class OrderType(Enum):
    ENTRY = "entry"
    EXIT = "exit"


class TradeSide(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Trade:
    pair: str
    side: TradeSide
    open_date: pd.Timestamp
    open_price: float
    close_date: Optional[pd.Timestamp] = None
    close_price: Optional[float] = None
    amount: float = 0.0
    stoploss: float = 0.0
    take_profit: float = 0.0
    trailing_stop: Optional[float] = None
    highest_price: float = 0.0
    lowest_price: float = 0.0
    profit_ratio: float = 0.0
    profit_abs: float = 0.0
    exit_reason: str = ""
    fee_open: float = 0.0
    fee_close: float = 0.0
    sl_highest: Optional[float] = None
    is_open: bool = True

    @property
    def duration(self) -> timedelta:
        if self.close_date:
            return self.close_date - self.open_date
        return timedelta(0)


@dataclass
class BacktestResult:
    pair: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_fees: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    avg_hold_time: timedelta = timedelta(0)
    avg_profit: float = 0.0
    avg_profit_win: float = 0.0
    avg_loss: float = 0.0
    total_volume: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    timestamps: List[pd.Timestamp] = field(default_factory=list)


@dataclass
class BacktestConfig:
    start_capital: float = 100.0
    fee: float = 0.0007
    slippage: float = 0.0005
    leverage: float = 1.0
    max_open_trades: int = 3
    stake_amount: float = 30.0
    pair_limit: int = 10
    timeout: int = 120
    data_source: str = "yfinance"
    output_detailed: bool = True


class BacktestingEngine:

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.results: Dict[str, BacktestResult] = {}

    def run(
        self,
        strategy_cls: Type[IStrategy],
        pairs: List[str],
        timerange: str = "730d",
        interval: str = "1h",
        strategy_params: Optional[Dict] = None,
    ) -> Dict[str, BacktestResult]:
        strategy_params = strategy_params or {}
        strategy = strategy_cls(**strategy_params)
        strategy.timeframe = interval

        logger.info(f"Running backtest on {len(pairs)} pairs, {timerange}, {interval}")

        all_results = {}
        for pair in pairs:
            try:
                result = self._backtest_pair(strategy, pair, timerange, interval)
                all_results[pair] = result
            except Exception as e:
                logger.error(f"Backtest failed for {pair}: {e}")

        self.results = all_results
        return all_results

    def _download_data(self, symbol: str, interval: str, timerange: str) -> pd.DataFrame:
        yf_symbol = symbol.replace("/", "-").split(":")[0]
        if not yf_symbol.endswith("-USD") and not yf_symbol.endswith("-USDT"):
            yf_symbol = f"{yf_symbol}-USD"

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=timerange, interval=interval)

        if df.empty:
            raise ValueError(f"No data for {symbol} ({timerange}, {interval})")

        df.columns = [c.capitalize() for c in df.columns]
        return df

    def _backtest_pair(
        self,
        strategy: IStrategy,
        pair: str,
        timerange: str,
        interval: str,
    ) -> BacktestResult:
        df_1h = self._download_data(pair, "1h", timerange)
        df_4h = self._download_data(pair, "4h", timerange)
        df_1d = self._download_data(pair, "1d", timerange)

        if hasattr(strategy, "higher_tf_data"):
            strategy.higher_tf_data = {"4h": df_4h, "1d": df_1d}
        if hasattr(strategy, "_pair_name"):
            strategy._pair_name = pair

        if hasattr(strategy, "use_15m_filter") and strategy.use_15m_filter:
            try:
                df_15m = self._download_data(pair, "15m", "30d")
                if hasattr(strategy, "lower_tf_data"):
                    strategy.lower_tf_data["15m"] = df_15m
            except Exception:
                pass

        df = strategy.populate_indicators(df_1h)

        entry_signal_found = hasattr(strategy, "populate_entry_trend")
        exit_signal_found = hasattr(strategy, "populate_exit_trend")

        if entry_signal_found:
            df = strategy.populate_entry_trend(df)
        if exit_signal_found:
            df = strategy.populate_exit_trend(df)

        result = self._simulate(strategy, df, pair)
        return result

    def _simulate(
        self,
        strategy: IStrategy,
        df: pd.DataFrame,
        pair: str,
    ) -> BacktestResult:
        capital = self.config.start_capital
        open_trades: List[Trade] = []
        closed_trades: List[Trade] = []

        equity_curve = [capital]
        timestamps = [df.index[0]]

        fee = self.config.fee
        slippage = self.config.slippage
        leverage = self.config.leverage
        max_open = self.config.max_open_trades

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            current_time = df.index[i]
            high = row["High"]
            low = row["Low"]
            close = row["Close"]
            open_price = row["Open"]

            filled_trades = []
            for trade in open_trades:
                trade.highest_price = max(trade.highest_price, high)
                trade.lowest_price = min(trade.lowest_price, low)

                if trade.side == TradeSide.LONG:
                    exit_triggered = False

                    if low <= trade.stoploss:
                        exit_price = trade.stoploss
                        exit_reason = "stoploss"
                        exit_triggered = True
                    elif high >= trade.take_profit:
                        exit_price = trade.take_profit
                        exit_reason = "take_profit"
                        exit_triggered = True

                    if not exit_triggered and strategy.use_exit_signal:
                        if "exit_long" in df.columns and row.get("exit_long", 0) == 1:
                            exit_price = close
                            exit_reason = row.get("exit_tag", "exit_signal")
                            exit_triggered = True

                    if not exit_triggered and strategy.trailing_stop:
                        exit_triggered, exit_price, exit_reason = self._check_trailing_stop(
                            trade, row, strategy
                        )

                    if not exit_triggered and strategy.use_custom_stoploss:
                        current_profit = (close - trade.open_price) / trade.open_price
                        new_sl = strategy.custom_stoploss(
                            pair=pair,
                            trade=trade,
                            current_time=current_time,
                            current_rate=close,
                            current_profit=current_profit,
                        )
                        if new_sl is not None:
                            new_sl_price = trade.open_price * (1 + new_sl)
                            trade.stoploss = max(trade.stoploss, new_sl_price)

                            if low <= trade.stoploss:
                                exit_price = trade.stoploss
                                exit_reason = "custom_stoploss"
                                exit_triggered = True

                    if not exit_triggered:
                        min_roi = strategy.minimal_roi(
                            (close - trade.open_price) / trade.open_price
                        )
                        if min_roi is not None:
                            min_roi_price = trade.open_price * (1 + min_roi)
                            if low <= min_roi_price:
                                exit_price = min_roi_price
                                exit_reason = "roi"
                                exit_triggered = True

                else:
                    exit_triggered = False

                    if high >= trade.stoploss:
                        exit_price = trade.stoploss
                        exit_reason = "stoploss"
                        exit_triggered = True
                    elif low <= trade.take_profit:
                        exit_price = trade.take_profit
                        exit_reason = "take_profit"
                        exit_triggered = True

                    if not exit_triggered and strategy.use_exit_signal:
                        if "exit_short" in df.columns and row.get("exit_short", 0) == 1:
                            exit_price = close
                            exit_reason = row.get("exit_tag", "exit_signal")
                            exit_triggered = True

                    if not exit_triggered and strategy.trailing_stop:
                        inverse_trade = Trade(
                            pair=trade.pair,
                            side=TradeSide.LONG,
                            open_date=trade.open_date,
                            open_price=trade.open_price,
                            stoploss=trade.stoploss,
                            highest_price=trade.highest_price,
                            lowest_price=trade.lowest_price,
                            amount=trade.amount,
                        )
                        inverse_trade.highest_price = trade.lowest_price
                        inverse_trade.lowest_price = trade.highest_price
                        inv_result = self._check_trailing_stop(inverse_trade, row, strategy)
                        if inv_result[0]:
                            exit_price = close
                            exit_reason = inv_result[2]
                            exit_triggered = True

                    if not exit_triggered and strategy.use_custom_stoploss:
                        current_profit = (trade.open_price - close) / trade.open_price
                        new_sl = strategy.custom_stoploss(
                            pair=pair,
                            trade=trade,
                            current_time=current_time,
                            current_rate=close,
                            current_profit=current_profit,
                        )
                        if new_sl is not None:
                            new_sl_price = trade.open_price * (1 - abs(new_sl))
                            trade.stoploss = min(trade.stoploss, new_sl_price)

                            if high >= trade.stoploss:
                                exit_price = trade.stoploss
                                exit_reason = "custom_stoploss"
                                exit_triggered = True

                    if not exit_triggered:
                        min_roi = strategy.minimal_roi(
                            (trade.open_price - close) / trade.open_price
                        )
                        if min_roi is not None:
                            min_roi_price = trade.open_price * (1 - min_roi)
                            if high >= min_roi_price:
                                exit_price = min_roi_price
                                exit_reason = "roi"
                                exit_triggered = True

                if exit_triggered:
                    trade.close_date = current_time
                    trade.close_price = exit_price
                    trade.fee_close = exit_price * trade.amount * fee

                    if trade.side == TradeSide.LONG:
                        trade.profit_abs = (
                            (exit_price - trade.open_price) * trade.amount * leverage
                            - trade.fee_open - trade.fee_close
                        )
                    else:
                        trade.profit_abs = (
                            (trade.open_price - exit_price) * trade.amount * leverage
                            - trade.fee_open - trade.fee_close
                        )

                    trade.profit_ratio = trade.profit_abs / (trade.open_price * trade.amount)
                    trade.exit_reason = exit_reason
                    trade.is_open = False

                    capital += trade.profit_abs
                    closed_trades.append(trade)
                    filled_trades.append(trade)

            for t in filled_trades:
                open_trades.remove(t)

            if len(open_trades) < max_open:
                entry_signal = False
                entry_side = None

                if "enter_long" in df.columns and row.get("enter_long", 0) == 1:
                    entry_signal = True
                    entry_side = TradeSide.LONG
                elif "enter_short" in df.columns and row.get("enter_short", 0) == 1:
                    entry_signal = True
                    entry_side = TradeSide.SHORT

                if entry_signal and entry_side:
                    entry_price = open_price * (1 + slippage) if entry_side == TradeSide.LONG else open_price * (1 - slippage)
                    entry_price = round(entry_price, 2)

                    stake = strategy.custom_stake_amount(
                        pair=pair,
                        current_time=current_time,
                        current_rate=entry_price,
                        proposed_stake=self.config.stake_amount,
                        min_stake=5.0,
                        max_stake=capital * 0.5,
                        leverage=leverage,
                        entry_tag=row.get("enter_tag", ""),
                        side=entry_side.value,
                    )

                    if stake > 0 and stake <= capital:
                        amount = (stake * leverage) / entry_price
                        fee_open_cost = entry_price * amount * fee
                        atr_val = row.get("ATRr_14", 0)
                        if atr_val == 0 or pd.isna(atr_val):
                            atr_val = entry_price * 0.02

                        stoploss_price = strategy.stoploss
                        sl_price = (
                            entry_price * (1 + stoploss_price)
                            if entry_side == TradeSide.LONG
                            else entry_price * (1 - abs(stoploss_price))
                        )

                        tp_ratio = 1.5 * abs(stoploss_price)
                        tp_price = (
                            entry_price * (1 + tp_ratio)
                            if entry_side == TradeSide.LONG
                            else entry_price * (1 - tp_ratio)
                        )

                        if entry_side == TradeSide.LONG:
                            sl_price = entry_price - (atr_val * 1.5)
                            tp_price = entry_price + (atr_val * 3.0)
                        else:
                            sl_price = entry_price + (atr_val * 1.5)
                            tp_price = entry_price - (atr_val * 3.0)

                        trade = Trade(
                            pair=pair,
                            side=entry_side,
                            open_date=current_time,
                            open_price=entry_price,
                            amount=amount,
                            stoploss=sl_price,
                            take_profit=tp_price,
                            highest_price=entry_price,
                            lowest_price=entry_price,
                            fee_open=fee_open_cost,
                            fee_close=0,
                        )
                        open_trades.append(trade)

            current_equity = capital
            for trade in open_trades:
                unrealized = 0
                if trade.side == TradeSide.LONG:
                    unrealized = (close - trade.open_price) * trade.amount * leverage
                else:
                    unrealized = (trade.open_price - close) * trade.amount * leverage
                current_equity += unrealized

            equity_curve.append(current_equity)
            timestamps.append(current_time)

        for trade in open_trades:
            trade.close_date = timestamps[-1]
            trade.close_price = df["Close"].iloc[-1]
            trade.fee_close = trade.close_price * trade.amount * fee
            if trade.side == TradeSide.LONG:
                trade.profit_abs = (
                    (trade.close_price - trade.open_price) * trade.amount * leverage
                    - trade.fee_open - trade.fee_close
                )
            else:
                trade.profit_abs = (
                    (trade.open_price - trade.close_price) * trade.amount * leverage
                    - trade.fee_open - trade.fee_close
                )
            trade.profit_ratio = trade.profit_abs / (trade.open_price * trade.amount)
            trade.exit_reason = "force_exit"
            trade.is_open = False
            capital += trade.profit_abs
            closed_trades.append(trade)

        result = self._compute_stats(closed_trades, equity_curve, timestamps, pair, capital)
        return result

    def _check_trailing_stop(
        self,
        trade: Trade,
        row: pd.Series,
        strategy: IStrategy,
    ) -> tuple:
        if not strategy.trailing_stop:
            return False, 0.0, ""

        current_profit = (row["Close"] - trade.open_price) / trade.open_price

        if strategy.trailing_only_offset_is_reached:
            offset_price = trade.open_price * (1 + strategy.trailing_stop_positive_offset)
            if trade.highest_price < offset_price:
                return False, 0.0, ""

        if strategy.trailing_stop_positive is not None:
            if current_profit < strategy.trailing_stop_positive_offset:
                return False, 0.0, ""

            trail_at = current_profit - strategy.trailing_stop_positive
            trailing_price = trade.open_price * (1 + trail_at)

            if trade.sl_highest is None or trailing_price > trade.sl_highest:
                trade.sl_highest = trailing_price

            if row["Low"] <= trade.sl_highest:
                exit_price = trade.sl_highest
                return True, exit_price, "trailing_stop"

        return False, 0.0, ""

    def _compute_stats(
        self,
        trades: List[Trade],
        equity_curve: List[float],
        timestamps: List[pd.Timestamp],
        pair: str,
        final_capital: float,
    ) -> BacktestResult:
        result = BacktestResult(pair=pair)
        result.trades = trades
        result.equity_curve = equity_curve
        result.timestamps = timestamps
        result.total_trades = len(trades)

        if not trades:
            return result

        wins = [t for t in trades if t.profit_abs > 0]
        losses = [t for t in trades if t.profit_abs <= 0]
        result.wins = len(wins)
        result.losses = len(losses)
        result.win_rate = (result.wins / result.total_trades * 100) if result.total_trades > 0 else 0

        result.total_profit = sum(t.profit_abs for t in trades)
        result.total_fees = sum(t.fee_open + t.fee_close for t in trades)

        gross_profit = sum(t.profit_abs for t in wins)
        gross_loss = abs(sum(t.profit_abs for t in losses))
        result.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        if len(equity_curve) > 1:
            equity = np.array(equity_curve)
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            result.max_drawdown = abs(dd.min() * 100)

            returns = np.diff(equity) / equity[:-1]
            if len(returns) > 1 and np.std(returns) > 0:
                result.sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(365)
                downside = returns[returns < 0]
                if len(downside) > 0:
                    result.sortino_ratio = np.mean(returns) / np.std(downside) * np.sqrt(365)

        result.avg_profit = np.mean([t.profit_abs for t in trades]) if trades else 0
        result.avg_profit_win = np.mean([t.profit_abs for t in wins]) if wins else 0
        result.avg_loss = np.mean([t.profit_abs for t in losses]) if losses else 0

        if trades:
            durations = [t.duration for t in trades if t.close_date]
            result.avg_hold_time = sum(durations, timedelta(0)) / len(durations) if durations else timedelta(0)

        return result

    def summary(self) -> pd.DataFrame:
        rows = []
        for pair, r in self.results.items():
            rows.append({
                "Pair": pair,
                "Trades": r.total_trades,
                "Win%": round(r.win_rate, 1),
                "Profit": round(r.total_profit, 2),
                "PF": round(r.profit_factor, 2),
                "MaxDD%": round(r.max_drawdown, 1),
                "Sharpe": round(r.sharpe_ratio, 2),
                "AvgHold": str(r.avg_hold_time).split(".")[0] if r.avg_hold_time else "0",
            })
        return pd.DataFrame(rows).sort_values("Profit", ascending=False)
