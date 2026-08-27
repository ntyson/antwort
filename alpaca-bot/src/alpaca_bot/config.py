from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


PROFILE_DEFAULTS = {
    RiskProfile.CONSERVATIVE: {
        "max_position_pct": 0.05,
        "max_positions": 3,
        "max_daily_loss_pct": 1.5,
        "risk_per_trade_pct": 0.5,
        "min_signal_score": 0.65,
    },
    RiskProfile.MODERATE: {
        "max_position_pct": 0.10,
        "max_positions": 5,
        "max_daily_loss_pct": 2.5,
        "risk_per_trade_pct": 1.0,
        "min_signal_score": 0.55,
    },
    RiskProfile.AGGRESSIVE: {
        "max_position_pct": 0.15,
        "max_positions": 8,
        "max_daily_loss_pct": 4.0,
        "risk_per_trade_pct": 1.5,
        "min_signal_score": 0.45,
    },
}


DEFAULT_WATCHLIST = [
    "SPY",
    "QQQ",
    "IWM",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AMD",
    "AVGO",
    "NFLX",
    "CRM",
    "COST",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    alpaca_api_key: str = Field(default="", alias="ALPACA_API_KEY")
    alpaca_secret_key: str = Field(default="", alias="ALPACA_SECRET_KEY")
    alpaca_paper: bool = Field(default=True, alias="ALPACA_PAPER")

    risk_profile: RiskProfile = Field(default=RiskProfile.AGGRESSIVE, alias="RISK_PROFILE")
    loop_interval_seconds: int = Field(default=60, alias="LOOP_INTERVAL_SECONDS")
    bar_timeframe: str = Field(default="5Min", alias="BAR_TIMEFRAME")
    lookback_bars: int = Field(default=120, alias="LOOKBACK_BARS")

    max_position_pct: float | None = Field(default=None, alias="MAX_POSITION_PCT")
    max_positions: int | None = Field(default=None, alias="MAX_POSITIONS")
    max_daily_loss_pct: float | None = Field(default=None, alias="MAX_DAILY_LOSS_PCT")
    risk_per_trade_pct: float | None = Field(default=None, alias="RISK_PER_TRADE_PCT")
    min_signal_score: float | None = Field(default=None, alias="MIN_SIGNAL_SCORE")

    stop_atr_mult: float = Field(default=1.5, alias="STOP_ATR_MULT")
    take_profit_r: float = Field(default=2.0, alias="TAKE_PROFIT_R")
    trail_atr_mult: float = Field(default=1.2, alias="TRAIL_ATR_MULT")

    # Survival mode: tighten when day, peak giveback, or any big loser
    survival_drawdown_pct: float = Field(default=2.0, alias="SURVIVAL_DRAWDOWN_PCT")
    survival_giveback_pct: float = Field(default=0.5, alias="SURVIVAL_GIVEBACK_PCT")
    survival_position_loss_pct: float = Field(default=1.5, alias="SURVIVAL_POSITION_LOSS_PCT")
    position_cut_pct: float = Field(default=2.0, alias="POSITION_CUT_PCT")
    survival_position_cut_pct: float = Field(default=1.0, alias="SURVIVAL_POSITION_CUT_PCT")
    # Hard stop: flatten + halt for the day
    max_weekly_loss_pct: float = Field(default=8.0, alias="MAX_WEEKLY_LOSS_PCT")

    flatten_minutes_before_close: int = Field(default=10, alias="FLATTEN_MINUTES_BEFORE_CLOSE")
    pdt_guard: bool = Field(default=True, alias="PDT_GUARD")
    pdt_equity_threshold: float = Field(default=25_000.0, alias="PDT_EQUITY_THRESHOLD")

    strategies: str = Field(
        default="momentum,vwap,breakout,mean_reversion",
        alias="STRATEGIES",
    )
    watchlist: str = Field(default=",".join(DEFAULT_WATCHLIST), alias="WATCHLIST")

    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")
    dry_run: bool = Field(default=False, alias="DRY_RUN")

    # Daily recap delivery (pick one channel)
    recap_email_to: str = Field(default="", alias="RECAP_EMAIL_TO")
    recap_webhook_url: str = Field(default="", alias="RECAP_WEBHOOK_URL")
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")

    def resolved(self) -> "Settings":
        """Fill profile defaults for any unset risk knobs."""
        defaults = PROFILE_DEFAULTS[self.risk_profile]
        data = self.model_dump()
        for key, value in defaults.items():
            if data.get(key) is None:
                setattr(self, key, value)
        return self

    def strategy_list(self) -> List[str]:
        return [s.strip().lower() for s in self.strategies.split(",") if s.strip()]

    def watchlist_symbols(self) -> List[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings().resolved()
