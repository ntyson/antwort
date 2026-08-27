from datetime import date

from alpaca_bot.recap import DailyRecap


def test_daily_recap_subject_and_text():
    recap = DailyRecap(
        trading_day="2026-08-27",
        paper=True,
        equity_start=100_000.0,
        equity_end=101_250.50,
        day_pl_dollars=1250.50,
        day_pl_pct=1.25,
        cash=50_000.0,
        open_positions=0,
        risk_mode="normal",
        entries=[
            {"symbol": "META", "side": "buy", "qty": 27, "strategy": "breakout", "score": 0.95}
        ],
        exits=[{"symbol": "SPY", "reason": "eod flatten"}],
        cycles=120,
        orders_placed=6,
    )
    assert "+$1,250.50" in recap.subject
    assert "META" in recap.to_text()
    assert "Paper" in recap.to_text()
    assert "<html>" in recap.to_html()


def test_state_trades_for_date(tmp_path):
    from alpaca_bot.state import StateStore, TradeRecord

    store = StateStore(tmp_path / "t.db")
    store.record_trade(
        TradeRecord(
            symbol="SPY",
            side="buy",
            qty=10,
            strategy="momentum",
            score=0.8,
            reason="test",
            created_at="2026-08-27T14:00:00+00:00",
        )
    )
    rows = store.trades_for_date("2026-08-27")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert store.cycle_stats_for_date("2026-08-27") == {"cycles": 0, "orders": 0}
