"""Append-only audit log (`state/audit.jsonl`): one JSON object per line, never rewritten.

Events are domain facts (plan created / approved / applied / rolled back / removed ...) with
enough identifiers to cross-reference plans, transactions and registry digests. There is no
broker; a future backend only needs to re-implement `AuditLog.emit`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_forge.util import now_iso

EVENTS = frozenset(
    {
        "ProjectScanned",
        "PlanCreated",
        "PlanApproved",
        "PlanRevoked",
        "TransactionStarted",
        "TransactionCompleted",
        "TransactionFailed",
        "RollbackCompleted",
        "ValidationCompleted",
        "SourcesSynced",
    }
)


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        if event not in EVENTS:
            raise ValueError(f"unknown audit event {event!r}")
        record = {"event": event, "at": now_iso(), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def read(self, *, limit: int = 200, event: str | None = None) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if event is None or rec.get("event") == event:
                out.append(rec)
        return out[-limit:]
