"""What `agent-forge check` enforces about decision records (ADR-0007, phase 3 of the fix list).

Two things must hold in CI once a project uses `/agent-forge-upgrade`:

1. Every SKIP / REMOVE in the latest decision record still verifies against the project as it
   is now (the cited file and quote exist, the catalog numbers match, policy agrees). A
   decision whose basis disappeared is a failure: the capability is absent for a reason that
   is no longer true, and the skill should run again.
2. Every plan that `forge --decisions` applied was built from a record that still exists in
   the project unchanged (`Plan.decisions_digest` is the digest of some committed record).
   A record edited or deleted after the fact breaks the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_forge.decisions.usage import usage_summary
from agent_forge.decisions.verify import (
    DECISIONS_DIR,
    latest_record_path,
    load_record,
    verify_record,
)
from agent_forge.errors import PlanError
from agent_forge.models.capability import Platform
from agent_forge.models.decision import Verdict
from agent_forge.models.project import ProjectProfile
from agent_forge.policy.engine import PolicySet
from agent_forge.registry.loader import Registry

RECENT_TRANSACTIONS = 20


@dataclass
class DecisionGate:
    record: str | None = None
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    downgraded: list[str] = field(default_factory=list)
    plans_checked: int = 0
    plans_unbound: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record,
            "downgraded": self.downgraded,
            "plans_checked": self.plans_checked,
            "plans_unbound": self.plans_unbound,
        }


def _record_digests(root: Path) -> set[str]:
    out: set[str] = set()
    directory = root / DECISIONS_DIR
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("*.json")):
        if p.is_symlink() or not p.is_file():
            continue
        try:
            out.add(load_record(p).digest())
        except PlanError:
            continue
    return out


def decision_gate(
    reg: Registry,
    profile: ProjectProfile,
    store: Any,
    *,
    policy: PolicySet | None,
    platform: Platform | None = None,
) -> DecisionGate:
    root = Path(profile.canonical_path)
    gate = DecisionGate()
    platform = platform or (
        profile.platforms[0].platform if profile.platforms else Platform.CLAUDE_CODE
    )

    # 1. the latest record still verifies
    record_file = latest_record_path(root)
    if record_file is not None:
        gate.record = record_file.name
        try:
            record = load_record(record_file)
        except PlanError as exc:
            gate.failures.append(f"decision record {record_file.name}: {exc.message}")
            record = None
        if record is not None:
            rep = verify_record(
                record,
                reg,
                profile,
                policy=policy,
                platform=platform,
                usage=usage_summary(profile),
                path=record_file,
            )
            for item in rep.items:
                cid = item.decision.capability_id
                errors = [f.message for f in item.findings if f.level == "error"]
                if item.downgraded and item.decision.verdict in (Verdict.SKIP, Verdict.REMOVE):
                    gate.downgraded.append(cid)
                    gate.failures.append(
                        f"decision: {cid} recorded {item.decision.verdict.value} but it no longer "
                        f"verifies ({'; '.join(errors)}); run /agent-forge-upgrade again"
                    )
                elif errors:
                    gate.warnings.append(
                        f"decision: {cid} {item.decision.verdict.value}: {'; '.join(errors)}"
                    )

    # 2. applied plans are bound to a record that still exists unchanged
    digests = _record_digests(root)
    for tx in store.list_transactions(profile.canonical_path, limit=RECENT_TRANSACTIONS):
        plan_id = tx.get("plan_id")
        if not isinstance(plan_id, str):
            continue
        try:
            plan = store.load_plan(plan_id)
        except PlanError:
            continue
        if plan.decisions_digest is None:
            continue
        gate.plans_checked += 1
        if plan.decisions_digest not in digests:
            gate.plans_unbound.append(plan_id)
            gate.failures.append(
                f"decision: plan {plan_id} was built from a decision record (digest "
                f"{plan.decisions_digest[:12]}) that is missing from {DECISIONS_DIR}/ or was "
                "edited afterwards; restore it from git or re-run /agent-forge-upgrade"
            )
    return gate
