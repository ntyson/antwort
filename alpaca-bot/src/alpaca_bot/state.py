from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TradeRecord:
    symbol: str
    side: str
    qty: float
    strategy: str
    score: float
    reason: str
    order_id: str = ""
    mode: str = "normal"
    created_at: str = ""


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS day_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    traded_on TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    score REAL NOT NULL,
                    reason TEXT NOT NULL,
                    order_id TEXT,
                    mode TEXT NOT NULL
                );
                """
            )

    def log_event(self, kind: str, payload: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (created_at, kind, payload) VALUES (?, ?, ?)",
                (_utc_now(), kind, json.dumps(payload)),
            )

    def record_trade(self, trade: TradeRecord) -> None:
        created = trade.created_at or _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO trades
                (created_at, symbol, side, qty, strategy, score, reason, order_id, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created,
                    trade.symbol,
                    trade.side,
                    trade.qty,
                    trade.strategy,
                    trade.score,
                    trade.reason,
                    trade.order_id,
                    trade.mode,
                ),
            )

    def record_day_trade(self, symbol: str, day: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO day_trades (symbol, traded_on) VALUES (?, ?)",
                (symbol, day),
            )

    def day_trade_count(self, since_day: str) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM day_trades WHERE traded_on >= ?",
                (since_day,),
            ).fetchone()
            return int(row["c"])

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO meta (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def recent_events(self, limit: int = 50) -> List[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT created_at, kind, payload FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "created_at": r["created_at"],
                    "kind": r["kind"],
                    "payload": json.loads(r["payload"]),
                }
                for r in rows
            ]

    def trades_for_date(self, day: str) -> List[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT symbol, side, qty, strategy, score, reason, order_id, mode, created_at
                FROM trades WHERE created_at LIKE ?
                ORDER BY id
                """,
                (f"{day}%",),
            ).fetchall()
            return [dict(r) for r in rows]

    def exits_for_date(self, day: str) -> List[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM events
                WHERE kind = 'exit' AND created_at LIKE ?
                ORDER BY id
                """,
                (f"{day}%",),
            ).fetchall()
            out = []
            for r in rows:
                payload = json.loads(r["payload"])
                if isinstance(payload, dict):
                    out.append(payload)
            return out

    def cycle_stats_for_date(self, day: str) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM events
                WHERE kind = 'cycle' AND created_at LIKE ?
                """,
                (f"{day}%",),
            ).fetchall()
            cycles = len(rows)
            orders = 0
            for r in rows:
                payload = json.loads(r["payload"])
                orders += int(payload.get("orders", 0) or 0)
            return {"cycles": cycles, "orders": orders}
