from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from alpaca_bot.backtest import run_backtest
from alpaca_bot.client import AlpacaClient
from alpaca_bot.config import Settings, get_settings
from alpaca_bot.loop import TradingLoop
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
    settings = get_settings()
    loop = build_loop(settings)
    console.print(
        f"[bold green]Starting autonomous loop[/] every {settings.loop_interval_seconds}s "
        f"(paper={settings.alpaca_paper}, profile={settings.risk_profile.value})"
    )

    def tick():
        try:
            summary = loop.run_once()
            console.print(summary)
        except Exception as exc:  # noqa: BLE001
            logging.exception("cycle error: %s", exc)

    # Run immediately, then on interval
    tick()
    scheduler = BlockingScheduler()
    scheduler.add_job(tick, "interval", seconds=settings.loop_interval_seconds, id="trade_cycle")
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
