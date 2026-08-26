from __future__ import annotations

import pandas as pd

from alpaca_bot.strategies.base import Side, Signal, Strategy


class BreakoutStrategy(Strategy):
    """20-bar high breakout on expanding volume."""

    name = "breakout"

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        if len(df) < 25 or pd.isna(df["high_20"].iloc[-2]):
            return Signal(symbol, Side.HOLD, 0.0, self.name, "insufficient data")

        row = df.iloc[-1]
        prev_high = float(df["high_20"].iloc[-2])
        atr = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else None
        price = float(row["close"])
        vol_sma = float(row["vol_sma_20"]) if not pd.isna(row["vol_sma_20"]) else 0.0

        broke = price > prev_high and float(row["high"]) >= prev_high
        vol_expand = vol_sma > 0 and float(row["volume"]) >= 1.5 * vol_sma
        trend_ok = row["ema_21"] >= row["ema_50"] * 0.995

        if broke and vol_expand and trend_ok:
            extension = (price - prev_high) / max(prev_high, 1e-9)
            # Prefer fresh breakouts, not extended ones
            freshness = max(0.0, 1.0 - extension * 40)
            score = min(0.5 + 0.25 * freshness + 0.2, 0.96)
            stop = prev_high - (0.5 * atr if atr else price * 0.005)
            target = price + (2.5 * atr if atr else price * 0.02)
            return Signal(
                symbol=symbol,
                side=Side.BUY,
                score=score,
                strategy=self.name,
                reason=f"breakout above {prev_high:.2f} on volume",
                stop_price=stop,
                take_profit=target,
                atr=atr,
            )

        return Signal(symbol, Side.HOLD, 0.0, self.name, "no breakout")
