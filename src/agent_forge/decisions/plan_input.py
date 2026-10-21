"""Turn a verified decision record into plan input (`forge --decisions`, ADR-0007).

Effective SKIP / REMOVE become exclusions and effective ADD become requests; flags the user
passed win per id. An effective ASK that no flag answers is `unresolved`: a dry run shows it,
a real run refuses to proceed (the CLI raises). The record's digest is what the plan binds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent_forge.decisions.usage import usage_summary
from agent_forge.decisions.verify import VerifyReport, load_record, verify_record
from agent_forge.models.capability import Platform
from agent_forge.models.decision import Verdict
from agent_forge.models.project import ProjectProfile
from agent_forge.policy.engine import PolicySet
from agent_forge.registry.loader import Registry


@dataclass
class DecisionInput:
    report: VerifyReport
    requested: frozenset[str]
    excluded: frozenset[str]
    unresolved: list[str] = field(default_factory=list)
    removals: list[str] = field(default_factory=list)
    digest: str = ""
    notes: list[str] = field(default_factory=list)


def decisions_for_plan(
    record_path: Path,
    reg: Registry,
    profile: ProjectProfile,
    *,
    policy: PolicySet | None,
    platform: Platform,
    requested: set[str],
    excluded: set[str],
) -> DecisionInput:
    record = load_record(record_path)
    report = verify_record(
        record,
        reg,
        profile,
        policy=policy,
        platform=platform,
        usage=usage_summary(profile),
        path=record_path,
    )
    requested, excluded = set(requested), set(excluded)
    for cid in report.effective(Verdict.SKIP) + report.effective(Verdict.REMOVE):
        if cid not in requested:
            excluded.add(cid)
    for cid in report.effective(Verdict.ADD):
        if cid not in excluded:
            requested.add(cid)
    unresolved = [
        cid for cid in report.effective(Verdict.ASK) if cid not in requested and cid not in excluded
    ]
    removals = report.effective(Verdict.REMOVE)
    digest = record.digest()
    notes = [
        f"decisions: {record_path} digest {digest[:12]} "
        f"({len(report.downgraded)} downgraded to ASK)"
    ]
    if removals:
        notes.append(
            "REMOVE verdicts are not applied by forge; run `agent-forge remove PATH "
            + " ".join(removals)
            + "`"
        )
    if unresolved:
        notes.append("ASK, not resolved: " + ", ".join(unresolved))
    return DecisionInput(
        report=report,
        requested=frozenset(requested),
        excluded=frozenset(excluded),
        unresolved=unresolved,
        removals=removals,
        digest=digest,
        notes=notes,
    )
