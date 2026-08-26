from __future__ import annotations

from typing import Dict, Iterable, List

from alpaca_bot.strategies.base import Signal, Side, Strategy
from alpaca_bot.strategies.breakout import BreakoutStrategy
from alpaca_bot.strategies.mean_reversion import MeanReversionStrategy
from alpaca_bot.strategies.momentum import MomentumStrategy
from alpaca_bot.strategies.vwap import VwapStrategy

REGISTRY: Dict[str, Strategy] = {
    "momentum": MomentumStrategy(),
    "mean_reversion": MeanReversionStrategy(),
    "breakout": BreakoutStrategy(),
    "vwap": VwapStrategy(),
}


def load_strategies(names: Iterable[str]) -> List[Strategy]:
    out: List[Strategy] = []
    for name in names:
        key = name.strip().lower()
        if key in REGISTRY:
            out.append(REGISTRY[key])
    return out


def best_signal(signals: List[Signal], min_score: float) -> Signal | None:
    actionable = [
        s
        for s in signals
        if s.side == Side.BUY and s.score >= min_score
    ]
    if not actionable:
        return None
    return max(actionable, key=lambda s: s.score)


def sell_signals(signals: List[Signal], min_score: float = 0.5) -> List[Signal]:
    return [s for s in signals if s.side == Side.SELL and s.score >= min_score]
