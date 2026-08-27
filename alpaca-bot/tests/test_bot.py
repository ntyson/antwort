from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpaca_bot.backtest import run_backtest, _synthetic_bars
from alpaca_bot.config import RiskProfile, Settings
from alpaca_bot.indicators import enrich, rsi, ema
from alpaca_bot.risk import AccountSnapshot, RiskManager, TradingMode
from alpaca_bot.state import StateStore
from alpaca_bot.strategies import best_signal, load_strategies
from alpaca_bot.strategies.base import Side, Signal
from alpaca_bot.strategies.momentum import MomentumStrategy
from alpaca_bot.strategies.vwap import VwapStrategy


def test_indicators_enrich():
    df = _synthetic_bars(200, seed=1)
    out = enrich(df)
    assert "rsi_14" in out.columns
    assert "vwap" in out.columns
    assert out["ema_9"].notna().sum() > 50


def test_rsi_bounds():
    s = pd.Series(np.linspace(100, 120, 50))
    values = rsi(s).dropna()
    assert values.min() >= 0
    assert values.max() <= 100


def test_strategies_return_signals():
    df = enrich(_synthetic_bars(200, seed=7))
    for strat in load_strategies(["momentum", "vwap", "breakout", "mean_reversion"]):
        sig = strat.evaluate("TEST", df)
        assert isinstance(sig, Signal)
        assert sig.strategy == strat.name


def test_best_signal_picks_highest():
    signals = [
        Signal("A", Side.BUY, 0.4, "m", "x"),
        Signal("B", Side.BUY, 0.9, "v", "y"),
        Signal("C", Side.HOLD, 0.0, "m", "z"),
    ]
    best = best_signal(signals, min_score=0.5)
    assert best is not None
    assert best.symbol == "B"


def test_risk_survival_from_position_loss(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="aggressive",
        SURVIVAL_ENABLED=True,
        SURVIVAL_POSITION_LOSS_PCT=1.5,
    ).resolved()
    store = StateStore(tmp_path / "t4.db")
    risk = RiskManager(settings, store)
    store.set_meta("day_start_date", __import__("datetime").date.today().isoformat())
    store.set_meta("day_start_equity", "102000")
    store.set_meta("day_peak_equity", "102500")

    class Pos:
        unrealized_plpc = -0.028

    acct = AccountSnapshot(
        equity=102_000, cash=50_000, buying_power=200_000, day_pl_pct=0.5, open_positions=1
    )
    assert risk.sync_mode(acct, {"META": Pos()}) == TradingMode.SURVIVAL


def test_position_cut_threshold():
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        POSITION_CUT_PCT=2.0,
        SURVIVAL_POSITION_CUT_PCT=1.0,
    ).resolved()
    risk = RiskManager(settings, StateStore(Path("/tmp/x.db")))  # noqa: S108
    risk.mode = TradingMode.NORMAL
    assert risk.position_cut_threshold() == -2.0
    risk.mode = TradingMode.SURVIVAL
    assert risk.position_cut_threshold() == -1.0


def test_risk_survival_sticky_for_session(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="aggressive",
        SURVIVAL_ENABLED=True,
    ).resolved()
    store = StateStore(tmp_path / "t5.db")
    risk = RiskManager(settings, store)
    store.set_meta("day_start_date", __import__("datetime").date.today().isoformat())
    store.set_meta("day_start_equity", "102000")
    store.set_meta("day_peak_equity", "102500")
    store.set_meta("survival_today", "1")

    class Pos:
        unrealized_plpc = -0.005

    acct = AccountSnapshot(
        equity=102_100, cash=50_000, buying_power=200_000, day_pl_pct=0.5, open_positions=1
    )
    assert risk.sync_mode(acct, {"SPY": Pos()}) == TradingMode.SURVIVAL


def test_risk_blocks_reentry_after_cut(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        PDT_GUARD=False,
        BLOCK_REENTRY_AFTER_CUT=True,
    ).resolved()
    store = StateStore(tmp_path / "t6.db")
    store.set_meta("cut_symbols_today", "META")
    risk = RiskManager(settings, store)
    acct = AccountSnapshot(100_000, 50_000, 200_000, 0, 0)
    sig = Signal("META", Side.BUY, 0.95, "breakout", "x", stop_price=550, atr=5)
    d = risk.approve(sig, acct, price=570, already_held=False)
    assert not d.approved
    assert "cut earlier" in d.reason


