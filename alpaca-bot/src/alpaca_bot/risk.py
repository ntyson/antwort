from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from alpaca_bot.config import Settings
from alpaca_bot.state import StateStore
from alpaca_bot.strategies.base import Signal


class TradingMode(str, Enum):
    NORMAL = "normal"
    SURVIVAL = "survival"  # same-session only, tighter filters
    HALTED = "halted"


@dataclass
class AccountSnapshot:
    equity: float
    cash: float
    buying_power: float
    day_pl_pct: float
    open_positions: int
    pattern_day_trader: bool = False


@dataclass
class RiskDecision:
    approved: bool
    qty: float
    reason: str
    mode: TradingMode


class RiskManager:
    """Deterministic risk gate — every signal passes through here before orders."""

    def __init__(self, settings: Settings, store: StateStore):
        self.settings = settings
        self.store = store
        self.mode = TradingMode.NORMAL
        self.day_start_equity: Optional[float] = None
        self.week_start_equity: Optional[float] = None
        self._halt_reason: str = ""

    def sync_mode(self, account: AccountSnapshot) -> TradingMode:
        today = date.today().isoformat()
        stored_day = self.store.get_meta("day_start_date")
        stored_equity = self.store.get_meta("day_start_equity")
        if stored_day != today or not stored_equity:
            self.store.set_meta("day_start_date", today)
            self.store.set_meta("day_start_equity", str(account.equity))
            self.day_start_equity = account.equity
        else:
            self.day_start_equity = float(stored_equity)

        week_key = date.today().isocalendar()
        week_id = f"{week_key.year}-W{week_key.week}"
        stored_week = self.store.get_meta("week_id")
        stored_week_eq = self.store.get_meta("week_start_equity")
        if stored_week != week_id or not stored_week_eq:
            self.store.set_meta("week_id", week_id)
            self.store.set_meta("week_start_equity", str(account.equity))
            self.week_start_equity = account.equity
        else:
            self.week_start_equity = float(stored_week_eq)

        day_dd = 0.0
        if self.day_start_equity and self.day_start_equity > 0:
            day_dd = (self.day_start_equity - account.equity) / self.day_start_equity * 100

        week_dd = 0.0
        if self.week_start_equity and self.week_start_equity > 0:
            week_dd = (self.week_start_equity - account.equity) / self.week_start_equity * 100

        halted = self.store.get_meta("halted") == "1"
        if halted:
            self.mode = TradingMode.HALTED
            self._halt_reason = self.store.get_meta("halt_reason") or "manual halt"
            return self.mode

        max_daily = float(self.settings.max_daily_loss_pct or 3.0)
        max_weekly = float(self.settings.max_weekly_loss_pct)
        survival_dd = float(self.settings.survival_drawdown_pct)

        if day_dd >= max_daily or week_dd >= max_weekly:
            self.halt(f"drawdown circuit breaker day={day_dd:.2f}% week={week_dd:.2f}%")
            return self.mode

        if day_dd >= survival_dd or account.equity < (self.day_start_equity or account.equity) * 0.985:
            # Tweet-style survival: tighten when capital is under threat
            if self.mode != TradingMode.SURVIVAL:
                self.store.log_event(
                    "mode_change",
                    {
                        "from": self.mode.value,
                        "to": TradingMode.SURVIVAL.value,
                        "day_dd_pct": day_dd,
                        "equity": account.equity,
                    },
                )
            self.mode = TradingMode.SURVIVAL
        else:
            self.mode = TradingMode.NORMAL

        return self.mode

    def halt(self, reason: str) -> None:
        self.mode = TradingMode.HALTED
        self._halt_reason = reason
        self.store.set_meta("halted", "1")
        self.store.set_meta("halt_reason", reason)
        self.store.log_event("halt", {"reason": reason})

    def clear_halt(self) -> None:
        self.store.set_meta("halted", "0")
        self.mode = TradingMode.NORMAL

    def min_score(self) -> float:
        base = float(self.settings.min_signal_score or 0.5)
        if self.mode == TradingMode.SURVIVAL:
            return min(0.95, base + 0.15)
        return base

    def allowed_strategies(self) -> set[str]:
        """Survival mode drops multi-bar mean reversion; prefers same-session VWAP/momentum."""
        if self.mode == TradingMode.SURVIVAL:
            return {"vwap", "momentum", "breakout"}
        return set(self.settings.strategy_list())

    def approve(
        self,
        signal: Signal,
        account: AccountSnapshot,
        price: float,
        already_held: bool,
    ) -> RiskDecision:
        if self.mode == TradingMode.HALTED:
            return RiskDecision(False, 0, f"halted: {self._halt_reason}", self.mode)

        if signal.strategy not in self.allowed_strategies():
            return RiskDecision(
                False, 0, f"strategy {signal.strategy} disabled in {self.mode.value}", self.mode
            )

        if signal.score < self.min_score():
            return RiskDecision(
                False,
                0,
                f"score {signal.score:.2f} < min {self.min_score():.2f}",
                self.mode,
            )

        max_positions = int(self.settings.max_positions or 5)
        if self.mode == TradingMode.SURVIVAL:
            max_positions = max(1, max_positions // 2)

        if not already_held and account.open_positions >= max_positions:
            return RiskDecision(False, 0, "max positions reached", self.mode)

        if already_held:
            return RiskDecision(False, 0, "already holding — no averaging down", self.mode)

        if self.settings.pdt_guard and account.equity < self.settings.pdt_equity_threshold:
            since = (date.today() - timedelta(days=7)).isoformat()
            if self.store.day_trade_count(since) >= 3:
                return RiskDecision(False, 0, "PDT guard: day-trade limit", self.mode)

        stop = signal.stop_price
        if not stop or stop >= price:
            atr = signal.atr or price * 0.01
            stop = price - float(self.settings.stop_atr_mult) * atr

        risk_per_share = max(price - stop, price * 0.002)
        risk_budget = account.equity * (float(self.settings.risk_per_trade_pct or 1.0) / 100.0)
        # Scale size by conviction (tweet: size up when disagreement is wide)
        risk_budget *= 0.5 + signal.score
        if self.mode == TradingMode.SURVIVAL:
            risk_budget *= 0.5

        qty = risk_budget / risk_per_share
        max_notional = account.equity * float(self.settings.max_position_pct or 0.1)
        if self.mode == TradingMode.SURVIVAL:
            max_notional *= 0.5
        qty = min(qty, max_notional / price, account.buying_power / price)
        qty = max(0.0, float(int(qty * 1000) / 1000))  # milli-share friendly

        if qty * price < 1.0 or qty <= 0:
            return RiskDecision(False, 0, "size too small", self.mode)

        return RiskDecision(True, qty, "approved", self.mode)
