from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

from alpaca.trading.enums import OrderSide

from alpaca_bot.client import AlpacaClient
from alpaca_bot.config import Settings
from alpaca_bot.indicators import enrich
from alpaca_bot.risk import RiskManager, TradingMode
from alpaca_bot.state import StateStore, TradeRecord
from alpaca_bot.strategies import best_signal, load_strategies, sell_signals
from alpaca_bot.strategies.base import Side, Signal

log = logging.getLogger(__name__)


class TradingLoop:
    """Autonomous scan → signal → size → trade cycle (tweet-style agent loop)."""

    def __init__(
        self,
        settings: Settings,
        client: AlpacaClient,
        risk: RiskManager,
        store: StateStore,
    ):
        self.settings = settings
        self.client = client
        self.risk = risk
        self.store = store
        self.strategies = load_strategies(settings.strategy_list())

    def run_once(self) -> dict:
        summary = {
            "scanned": 0,
            "signals": 0,
            "orders": 0,
            "exits": 0,
            "mode": self.risk.mode.value,
            "skipped": [],
        }

        if not self.client.is_market_open():
            summary["skipped"].append("market closed")
            self.store.log_event("skip", {"reason": "market_closed"})
            return summary

        account = self.client.account_snapshot()
        mode = self.risk.sync_mode(account)
        summary["mode"] = mode.value
        summary["equity"] = account.equity
        summary["day_pl_pct"] = account.day_pl_pct

        minutes = self.client.minutes_to_close()
        if minutes is not None and minutes <= self.settings.flatten_minutes_before_close:
            log.warning("Flattening all positions — %.1f min to close", minutes)
            if not self.settings.dry_run:
                self.client.close_all_positions()
            summary["exits"] = account.open_positions
            self.store.log_event("eod_flatten", {"minutes_to_close": minutes})
            return summary

        if mode == TradingMode.HALTED:
            summary["skipped"].append("halted")
            # Still manage exits if somehow open
            summary["exits"] += self._manage_exits()
            return summary

        positions = self.client.positions_by_symbol()
        summary["exits"] += self._manage_exits(positions)

        # Refresh after exits
        positions = self.client.positions_by_symbol()
        account = self.client.account_snapshot()
        self.risk.sync_mode(account)

        symbols = self.settings.watchlist_symbols()
        candidates: List[Signal] = []

        for symbol in symbols:
            summary["scanned"] += 1
            try:
                df = self.client.get_bars(symbol)
                if df.empty or len(df) < 30:
                    continue
                df = enrich(df)
                signals = [s.evaluate(symbol, df) for s in self.strategies]
                for sell in sell_signals(signals):
                    if symbol in positions:
                        self._exit(symbol, sell.reason)
                        summary["exits"] += 1
                best = best_signal(signals, self.risk.min_score())
                if best:
                    candidates.append(best)
                    summary["signals"] += 1
            except Exception as exc:  # noqa: BLE001 — keep loop alive
                log.exception("scan failed for %s: %s", symbol, exc)
                self.store.log_event("scan_error", {"symbol": symbol, "error": str(exc)})

        # Prefer highest-conviction edges (tweet: only trade when disagreement is wide)
        candidates.sort(key=lambda s: s.score, reverse=True)
        max_new = max(1, int(self.settings.max_positions or 5) - len(positions))
        if self.risk.mode == TradingMode.SURVIVAL:
            max_new = min(max_new, 1)

        for signal in candidates[:max_new]:
            if signal.symbol in positions:
                continue
            try:
                df = self.client.get_bars(signal.symbol, limit=5)
                price = float(df["close"].iloc[-1])
            except Exception:  # noqa: BLE001
                continue

            decision = self.risk.approve(
                signal, account, price, already_held=signal.symbol in positions
            )
            self.store.log_event(
                "risk",
                {
                    "symbol": signal.symbol,
                    "approved": decision.approved,
                    "qty": decision.qty,
                    "reason": decision.reason,
                    "score": signal.score,
                    "strategy": signal.strategy,
                    "mode": decision.mode.value,
                },
            )
            if not decision.approved:
                continue

            order_id = self._enter(signal, decision.qty, price)
            if order_id is not None:
                summary["orders"] += 1
                account = self.client.account_snapshot()
                positions = self.client.positions_by_symbol()

        self.store.log_event("cycle", summary)
        return summary

    def _enter(self, signal: Signal, qty: float, price: float) -> Optional[str]:
        atr = signal.atr or price * 0.01
        stop = signal.stop_price or (price - self.settings.stop_atr_mult * atr)
        tp = signal.take_profit or (price + self.settings.take_profit_r * (price - stop))

        log.info(
            "ENTER %s qty=%.3f score=%.2f strategy=%s mode=%s — %s",
            signal.symbol,
            qty,
            signal.score,
            signal.strategy,
            self.risk.mode.value,
            signal.reason,
        )

        order_id = "dry-run"
        if not self.settings.dry_run:
            order = self.client.submit_bracket_buy(signal.symbol, qty, stop, tp)
            order_id = str(order.id)

        self.store.record_trade(
            TradeRecord(
                symbol=signal.symbol,
                side="buy",
                qty=qty,
                strategy=signal.strategy,
                score=signal.score,
                reason=signal.reason,
                order_id=order_id,
                mode=self.risk.mode.value,
            )
        )
        # Potential day trade if we later sell same day — counted on exit
        return order_id

    def _exit(self, symbol: str, reason: str) -> None:
        log.info("EXIT %s — %s", symbol, reason)
        if not self.settings.dry_run:
            try:
                self.client.close_position(symbol)
            except Exception as exc:  # noqa: BLE001
                log.warning("close %s failed: %s", symbol, exc)
                return
        self.store.record_day_trade(symbol, date.today().isoformat())
        self.store.log_event("exit", {"symbol": symbol, "reason": reason})

    def _manage_exits(self, positions=None) -> int:
        """Time-stop and survival flatten for non-intraday holds."""
        positions = positions if positions is not None else self.client.positions_by_symbol()
        exits = 0
        if self.risk.mode == TradingMode.SURVIVAL:
            # Tweet: dump multi-day / risky holds; keep only same-session names
            for symbol, pos in list(positions.items()):
                # If unrealized is deeply red in survival, cut
                try:
                    uplpc = float(getattr(pos, "unrealized_plpc", 0) or 0)
                except (TypeError, ValueError):
                    uplpc = 0.0
                if uplpc < -0.01:
                    self._exit(symbol, "survival cut loser")
                    exits += 1
        return exits
