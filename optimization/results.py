from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import pandas as pd
import json


@dataclass
class HyperoptEpoch:
    epoch: int
    params: Dict[str, Any]
    loss: float
    results: List[Dict] = field(default_factory=list)
    total_profit: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    sharpe: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "epoch": self.epoch,
            "loss": round(self.loss, 4),
            "params": self.params,
            "total_profit": round(self.total_profit, 2),
            "win_rate": round(self.win_rate, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "total_trades": self.total_trades,
            "sharpe": round(self.sharpe, 2),
        }


class HyperoptResults:
    def __init__(self):
        self.epochs: List[HyperoptEpoch] = []
        self.total_epochs: int = 0
        self.best_epoch: Optional[HyperoptEpoch] = None

    def add_epoch(self, epoch: HyperoptEpoch):
        self.epochs.append(epoch)
        if self.best_epoch is None or epoch.loss > self.best_epoch.loss:
            self.best_epoch = epoch

    def to_dataframe(self) -> pd.DataFrame:
        rows = [e.to_dict() for e in self.epochs]
        return pd.DataFrame(rows)

    def best_params(self) -> Dict:
        return self.best_epoch.params if self.best_epoch else {}

    def summary(self) -> str:
        if not self.epochs:
            return "No hyperopt results"
        best = self.best_epoch
        lines = [
            f"Hyperopt Results ({len(self.epochs)} epochs)",
            f"Best epoch: #{best.epoch}",
            f"  Loss: {best.loss:.4f}",
            f"  Total Profit: {best.total_profit:.2f}",
            f"  Win Rate: {best.win_rate:.1%}",
            f"  Profit Factor: {best.profit_factor:.2f}",
            f"  Max Drawdown: {best.max_drawdown:.1%}",
            f"  Trades: {best.total_trades}",
            f"  Sharpe: {best.sharpe:.2f}",
            "Best Params:",
        ]
        for k, v in best.params.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)

    def to_json(self, path: str = None):
        data = {
            "total_epochs": len(self.epochs),
            "best_epoch": self.best_epoch.to_dict() if self.best_epoch else None,
            "epochs": [e.to_dict() for e in self.epochs],
        }
        if path:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        return data
