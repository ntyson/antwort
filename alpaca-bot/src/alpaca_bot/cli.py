from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from alpaca_bot.backtest import run_backtest
from alpaca_bot.client import AlpacaClient
from alpaca_bot.config import Settings, get_settings
from alpaca_bot.health import start_health_server
from alpaca_bot.loop import TradingLoop
from alpaca_bot.recap import build_daily_recap, send_daily_recap_if_due
from alpaca_bot.risk import RiskManager
from alpaca_bot.state import StateStore

console = Console()


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(log_dir / "bot.log"),
        ],
    )


def build_loop(settings: Settings | None = None) -> TradingLoop:
    settings = (settings or get_settings()).resolved()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(settings.log_dir)
    store = StateStore(settings.data_dir / "bot.db")
    client = AlpacaClient(settings)
    risk = RiskManager(settings, store)
    return TradingLoop(settings, client, risk, store)


def cmd_status() -> int:
    settings = get_settings()
    client = AlpacaClient(settings)
    acct = client.account_snapshot()
    positions = client.positions_by_symbol()
    clock_open = client.is_market_open()

    table = Table(title="Alpaca Day Bot — Account")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Paper", str(settings.alpaca_paper))
    table.add_row("Market open", str(clock_open))
    table.add_row("Equity", f"${acct.equity:,.2f}")
    table.add_row("Cash", f"${acct.cash:,.2f}")
    table.add_row("Buying power", f"${acct.buying_power:,.2f}")
    table.add_row("Day P/L %", f"{acct.day_pl_pct:.2f}%")
    table.add_row("Positions", str(acct.open_positions))
    table.add_row("Risk profile", settings.risk_profile.value)
    table.add_row("Strategies", ", ".join(settings.strategy_list()))
    console.print(table)

    if positions:
        pt = Table(title="Open Positions")
        pt.add_column("Symbol")
        pt.add_column("Qty")
        pt.add_column("Entry")
        pt.add_column("P/L %")
        for sym, p in positions.items():
            pt.add_row(
                sym,
                str(p.qty),
                str(p.avg_entry_price),
                f"{float(p.unrealized_plpc or 0) * 100:.2f}%",
            )
        console.print(pt)
    return 0


def cmd_once() -> int:
    loop = build_loop()
    summary = loop.run_once()
    console.print(summary)
    return 0


def cmd_run() -> int:
    # Railway (and similar) set PORT and may health-check it
    start_health_server()

    settings = get_settings()
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        console.print(
            "[red]Missing ALPACA_API_KEY / ALPACA_SECRET_KEY.[/]\n"
            "Add them in Railway → Variables, then redeploy."
        )
        # Keep health server up so the platform doesn't flap while you add secrets
        logging.error("Waiting for Alpaca credentials — set env vars and redeploy")
        while True:
            time.sleep(3600)

    loop = build_loop(settings)
    store = StateStore(settings.data_dir / "bot.db")
    client = AlpacaClient(settings)
    risk = RiskManager(settings, store)

    console.print(
        f"[bold green]Starting autonomous loop[/] every {settings.loop_interval_seconds}s "
        f"(paper={settings.alpaca_paper}, profile={settings.risk_profile.value})"
    )
    if settings.recap_email_to or settings.recap_webhook_url or settings.resend_api_key:
        console.print(f"[dim]Daily recap → {settings.recap_email_to or 'webhook'} at market close (ET)[/]")
    else:
        console.print("[yellow]Daily recap not configured — set RECAP_EMAIL_TO + RESEND_API_KEY[/]")

    def tick():
        try:
            summary = loop.run_once()
            console.print(summary)
        except Exception as exc:  # noqa: BLE001
            logging.exception("cycle error: %s", exc)

    def recap_tick():
        try:
            result = send_daily_recap_if_due(settings, client, store, risk)
            if result.get("sent"):
                console.print(f"[green]Daily recap sent[/] via {result.get('channel')}")
            elif result.get("ok"):
                console.print("[green]Daily recap sent[/]")
        except Exception as exc:  # noqa: BLE001
            logging.exception("recap error: %s", exc)

    # Run immediately, then on interval
    tick()
    scheduler = BlockingScheduler()
    scheduler.add_job(tick, "interval", seconds=settings.loop_interval_seconds, id="trade_cycle")
    # Mon–Fri 4:05 PM ET + backup every 15 min until 8 PM if the first run missed
    scheduler.add_job(
        recap_tick,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone="America/New_York"),
        id="daily_recap",
    )
    scheduler.add_job(
        recap_tick,
        CronTrigger(day_of_week="mon-fri", hour="16-20", minute="5,20,35,50", timezone="America/New_York"),
        id="daily_recap_backup",
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("[yellow]Shutting down…[/]")
        if not settings.dry_run:
            # Leave positions with their bracket stops; cancel only if you prefer flatten:
            pass
    return 0


def cmd_backtest() -> int:
    result = run_backtest()
    console.print(result)
    return 0


def cmd_flatten() -> int:
    settings = get_settings()
    client = AlpacaClient(settings)
    client.close_all_positions()
    console.print("[red]All positions closed.[/]")
    return 0


def cmd_recap() -> int:
    settings = get_settings()
    store = StateStore(settings.data_dir / "bot.db")
    client = AlpacaClient(settings)
    risk = RiskManager(settings, store)
    force = "--send" in sys.argv or "-s" in sys.argv
    if force:
        result = send_daily_recap_if_due(settings, client, store, risk, force=True)
        console.print(result)
        return 0 if result.get("ok") else 1
    recap = build_daily_recap(settings, client, store, risk)
    console.print(recap.to_text())
    if not settings.recap_email_to and not settings.recap_webhook_url and not settings.resend_api_key:
        console.print(
            "\n[yellow]Tip:[/] set RECAP_EMAIL_TO + RESEND_API_KEY (or SMTP_*) to email this daily at close."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        console.print(
            """
[bold]alpaca-bot[/] — autonomous Alpaca day trader

  python -m alpaca_bot status     Account + positions
  python -m alpaca_bot once       Single scan/trade cycle
  python -m alpaca_bot run        Autonomous loop (market hours)
  python -m alpaca_bot backtest   Synthetic strategy smoke backtest
  python -m alpaca_bot flatten    Close all positions now
  python -m alpaca_bot recap      Print today's recap (add --send to email)
"""
        )
        return 0

    cmd = argv[0]
    mapping = {
        "status": cmd_status,
        "once": cmd_once,
        "run": cmd_run,
        "backtest": cmd_backtest,
        "flatten": cmd_flatten,
        "recap": cmd_recap,
    }
    if cmd not in mapping:
        console.print(f"Unknown command: {cmd}")
        return 1
    try:
        return mapping[cmd]()
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
