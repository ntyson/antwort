from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    score: float  # 0..1 conviction
    strategy: str
    reason: str
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    atr: Optional[float] = None

    @property
    def is_actionable(self) -> bool:
        return self.side in (Side.BUY, Side.SELL) and self.score > 0


class Strategy:
    name: str = "base"

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        raise NotImplementedError
