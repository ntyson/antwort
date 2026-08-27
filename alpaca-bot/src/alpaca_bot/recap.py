from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from alpaca_bot.client import AlpacaClient
from alpaca_bot.config import Settings
from alpaca_bot.risk import RiskManager
from alpaca_bot.state import StateStore

ET = ZoneInfo("America/New_York")


@dataclass
class DailyRecap:
    trading_day: str
    paper: bool
    equity_start: float
    equity_end: float
    day_pl_dollars: float
    day_pl_pct: float
    cash: float
    open_positions: int
    risk_mode: str
    entries: list[dict[str, Any]]
    exits: list[dict[str, Any]]
    cycles: int
    orders_placed: int

    @property
    def subject(self) -> str:
        sign = "+" if self.day_pl_dollars >= 0 else ""
        mode = "Paper" if self.paper else "Live"
        return (
            f"Alpaca bot {mode} recap {self.trading_day}: "
            f"{sign}${self.day_pl_dollars:,.2f} ({self.day_pl_pct:+.2f}%)"
        )

    def to_text(self) -> str:
        sign = "+" if self.day_pl_dollars >= 0 else ""
        lines = [
            f"Alpaca Day Bot — Daily Recap ({self.trading_day})",
            "=" * 48,
            f"Account: {'Paper' if self.paper else 'Live'}",
            f"Risk mode: {self.risk_mode}",
            "",
            "Performance",
            f"  Start equity:  ${self.equity_start:,.2f}",
            f"  End equity:    ${self.equity_end:,.2f}",
            f"  Day P/L:       {sign}${self.day_pl_dollars:,.2f} ({self.day_pl_pct:+.2f}%)",
            f"  Cash:          ${self.cash:,.2f}",
            f"  Open positions at close: {self.open_positions}",
            "",
            f"Bot activity ({self.cycles} cycles, {self.orders_placed} orders placed)",
        ]
        if self.entries:
            lines.append("")
            lines.append("Entries")
            for t in self.entries:
                lines.append(
                    f"  • {t['symbol']} {t['side']} x{t['qty']:.0f} "
                    f"[{t['strategy']}] score={t['score']:.2f}"
                )
        else:
            lines.append("")
            lines.append("Entries: none logged today")

        if self.exits:
            lines.append("")
            lines.append("Exits")
            for e in self.exits:
                lines.append(f"  • {e.get('symbol', '?')} — {e.get('reason', 'exit')}")
        else:
            lines.append("")
            lines.append("Exits: none logged today")

        lines.extend(
            [
                "",
                "—",
                "Automated recap from alpaca-bot. Not investment advice.",
            ]
        )
        return "\n".join(lines)

    def to_html(self) -> str:
        sign = "+" if self.day_pl_dollars >= 0 else ""
        color = "#16a34a" if self.day_pl_dollars >= 0 else "#dc2626"
        rows = "".join(
            f"<tr><td>{t['symbol']}</td><td>{t['side']}</td>"
            f"<td>{t['qty']:.0f}</td><td>{t['strategy']}</td>"
            f"<td>{t['score']:.2f}</td></tr>"
            for t in self.entries
        )
        exit_rows = "".join(
            f"<tr><td>{e.get('symbol', '?')}</td><td>{e.get('reason', 'exit')}</td></tr>"
            for e in self.exits
        )
        return f"""
<html><body style="font-family: system-ui, sans-serif; color: #111;">
<h2>Alpaca Day Bot — {self.trading_day}</h2>
<p><strong>{'Paper' if self.paper else 'Live'}</strong> · Risk mode: {self.risk_mode}</p>
<table style="border-collapse: collapse;">
<tr><td style="padding:4px 12px 4px 0;">Start equity</td><td>${self.equity_start:,.2f}</td></tr>
<tr><td style="padding:4px 12px 4px 0;">End equity</td><td>${self.equity_end:,.2f}</td></tr>
<tr><td style="padding:4px 12px 4px 0;">Day P/L</td>
<td style="color:{color}; font-weight:600;">{sign}${self.day_pl_dollars:,.2f} ({self.day_pl_pct:+.2f}%)</td></tr>
<tr><td style="padding:4px 12px 4px 0;">Cash</td><td>${self.cash:,.2f}</td></tr>
<tr><td style="padding:4px 12px 4px 0;">Open positions</td><td>{self.open_positions}</td></tr>
</table>
<p>{self.cycles} cycles · {self.orders_placed} orders placed today</p>
<h3>Entries</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse;">
<tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Strategy</th><th>Score</th></tr>
{rows or '<tr><td colspan="5">None</td></tr>'}
</table>
<h3>Exits</h3>
<table border="1" cellpadding="6" style="border-collapse:collapse;">
<tr><th>Symbol</th><th>Reason</th></tr>
{exit_rows or '<tr><td colspan="2">None</td></tr>'}
</table>
<p style="color:#666;font-size:12px;">Automated recap. Not investment advice.</p>
</body></html>
"""


