"""SQLite index of plans and transactions.

The JSON documents in state/plans and state/transactions are the source of truth (reviewable,
hashable). The database is an index for fast listing and is rebuilt from the documents on
demand (`reindex`). Losing it loses nothing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    digest TEXT NOT NULL,
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_target ON plans(target);
CREATE INDEX IF NOT EXISTS idx_tx_target ON transactions(target);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- plans ---------------------------------------------------------------------------

    def upsert_plan(self, **row: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO plans(plan_id, kind, target, status, created_at, digest, path) "
                "VALUES(:plan_id, :kind, :target, :status, :created_at, :digest, :path) "
                "ON CONFLICT(plan_id) DO UPDATE SET status=excluded.status, digest=excluded.digest, "
                "path=excluded.path",
                row,
            )

    def list_plans(self, target: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if target:
                cur = conn.execute(
                    "SELECT * FROM plans WHERE target=? ORDER BY created_at DESC", (target,)
                )
            else:
                cur = conn.execute("SELECT * FROM plans ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    # ---- transactions --------------------------------------------------------------------

    def upsert_transaction(self, **row: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO transactions(transaction_id, plan_id, target, status, started_at, "
                "finished_at, path) VALUES(:transaction_id, :plan_id, :target, :status, "
                ":started_at, :finished_at, :path) "
                "ON CONFLICT(transaction_id) DO UPDATE SET status=excluded.status, "
                "finished_at=excluded.finished_at, path=excluded.path",
                row,
            )

    def list_transactions(self, target: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if target:
                cur = conn.execute(
                    "SELECT * FROM transactions WHERE target=? ORDER BY started_at DESC LIMIT ?",
                    (target, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM transactions ORDER BY started_at DESC LIMIT ?", (limit,)
                )
            return [dict(r) for r in cur.fetchall()]

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM plans")
            conn.execute("DELETE FROM transactions")
