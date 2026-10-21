"""The decision layer (ADR-0007): read, verify and summarise the agent's decision records.

Everything here is read-only with respect to the project. Records are written by the
`/agent-forge-upgrade` skill (the agent's own file, outside the engine's write path) and the
engine only checks them.
"""

from agent_forge.decisions.verify import (
    DECISIONS_DIR,
    VerifyReport,
    diff_records,
    evidence_drift,
    latest_record_path,
    load_record,
    verify_record,
)

__all__ = [
    "DECISIONS_DIR",
    "VerifyReport",
    "diff_records",
    "evidence_drift",
    "latest_record_path",
    "load_record",
    "verify_record",
]