def _today_et() -> date:
    return datetime.now(ET).date()


def build_daily_recap(
    settings: Settings,
    client: AlpacaClient,
    store: StateStore,
    risk: RiskManager | None = None,
    for_day: date | None = None,
) -> DailyRecap:
    day = for_day or _today_et()
    day_str = day.isoformat()
    acct = client.account_snapshot()
    risk = risk or RiskManager(settings, store)
    mode = risk.sync_mode(acct)

    start_raw = store.get_meta("day_start_equity")
    if store.get_meta("day_start_date") != day_str or not start_raw:
        equity_start = float(acct.last_equity or acct.equity)
    else:
        equity_start = float(start_raw)

    equity_end = acct.equity
    day_pl = equity_end - equity_start
    day_pl_pct = (day_pl / equity_start * 100) if equity_start else 0.0

    entries = store.trades_for_date(day_str)
    exits = store.exits_for_date(day_str)
    activity = store.cycle_stats_for_date(day_str)

    return DailyRecap(
        trading_day=day_str,
        paper=settings.alpaca_paper,
        equity_start=equity_start,
        equity_end=equity_end,
        day_pl_dollars=day_pl,
        day_pl_pct=day_pl_pct,
        cash=acct.cash,
        open_positions=acct.open_positions,
        risk_mode=mode.value,
        entries=entries,
        exits=exits,
        cycles=activity["cycles"],
        orders_placed=activity["orders"],
    )


def send_daily_recap_if_due(
    settings: Settings,
    client: AlpacaClient,
    store: StateStore,
    risk: RiskManager | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Send recap once per ET trading day, after the session ends."""
    from alpaca_bot.notify import send_recap

    now = datetime.now(ET)
    day_str = now.date().isoformat()
    sent_key = f"recap_sent_{day_str}"

    if not force:
        if store.get_meta(sent_key) == "1":
            return {"sent": False, "reason": "already_sent"}
        if now.weekday() >= 5:
            return {"sent": False, "reason": "weekend"}
        if client.is_market_open():
            return {"sent": False, "reason": "market_still_open"}
        # Only send after regular close (4:00 PM ET)
        if now.hour < 16 or (now.hour == 16 and now.minute < 1):
            return {"sent": False, "reason": "before_close_window"}

    recap = build_daily_recap(settings, client, store, risk)
    result = send_recap(settings, recap)
    if result.get("ok"):
        store.set_meta(sent_key, "1")
        store.log_event("recap_sent", {"day": day_str, "channel": result.get("channel")})
        recap_path = settings.log_dir / f"recap-{day_str}.txt"
        recap_path.parent.mkdir(parents=True, exist_ok=True)
        recap_path.write_text(recap.to_text(), encoding="utf-8")
    else:
        store.log_event("recap_failed", {"day": day_str, "error": result.get("error")})
    return result