def test_max_growth_skips_survival(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="max",
    ).resolved()
    assert settings.is_max_growth()
    assert settings.max_position_pct == 0.28
    store = StateStore(tmp_path / "tmax.db")
    risk = RiskManager(settings, store)
    store.set_meta("day_start_date", __import__("datetime").date.today().isoformat())
    store.set_meta("day_start_equity", "102000")
    store.set_meta("day_peak_equity", "102500")

    class Pos:
        unrealized_plpc = -0.05

    acct = AccountSnapshot(
        equity=100_000, cash=50_000, buying_power=200_000, day_pl_pct=-2.0, open_positions=1
    )
    assert risk.sync_mode(acct, {"META": Pos()}) == TradingMode.NORMAL


def test_max_sprint_sizes_up_when_behind(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="max",
        PDT_GUARD=False,
        MAX_POSITION_PCT=0.5,
        SPRINT_SIZE_MULT=1.5,
    ).resolved()
    risk = RiskManager(settings, StateStore(tmp_path / "tsprint.db"))
    sig = Signal("NVDA", Side.BUY, 0.9, "momentum", "x", stop_price=90.0, atr=5.0)
    flat = AccountSnapshot(100_000, 50_000, 200_000, 0.5, 0)
    behind = AccountSnapshot(100_000, 50_000, 200_000, -1.0, 0)
    d_flat = risk.approve(sig, flat, price=100.0, already_held=False)
    d_behind = risk.approve(sig, behind, price=100.0, already_held=False)
    assert d_flat.approved and d_behind.approved
    assert d_behind.qty > d_flat.qty


def test_risk_survival_and_halt(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="aggressive",
        SURVIVAL_ENABLED=True,
        SURVIVAL_DRAWDOWN_PCT=1.0,
        MAX_DAILY_LOSS_PCT=3.0,
    ).resolved()
    store = StateStore(tmp_path / "t.db")
    risk = RiskManager(settings, store)

    acct = AccountSnapshot(
        equity=100_000, cash=100_000, buying_power=200_000, day_pl_pct=0, open_positions=0
    )
    assert risk.sync_mode(acct) == TradingMode.NORMAL

    # Simulate day start then drawdown into survival
    store.set_meta("day_start_date", __import__("datetime").date.today().isoformat())
    store.set_meta("day_start_equity", "100000")
    risk.day_start_equity = 100_000
    down = AccountSnapshot(
        equity=98_500, cash=98_500, buying_power=190_000, day_pl_pct=-1.5, open_positions=0
    )
    assert risk.sync_mode(down) == TradingMode.SURVIVAL
    assert "mean_reversion" not in risk.allowed_strategies()
    assert risk.min_score() > float(settings.min_signal_score)

    crushed = AccountSnapshot(
        equity=96_000, cash=96_000, buying_power=180_000, day_pl_pct=-4, open_positions=0
    )
    assert risk.sync_mode(crushed) == TradingMode.HALTED


def test_risk_approve_sizes_by_score(tmp_path):
    settings = Settings(
        ALPACA_API_KEY="x",
        ALPACA_SECRET_KEY="y",
        RISK_PROFILE="aggressive",
        PDT_GUARD=False,
        MAX_POSITION_PCT=0.5,  # room for score-based risk sizing to matter
    ).resolved()
    store = StateStore(tmp_path / "t2.db")
    risk = RiskManager(settings, store)
    acct = AccountSnapshot(
        equity=100_000, cash=50_000, buying_power=200_000, day_pl_pct=0, open_positions=0
    )
    # Wide stop so max-notional does not bind first
    weak = Signal("SPY", Side.BUY, 0.5, "vwap", "ok", stop_price=90.0, atr=5.0)
    strong = Signal("SPY", Side.BUY, 0.95, "vwap", "ok", stop_price=90.0, atr=5.0)
    d1 = risk.approve(weak, acct, price=100.0, already_held=False)
    d2 = risk.approve(strong, acct, price=100.0, already_held=False)
    assert d1.approved and d2.approved
    assert d2.qty > d1.qty


def test_no_average_down(tmp_path):
    settings = Settings(ALPACA_API_KEY="x", ALPACA_SECRET_KEY="y", PDT_GUARD=False).resolved()
    risk = RiskManager(settings, StateStore(tmp_path / "t3.db"))
    acct = AccountSnapshot(100_000, 50_000, 100_000, 0, 1)
    sig = Signal("AAPL", Side.BUY, 0.9, "momentum", "x", stop_price=190, atr=2)
    d = risk.approve(sig, acct, price=200, already_held=True)
    assert not d.approved


def test_backtest_runs():
    result = run_backtest(seed=3)
    assert "total_return_pct" in result
    assert result["trades"] >= 0
    assert result["ending_equity"] > 0


def test_profile_defaults():
    s = Settings(RISK_PROFILE="conservative").resolved()
    assert s.max_position_pct == 0.05
    assert s.risk_profile == RiskProfile.CONSERVATIVE
