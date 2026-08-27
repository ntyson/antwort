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
        positions = self.client.positions_by_symbol()
        mode = self.risk.sync_mode(account, positions)
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
            summary["exits"] += self._manage_exits(positions)
            return summary

        summary["exits"] += self._manage_exits(positions)

        # Refresh after exits
        positions = self.client.positions_by_symbol()
        account = self.client.account_snapshot()
        self.risk.sync_mode(account, positions)

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

        # Prefer highest-conviction edges on names we do not already hold
        candidates = [s for s in candidates if s.symbol not in positions]
        candidates.sort(key=lambda s: s.score, reverse=True)
        slots = max(0, int(self.settings.max_positions or 5) - len(positions))
        max_new = min(slots, int(self.settings.max_new_per_cycle or 5))
        if self.risk.mode == TradingMode.SURVIVAL:
            max_new = min(max_new, 1)
        max_new = max(max_new, 0)

        for signal in candidates[:max_new]:
            try:
                df = self.client.get_bars(signal.symbol, limit=5)
                price = float(df["close"].iloc[-1])
            except Exception:  # noqa: BLE001
                continue

            decision = self.risk.approve(
                signal, account, price, already_held=False
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

    def _cut_symbols_today(self) -> set[str]:
        return {
            s.strip().upper()
            for s in (self.store.get_meta("cut_symbols_today") or "").split(",")
            if s.strip()
        }

    def _record_cut(self, symbol: str) -> None:
        cuts = self._cut_symbols_today()
        cuts.add(symbol.upper())
        self.store.set_meta("cut_symbols_today", ",".join(sorted(cuts)))

    def _manage_exits(self, positions=None) -> int:
        """Cut losers past the threshold; optional session cut list."""
        positions = positions if positions is not None else self.client.positions_by_symbol()
        cut_pct = self.risk.position_cut_threshold()  # percent, e.g. -3.5
        cut_symbols = self._cut_symbols_today() if self.settings.block_reentry_after_cut else set()
        exits = 0
        for symbol, pos in list(positions.items()):
            if symbol.upper() in cut_symbols:
                self._exit(symbol, "session cut cooldown")
                exits += 1
                continue
            try:
                uplpc = float(getattr(pos, "unrealized_plpc", 0) or 0) * 100
            except (TypeError, ValueError):
                uplpc = 0.0
            if uplpc <= cut_pct:
                if self.settings.block_reentry_after_cut:
                    self._record_cut(symbol)
                self._exit(symbol, f"cut loser ({uplpc:.2f}%)")
                exits += 1
        return exits
