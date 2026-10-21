"""Verify a decision record against the project, the catalog and the policy.

The agent's rubric says what evidence each ground needs; this module checks what a program
can check and says so for the rest. A SKIP or REMOVE whose grounds do not survive the check
is reported with the effective verdict ASK ("the agent wanted to leave X out but could not
prove why"); an ADD of a capability the policy denies becomes SKIP; a SKIP of a required one
becomes ADD. Nothing is rewritten: the report carries both the recorded and the effective
verdict, and `forge --decisions` acts on the effective one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_forge.apply.filesystem_safety import resolve_in_root, validate_relative_path
from agent_forge.errors import PlanError, SafetyViolation
from agent_forge.matching.rules import MatchContext, applies_to
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.models.decision import Citation, Decision, DecisionRecord, Ground, Verdict
from agent_forge.models.project import ProjectProfile
from agent_forge.policy.engine import Decision as PolicyDecision
from agent_forge.policy.engine import PolicySet
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import Registry
from agent_forge.util import normalize_newlines

DECISIONS_DIR = ".agent-forge/decisions"
MAX_CITED_FILE_BYTES = 2_000_000
_WS = re.compile(r"\s+")


# ---- loading -------------------------------------------------------------------------------


def latest_record_path(root: Path) -> Path | None:
    """The newest `.agent-forge/decisions/*.json` (by assessed_at, then file name)."""
    directory = root / DECISIONS_DIR
    if not directory.is_dir():
        return None
    best: tuple[str, str, Path] | None = None
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        stamp = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stamp = str(data.get("assessed_at") or "") if isinstance(data, dict) else ""
        except (OSError, ValueError):
            pass
        key = (stamp, path.name, path)
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def record_path(root: Path, plan_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", plan_id):
        raise PlanError(f"invalid plan id {plan_id!r}")
    return root / DECISIONS_DIR / f"{plan_id}.json"


def load_record(path: Path) -> DecisionRecord:
    if path.is_symlink():
        raise PlanError(f"{path}: decision record must be a regular file, not a link")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"{path}: cannot read decision record: {exc}") from exc
    except ValueError as exc:
        raise PlanError(f"{path}: decision record is not valid JSON: {exc}") from exc
    try:
        return DecisionRecord.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise PlanError(
            f"{path}: invalid decision record at {where or '<root>'}: {first['msg']}",
            hint="The schema is registry/schema/decisions.schema.json.",
        ) from exc


# ---- citations -----------------------------------------------------------------------------


def _norm(text: str) -> str:
    return _WS.sub(" ", normalize_newlines(text)).strip().lower()


def check_citation(root: Path, cit: Citation, *, require_quote: bool) -> str | None:
    """None when the citation holds; otherwise what is wrong with it."""
    try:
        validate_relative_path(cit.path)
        target = resolve_in_root(root, cit.path)
    except SafetyViolation as exc:
        return f"{cit.path}: {exc.message}"
    if not target.is_file() or target.is_symlink():
        return f"{cit.path}: file does not exist in the project"
    if cit.quote is None or not cit.quote.strip():
        return (
            f"{cit.path}: no quote (the ground needs one line from the file)"
            if require_quote
            else None
        )
    try:
        size = target.stat().st_size
        if size > MAX_CITED_FILE_BYTES:
            return f"{cit.path}: file too large to verify a quote ({size} bytes)"
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"{cit.path}: cannot read: {exc}"
    if _norm(cit.quote) not in _norm(text):
        return f"{cit.path}: quote not found in the file: {cit.quote[:80]!r}"
    return None


# ---- verification --------------------------------------------------------------------------


@dataclass
class Finding:
    capability_id: str
    level: str  # error | warning | info
    check: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class VerifiedDecision:
    decision: Decision
    effective: Verdict
    findings: list[Finding] = field(default_factory=list)

    def err(self, check: str, message: str) -> None:
        self.findings.append(Finding(self.decision.capability_id, "error", check, message))

    def warn(self, check: str, message: str) -> None:
        self.findings.append(Finding(self.decision.capability_id, "warning", check, message))

    @property
    def verified(self) -> bool:
        return not any(f.level == "error" for f in self.findings)

    @property
    def downgraded(self) -> bool:
        return self.effective != self.decision.verdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.decision.capability_id,
            "verdict": self.decision.verdict.value,
            "effective_verdict": self.effective.value,
            "grounds": [g.value for g in self.decision.grounds],
            "confidence": self.decision.confidence.value,
            "verified": self.verified,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class VerifyReport:
    record: DecisionRecord
    path: str | None
    target: str
    items: list[VerifiedDecision] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def downgraded(self) -> list[VerifiedDecision]:
        return [i for i in self.items if i.downgraded]

    @property
    def errors(self) -> list[Finding]:
        return [f for i in self.items for f in i.findings if f.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def effective(self, verdict: Verdict) -> list[str]:
        return [i.decision.capability_id for i in self.items if i.effective == verdict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "plan_id": self.record.plan_id,
            "target": self.target,
            "digest": self.record.digest(),
            "assessed_by": self.record.assessed_by,
            "assessed_at": self.record.assessed_at,
            "decisions": [i.to_dict() for i in self.items],
            "downgraded": [
                {
                    "capability_id": i.decision.capability_id,
                    "from": i.decision.verdict.value,
                    "to": i.effective.value,
                    "why": [f.message for f in i.findings if f.level == "error"],
                }
                for i in self.downgraded
            ],
            "effective": {v.value: self.effective(v) for v in Verdict},
            "notes": self.notes,
        }


_QUOTED_GROUNDS = {Ground.COVERED, Ground.CONFLICTS, Ground.DUPLICATE_TOOL}


def verify_record(
    record: DecisionRecord,
    reg: Registry,
    profile: ProjectProfile,
    *,
    policy: PolicySet | None,
    platform: Platform,
    usage: dict[str, Any] | None = None,
    path: Path | None = None,
) -> VerifyReport:
    root = Path(profile.canonical_path)
    rep = VerifyReport(
        record=record, path=str(path) if path else None, target=profile.canonical_path
    )
    ctx = MatchContext(platforms=(platform,), policy=policy)
    installed = {m.capability_id: m for m in profile.managed}
    usage_by_id = {row["capability"]: row for row in (usage or {}).get("by_capability", [])}
    seen: set[str] = set()
    for d in record.decisions:
        vd = VerifiedDecision(decision=d, effective=d.verdict)
        rep.items.append(vd)
        cid = d.capability_id
        err, warn = vd.err, vd.warn
        if cid in seen:
            err("duplicate", "assessed twice in one record")
        seen.add(cid)
        lc = reg.items.get(cid)
        if lc is None:
            err("catalog", "not in the catalog")
            vd.effective = Verdict.ASK if d.verdict in (Verdict.SKIP, Verdict.REMOVE) else d.verdict
            continue
        cap = lc.capability

        # ground <-> verdict consistency
        if d.verdict in (Verdict.SKIP, Verdict.REMOVE) and not d.grounds:
            err("grounds", f"{d.verdict.value} without a ground (write one from the rubric or ASK)")
        if d.verdict == Verdict.ADD and d.grounds:
            warn("grounds", "ADD carries grounds to skip; one of the two is wrong")
        if d.verdict == Verdict.ADD and not (d.gap or "").strip():
            warn("gap", "ADD without a named gap")
        if d.verdict in (Verdict.UPGRADE, Verdict.REMOVE) and cid not in installed:
            err("installed", f"{d.verdict.value} of a capability that is not installed")

        # evidence each ground requires
        for g in d.grounds:
            if g in _QUOTED_GROUNDS:
                cits = d.contradicts if g == Ground.CONFLICTS else d.covered_by
                if not cits:
                    err(g.value, f"ground {g.value!r} needs a path and a quote; none given")
                    continue
                problems = [p for c in cits if (p := check_citation(root, c, require_quote=True))]
                for p in problems:
                    err(g.value, p)
            elif g == Ground.SECURITY:
                grants = cap.effective_grants
                risky = (
                    cap.kind in (CapabilityKind.HOOK, CapabilityKind.MCP)
                    or grants.process_execute
                    or grants.network_access
                    or grants.secrets_read
                    or bool(cap.permissions)
                )
                if not risky:
                    err("security", "the manifest declares no permissions, hooks or MCP")
                if not d.risk:
                    warn("security", "name the manifest field in `risk` (permissions, hook, mcp)")
            elif g == Ground.CONTEXT_COST:
                actual = context_chars(lc, platform)
                if d.context_chars is None:
                    err("context_cost", f"context_chars missing (catalog: {actual})")
                elif d.context_chars != actual:
                    err("context_cost", f"context_chars {d.context_chars} != catalog {actual}")
                elif actual == 0:
                    err("context_cost", "capability adds no always-loaded context")
                budget = policy.total_context_budget if policy else None
                if budget is not None and actual <= budget:
                    warn("context_cost", f"within the policy budget ({actual} <= {budget})")
            elif g == Ground.STACK_MISMATCH:
                if applies_to(cap, profile, ctx):
                    err("stack_mismatch", "applicability matches the scanned profile")
            elif g == Ground.EVIDENCE_WORSE:
                if not any(e.verdict == "worse" for e in cap.review.evidence):
                    err("evidence_worse", "the catalog records no `worse` evaluation")
            elif g == Ground.UNUSED:
                if cid not in installed:
                    err("unused", "not installed; `unused` applies to installed capabilities")
                elif usage is None or not usage.get("log_present"):
                    err("unused", "no usage log in the project (forge.hook.usage-log not enabled)")
                else:
                    row = usage_by_id.get(cid)
                    if row is None or not row.get("unused"):
                        n = row["invocations"] if row else 0
                        err(
                            "unused",
                            f"usage log shows {n} invocation(s) in {usage.get('window_days')} days"
                            + ("" if row else "; capability is not a skill or agent")
                            if row
                            else "usage log does not cover this capability (rules are never invoked)",
                        )

        # numbers copied from the catalog
        actual_ctx = context_chars(lc, platform)
        if (
            d.context_chars is not None
            and d.context_chars != actual_ctx
            and Ground.CONTEXT_COST not in d.grounds
        ):
            warn("context_chars", f"recorded {d.context_chars}, catalog {actual_ctx}")
        expected_on = cap.kind in (CapabilityKind.RULE, CapabilityKind.INSTRUCTION)
        if d.always_on is not None and d.always_on != expected_on:
            warn(
                "always_on",
                f"kind {cap.kind.value} is {'always-on' if expected_on else 'on-demand'}",
            )
        cat_evidence = cap.review.evidence[-1].verdict if cap.review.evidence else "not_measured"
        if d.evidence != cat_evidence:
            level = err if d.evidence in ("improved", "worse") else warn
            level("evidence", f"recorded {d.evidence!r}, catalog says {cat_evidence!r}")

        # policy is the user's, not the agent's
        if policy is not None:
            verdict, _why = policy.evaluate(cap, platform, actual_ctx)
            if policy.is_required(cid) and d.verdict in (Verdict.SKIP, Verdict.REMOVE, Verdict.ASK):
                err("policy", "required by policy; it cannot be skipped or removed")
                vd.effective = Verdict.UPGRADE if cid in installed else Verdict.ADD
                continue
            if verdict == PolicyDecision.DENY and d.verdict in (Verdict.ADD, Verdict.UPGRADE):
                err("policy", "denied by policy; it cannot be added")
                vd.effective = Verdict.SKIP
                continue

        # a SKIP / REMOVE that could not be proven is a question for the user
        if d.verdict in (Verdict.SKIP, Verdict.REMOVE) and not vd.verified:
            vd.effective = Verdict.ASK
    if policy is not None:
        missing = [
            cid
            for cid in sorted(reg.items)
            if policy.is_required(cid) and cid not in seen and cid not in installed
        ]
        if missing:
            rep.notes.append("required by policy but not assessed: " + ", ".join(missing))
    return rep


# ---- drift of the evidence -----------------------------------------------------------------


@dataclass
class EvidenceDrift:
    capability_id: str
    verdict: str
    path: str
    state: str  # basis_missing | quote_missing
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def evidence_drift(record: DecisionRecord, root: Path) -> list[EvidenceDrift]:
    """Citations whose file or quoted line no longer exists: the decision should be reviewed."""
    out: list[EvidenceDrift] = []
    for d in record.decisions:
        for cit in d.citations:
            problem = check_citation(root, cit, require_quote=False)
            if problem is None:
                continue
            state = "quote_missing" if "quote not found" in problem else "basis_missing"
            out.append(EvidenceDrift(d.capability_id, d.verdict.value, cit.path, state, problem))
    return out


# ---- diff between two records --------------------------------------------------------------


def diff_records(old: DecisionRecord, new: DecisionRecord) -> list[dict[str, Any]]:
    """Only the decisions that changed, with the old and the new reason."""
    a, b = old.by_id(), new.by_id()
    out: list[dict[str, Any]] = []
    for cid in sorted(set(a) | set(b)):
        x, y = a.get(cid), b.get(cid)
        if x is None:
            out.append({"capability_id": cid, "change": "new", "old": None, "new": _brief(y)})
        elif y is None:
            out.append({"capability_id": cid, "change": "dropped", "old": _brief(x), "new": None})
        elif x.verdict != y.verdict or x.grounds != y.grounds:
            out.append(
                {"capability_id": cid, "change": "changed", "old": _brief(x), "new": _brief(y)}
            )
    return out


def _brief(d: Decision | None) -> dict[str, Any] | None:
    if d is None:
        return None
    return {
        "verdict": d.verdict.value,
        "grounds": [g.value for g in d.grounds],
        "confidence": d.confidence.value,
        "reason": d.reason,
    }


def parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
