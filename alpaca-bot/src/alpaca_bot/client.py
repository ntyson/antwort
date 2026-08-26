from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from alpaca_bot.config import Settings
from alpaca_bot.risk import AccountSnapshot

ET = ZoneInfo("America/New_York")

_TIMEFRAMES = {
    "1Min": TimeFrame.Minute,
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame.Hour,
    "1Day": TimeFrame.Day,
}


class AlpacaClient:
    def __init__(self, settings: Settings):
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ValueError(
                "Missing ALPACA_API_KEY / ALPACA_SECRET_KEY. "
                "Copy .env.example to .env and add paper keys from Alpaca."
            )
        self.settings = settings
        self.trading = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )
        self.data = StockHistoricalDataClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
        )

    def account_snapshot(self) -> AccountSnapshot:
        acct = self.trading.get_account()
        positions = self.trading.get_all_positions()
        equity = float(acct.equity)
        last_equity = float(acct.last_equity or equity)
        day_pl_pct = ((equity - last_equity) / last_equity * 100) if last_equity else 0.0
        return AccountSnapshot(
            equity=equity,
            cash=float(acct.cash),
            buying_power=float(acct.buying_power),
            day_pl_pct=day_pl_pct,
            open_positions=len(positions),
            pattern_day_trader=bool(getattr(acct, "pattern_day_trader", False)),
        )

    def positions_by_symbol(self) -> Dict[str, Any]:
        return {p.symbol: p for p in self.trading.get_all_positions()}

    def is_market_open(self) -> bool:
        clock = self.trading.get_clock()
        return bool(clock.is_open)

    def minutes_to_close(self) -> Optional[float]:
        clock = self.trading.get_clock()
        if not clock.is_open:
            return None
        now = clock.timestamp
        close = clock.next_close
        return (close - now).total_seconds() / 60.0

    def get_bars(self, symbol: str, limit: int | None = None) -> pd.DataFrame:
        limit = limit or self.settings.lookback_bars
        tf = _TIMEFRAMES.get(self.settings.bar_timeframe, TimeFrame(5, TimeFrameUnit.Minute))
        end = datetime.now(tz=ET)
        # Pull enough calendar time for the bar count
        start = end - timedelta(days=5)
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            limit=limit,
            feed=DataFeed.IEX,
        )
        bars = self.data.get_stock_bars(req)
        df = bars.df
        if df.empty:
            return df
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol)
        df = df.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            }
        )
        return df.tail(limit).copy()

    def submit_bracket_buy(
        self,
        symbol: str,
        qty: float,
        stop_price: float,
        take_profit: float,
    ) -> Any:
        # Round stop/limit to cents
        stop = round(stop_price, 2)
        tp = round(take_profit, 2)
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=tp),
            stop_loss=StopLossRequest(stop_price=stop),
        )
        return self.trading.submit_order(req)

    def submit_market(self, symbol: str, qty: float, side: OrderSide) -> Any:
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        return self.trading.submit_order(req)

    def close_position(self, symbol: str) -> Any:
        return self.trading.close_position(symbol)

    def close_all_positions(self) -> Any:
        return self.trading.close_all_positions(cancel_orders=True)

    def cancel_open_orders(self) -> None:
        self.trading.cancel_orders()
