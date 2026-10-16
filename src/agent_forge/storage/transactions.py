"""Document store for plans and transactions (JSON on disk + SQLite index)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import ValidationError

from agent_forge.config import WorkspaceConfig
from agent_forge.errors import PlanError
from agent_forge.models.plan import Plan
from agent_forge.models.transaction import Transaction
from agent_forge.storage.audit import AuditLog
from agent_forge.storage.database import Database
from agent_forge.util import read_json, write_json

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def _check_id(value: str, what: str) -> str:
    if not _ID_RE.match(value):
        raise PlanError(f"invalid {what} id: {value!r}")
    return value


class Store:
    def __init__(self, ws: WorkspaceConfig) -> None:
        self.ws = ws
        ws.ensure_state_dirs()
        self.db = Database(ws.database_path)
        self.audit = AuditLog(ws.audit_path)

    # ---- plans ---------------------------------------------------------------------------

    def plan_path(self, plan_id: str) -> Path:
        return self.ws.plans_dir / f"{_check_id(plan_id, 'plan')}.json"

    def save_plan(self, plan: Plan) -> Path:
        path = self.plan_path(plan.plan_id)
        write_json(path, plan.model_dump(mode="json"))
        self.db.upsert_plan(
            plan_id=plan.plan_id,
            kind=plan.kind,
            target=plan.target.canonical_path,
            status=plan.status.value,
            created_at=plan.created_at,
            digest=plan.content_digest(),
            path=str(path),
        )
        return path

    def load_plan(self, plan_id: str) -> Plan:
        path = self.plan_path(plan_id)
        if not path.is_file():
            raise PlanError(
                f"plan not found: {plan_id}", hint="Run `agent-forge plans` to list plans."
            )
        try:
            plan = Plan.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            raise PlanError(f"plan {plan_id} is invalid or corrupted: {exc}") from exc
        if plan.plan_id != plan_id:
            raise PlanError(f"plan file {path.name} claims a different id ({plan.plan_id})")
        return plan

    def list_plans(self, target: str | None = None) -> list[dict]:
        return self.db.list_plans(target)

    # ---- transactions --------------------------------------------------------------------

    def transaction_dir(self, tx_id: str) -> Path:
        return self.ws.transactions_dir / _check_id(tx_id, "transaction")

    def transaction_path(self, tx_id: str) -> Path:
        return self.transaction_dir(tx_id) / "transaction.json"

    def backup_dir(self, tx_id: str) -> Path:
        return self.transaction_dir(tx_id) / "backup"

    def save_transaction(self, tx: Transaction) -> Path:
        tx.seal()
        path = self.transaction_path(tx.transaction_id)
        write_json(path, tx.model_dump(mode="json"))
        self.db.upsert_transaction(
            transaction_id=tx.transaction_id,
            plan_id=tx.plan_id,
            target=tx.target_canonical_path,
            status=tx.status.value,
            started_at=tx.started_at,
            finished_at=tx.finished_at,
            path=str(path),
        )
        return path

    def load_transaction(self, tx_id: str) -> Transaction:
        path = self.transaction_path(tx_id)
        if not path.is_file():
            raise PlanError(f"transaction not found: {tx_id}")
        try:
            tx = Transaction.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            raise PlanError(f"transaction {tx_id} is invalid or corrupted: {exc}") from exc
        if tx.transaction_id != tx_id:
            raise PlanError(f"transaction file claims a different id ({tx.transaction_id})")
        return tx

    def list_transactions(self, target: str | None = None, limit: int = 50) -> list[dict]:
        return self.db.list_transactions(target, limit)

    # ---- maintenance ---------------------------------------------------------------------

    def reindex(self) -> tuple[int, int]:
        """Rebuild the SQLite index from JSON documents. Returns (plans, transactions)."""
        self.db.clear()
        n_plans = n_tx = 0
        for p in sorted(self.ws.plans_dir.glob("*.json")):
            try:
                plan = Plan.model_validate(read_json(p))
            except (ValidationError, ValueError):
                continue
            self.save_plan(plan)
            n_plans += 1
        for d in (
            sorted(self.ws.transactions_dir.iterdir()) if self.ws.transactions_dir.exists() else []
        ):
            f = d / "transaction.json"
            if not f.is_file():
                continue
            try:
                tx = Transaction.model_validate(read_json(f))
            except (ValidationError, ValueError):
                continue
            self.db.upsert_transaction(
                transaction_id=tx.transaction_id,
                plan_id=tx.plan_id,
                target=tx.target_canonical_path,
                status=tx.status.value,
                started_at=tx.started_at,
                finished_at=tx.finished_at,
                path=str(f),
            )
            n_tx += 1
        return n_plans, n_tx
