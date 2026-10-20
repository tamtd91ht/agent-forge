"""Local usage statistics from the audit log. Nothing leaves the machine.

`agent-forge stats` answers "which capabilities get installed, removed and rolled back, in
which projects" from `state/audit.jsonl` alone, so a team can see what its catalog is
actually used for without any telemetry.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_forge.storage.audit import AuditLog


def _parse_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def usage_stats(log: AuditLog, *, since_days: int | None = None) -> dict[str, Any]:
    records = log.read(limit=1_000_000)
    cutoff = datetime.now(UTC) - timedelta(days=since_days) if since_days else None
    if cutoff is not None:
        records = [r for r in records if (at := _parse_at(r.get("at"))) and at >= cutoff]
    events: Counter[str] = Counter(str(r.get("event")) for r in records)
    installs: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    approvers: Counter[str] = Counter()
    tx_capabilities: dict[str, list[str]] = {}
    failed_tx = 0
    for r in records:
        ev = r.get("event")
        target = r.get("target")
        if isinstance(target, str) and ev in ("TransactionCompleted", "RollbackCompleted"):
            targets[target] += 1
        if ev == "TransactionCompleted":
            caps = r.get("capabilities") or []
            if r.get("status") in ("completed", "success", "applied"):
                installs.update(str(c) for c in caps)
            else:
                failed_tx += 1
            tx_id = r.get("transaction_id")
            if isinstance(tx_id, str):
                tx_capabilities[tx_id] = [str(c) for c in caps]
        elif ev == "PlanApproved":
            approvers[str(r.get("approved_by") or "-")] += 1
    rollbacks: Counter[str] = Counter()
    for r in records:
        if r.get("event") == "RollbackCompleted":
            for c in tx_capabilities.get(str(r.get("rollback_of")), []):
                rollbacks[c] += 1
    by_capability = [
        {"capability": cid, "installs": installs[cid], "rollbacks": rollbacks[cid]}
        for cid in sorted(set(installs) | set(rollbacks))
    ]
    by_capability.sort(key=lambda row: (-row["installs"], row["capability"]))
    return {
        "since_days": since_days,
        "records": len(records),
        "events": dict(sorted(events.items())),
        "transactions_failed": failed_tx,
        "projects": len(targets),
        "by_project": [{"target": t, "transactions": n} for t, n in targets.most_common()],
        "by_capability": by_capability,
        "approvers": dict(approvers.most_common()),
    }
