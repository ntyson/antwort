from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from alpaca_bot.indicators import enrich
from alpaca_bot.strategies import best_signal, load_strategies
from alpaca_bot.strategies.base import Side

log = logging.getLogger(__name__)


def _synthetic_bars(
    n: int = 400,
    seed: int = 42,
    start_price: float = 100.0,
    drift: float = 0.00015,
    vol: float = 0.004,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start_price * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.0005, 0.004, n))
    low = close * (1 - rng.uniform(0.0005, 0.004, n))
    open_ = np.roll(close, 1)
    open_[0] = start_price
    volume = rng.integers(200_000, 2_000_000, n)
    idx = pd.date_range("2024-01-02 09:30", periods=n, freq="5min", tz="America/New_York")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def run_backtest(
    strategies: list[str] | None = None,
    min_score: float = 0.5,
    risk_per_trade: float = 0.01,
    starting_equity: float = 100_000.0,
    seed: int = 42,
) -> Dict:
    """Simple long-only event backtest on synthetic 5m bars (no look-ahead)."""
    strats = load_strategies(strategies or ["momentum", "vwap", "breakout", "mean_reversion"])
    df = enrich(_synthetic_bars(seed=seed))
    equity = starting_equity
    cash = starting_equity
    position = 0.0
    entry = 0.0
    stop = 0.0
    tp = 0.0
    trades = []
    equity_curve = []

    for i in range(60, len(df)):
        window = df.iloc[: i + 1]
        row = window.iloc[-1]
        price = float(row["close"])

        # Manage open position
        if position > 0:
            if price <= stop or price >= tp:
                pnl = (price - entry) * position
                cash += position * price
                trades.append({"pnl": pnl, "ret": pnl / starting_equity})
                position = 0.0
            equity = cash + position * price
            equity_curve.append(equity)
            continue

        signals = [s.evaluate("SYN", window) for s in strats]
        best = best_signal(signals, min_score)
        if not best or best.side != Side.BUY:
            equity_curve.append(cash)
            continue

        atr = best.atr or price * 0.01
        stop = best.stop_price or price - 1.5 * atr
        tp = best.take_profit or price + 2.0 * (price - stop)
        risk_per_share = max(price - stop, price * 0.002)
        qty = (equity * risk_per_trade * (0.5 + best.score)) / risk_per_share
        qty = min(qty, equity * 0.15 / price)
        if qty * price < 1:
            equity_curve.append(cash)
            continue
        position = qty
        entry = price
        cash -= qty * price
        equity = cash + position * price
        equity_curve.append(equity)

    if position > 0:
        price = float(df["close"].iloc[-1])
        pnl = (price - entry) * position
        cash += position * price
        trades.append({"pnl": pnl, "ret": pnl / starting_equity})
        equity = cash

    rets = [t["ret"] for t in trades]
    total_return = (equity - starting_equity) / starting_equity * 100
    win_rate = (
        sum(1 for t in trades if t["pnl"] > 0) / len(trades) * 100 if trades else 0.0
    )
    arr = np.array(equity_curve) if equity_curve else np.array([starting_equity])
    peak = np.maximum.accumulate(arr)
    max_dd = float(np.max((peak - arr) / peak) * 100) if len(arr) else 0.0

    return {
        "starting_equity": starting_equity,
        "ending_equity": round(equity, 2),
        "total_return_pct": round(total_return, 2),
        "trades": len(trades),
        "win_rate_pct": round(win_rate, 1),
        "max_drawdown_pct": round(max_dd, 2),
        "avg_trade_ret_pct": round(float(np.mean(rets) * 100) if rets else 0.0, 3),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_backtest(), indent=2))
