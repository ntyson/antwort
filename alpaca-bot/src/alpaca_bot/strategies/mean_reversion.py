from __future__ import annotations

import pandas as pd

from alpaca_bot.strategies.base import Side, Signal, Strategy


class MeanReversionStrategy(Strategy):
    """Fade lower Bollinger band with RSI oversold, mean toward mid-band."""

    name = "mean_reversion"

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        if len(df) < 30 or pd.isna(df["bb_lower"].iloc[-1]):
            return Signal(symbol, Side.HOLD, 0.0, self.name, "insufficient data")

        row = df.iloc[-1]
        atr = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else None
        price = float(row["close"])

        # Avoid catching knives in strong downtrends
        if row["ema_21"] < row["ema_50"] and row["close"] < row["ema_21"]:
            return Signal(symbol, Side.HOLD, 0.0, self.name, "downtrend filter")

        if price <= row["bb_lower"] and row["rsi_14"] <= 35:
            depth = (row["bb_mid"] - price) / max(row["bb_mid"] - row["bb_lower"], 1e-9)
            score = min(0.45 + 0.35 * float(depth) + (0.1 if row["rsi_14"] < 30 else 0), 0.95)
            stop = price - (1.2 * atr if atr else price * 0.01)
            target = float(row["bb_mid"])
            return Signal(
                symbol=symbol,
                side=Side.BUY,
                score=score,
                strategy=self.name,
                reason="BB lower + RSI oversold",
                stop_price=stop,
                take_profit=target,
                atr=atr,
            )

        if price >= row["bb_upper"] and row["rsi_14"] >= 70:
            return Signal(
                symbol=symbol,
                side=Side.SELL,
                score=0.55,
                strategy=self.name,
                reason="BB upper + RSI overbought",
                atr=atr,
            )

        return Signal(symbol, Side.HOLD, 0.0, self.name, "no mean-reversion edge")
