from __future__ import annotations

import pandas as pd

from alpaca_bot.strategies.base import Side, Signal, Strategy


class MomentumStrategy(Strategy):
    """Trend-following: EMA stack + MACD hist flip + RSI not overbought."""

    name = "momentum"

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        if len(df) < 60 or df["atr_14"].iloc[-1] != df["atr_14"].iloc[-1]:
            return Signal(symbol, Side.HOLD, 0.0, self.name, "insufficient data")

        row = df.iloc[-1]
        prev = df.iloc[-2]
        atr = float(row["atr_14"])
        price = float(row["close"])

        bullish_stack = row["ema_9"] > row["ema_21"] > row["ema_50"]
        macd_up = prev["macd_hist"] <= 0 and row["macd_hist"] > 0
        rsi_ok = 45 <= row["rsi_14"] <= 70
        vol_ok = row["volume"] >= 1.2 * (row["vol_sma_20"] or 0)

        if bullish_stack and (macd_up or row["macd_hist"] > 0) and rsi_ok:
            score = 0.55
            if macd_up:
                score += 0.15
            if vol_ok:
                score += 0.15
            if row["close"] > row["ema_9"]:
                score += 0.10
            score = min(score, 0.98)
            return Signal(
                symbol=symbol,
                side=Side.BUY,
                score=score,
                strategy=self.name,
                reason="EMA stack + MACD/RSI momentum",
                stop_price=price - 1.5 * atr,
                take_profit=price + 3.0 * atr,
                atr=atr,
            )

        # Exit / short bias for open long management is handled by exits module;
        # we only emit short signals if explicitly wanted — day bot is long-biased.
        bearish = row["ema_9"] < row["ema_21"] and row["macd_hist"] < 0 and row["rsi_14"] > 70
        if bearish:
            return Signal(
                symbol=symbol,
                side=Side.SELL,
                score=0.6,
                strategy=self.name,
                reason="momentum exhaustion",
                atr=atr,
            )

        return Signal(symbol, Side.HOLD, 0.0, self.name, "no momentum edge")
