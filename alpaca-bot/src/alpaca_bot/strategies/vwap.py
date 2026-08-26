from __future__ import annotations

import pandas as pd

from alpaca_bot.strategies.base import Side, Signal, Strategy


class VwapStrategy(Strategy):
    """Intraday VWAP reclaim / rejection — classic day-trade edge."""

    name = "vwap"

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        if len(df) < 20 or pd.isna(df["vwap"].iloc[-1]):
            return Signal(symbol, Side.HOLD, 0.0, self.name, "insufficient data")

        row = df.iloc[-1]
        prev = df.iloc[-2]
        atr = float(row["atr_14"]) if not pd.isna(row["atr_14"]) else None
        price = float(row["close"])
        vwap = float(row["vwap"])
        prev_close = float(prev["close"])
        prev_vwap = float(prev["vwap"]) if not pd.isna(prev["vwap"]) else vwap

        reclaim = prev_close <= prev_vwap and price > vwap
        holding = price > vwap and row["ema_9"] > vwap
        vol_ok = float(row["volume"]) >= 1.1 * float(row["vol_sma_20"] or 1)

        if reclaim and vol_ok:
            distance = abs(price - vwap) / max(price, 1e-9)
            # Wider reclaim distance = stronger disagreement with fair value
            score = min(0.5 + min(distance * 80, 0.3) + 0.1, 0.95)
            stop = vwap - (0.8 * atr if atr else price * 0.006)
            target = price + (2.0 * atr if atr else price * 0.015)
            return Signal(
                symbol=symbol,
                side=Side.BUY,
                score=score,
                strategy=self.name,
                reason="VWAP reclaim with volume",
                stop_price=stop,
                take_profit=target,
                atr=atr,
            )

        if holding and row["rsi_14"] >= 55 and row["macd_hist"] > 0 and vol_ok:
            return Signal(
                symbol=symbol,
                side=Side.BUY,
                score=0.52,
                strategy=self.name,
                reason="holding above VWAP with momentum",
                stop_price=vwap - (0.5 * atr if atr else price * 0.004),
                take_profit=price + (1.8 * atr if atr else price * 0.012),
                atr=atr,
            )

        reject = prev_close >= prev_vwap and price < vwap and row["rsi_14"] < 45
        if reject:
            return Signal(
                symbol=symbol,
                side=Side.SELL,
                score=0.55,
                strategy=self.name,
                reason="VWAP rejection",
                atr=atr,
            )

        return Signal(symbol, Side.HOLD, 0.0, self.name, "no VWAP edge")
