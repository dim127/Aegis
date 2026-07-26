import numpy as np
from typing import List, Dict


def sharpe_loss(results: List[Dict]) -> float:
    profits = [t.get("profit_ratio", 0) for t in results]
    if len(profits) < 2:
        return 0.0
    returns = np.array(profits)
    if np.std(returns) == 0:
        return 0.0
    return np.mean(returns) / np.std(returns) * np.sqrt(365)


def sortino_loss(results: List[Dict]) -> float:
    profits = [t.get("profit_ratio", 0) for t in results]
    if len(profits) < 2:
        return 0.0
    returns = np.array(profits)
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0
    return np.mean(returns) / np.std(downside) * np.sqrt(365)


def calmar_loss(results: List[Dict]) -> float:
    profits = [t.get("profit_ratio", 0) for t in results]
    if len(profits) < 2:
        return 0.0
    total_return = sum(profits)
    peak = np.maximum.accumulate(np.array(profits))
    dd = (np.array(profits) - peak) / peak
    max_dd = abs(min(dd)) if len(dd) > 0 else 1.0
    if max_dd == 0:
        return 0.0
    return total_return / max_dd


def profit_loss(results: List[Dict]) -> float:
    total_profit = sum(t.get("profit_abs", 0) for t in results)
    return total_profit


def profit_factor_loss(results: List[Dict]) -> float:
    gross_profit = sum(t.get("profit_abs", 0) for t in results if t.get("profit_abs", 0) > 0)
    gross_loss = abs(sum(t.get("profit_abs", 0) for t in results if t.get("profit_abs", 0) < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def win_rate_loss(results: List[Dict]) -> float:
    if not results:
        return 0.0
    wins = sum(1 for t in results if t.get("profit_abs", 0) > 0)
    return wins / len(results)


def multi_metric_loss(results: List[Dict]) -> float:
    if not results:
        return -float("inf")
    pf = profit_factor_loss(results)
    sharpe = sharpe_loss(results)
    wr = win_rate_loss(results)
    total_profit = profit_loss(results)
    return total_profit * (0.3 * pf + 0.3 * sharpe + 0.2 * wr)


LOSS_FUNCTIONS = {
    "sharpe": sharpe_loss,
    "sortino": sortino_loss,
    "calmar": calmar_loss,
    "profit": profit_loss,
    "profit_factor": profit_factor_loss,
    "win_rate": win_rate_loss,
    "multi_metric": multi_metric_loss,
}
