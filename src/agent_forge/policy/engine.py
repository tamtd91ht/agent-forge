"""Policy engine.

Policies are small YAML documents layered in a fixed order; a later layer may only *tighten*
an earlier one (a project can deny what the workspace allows, never the reverse):

    registry/policies/default.yaml   shipped defaults (part of the registry digest)
    <workspace>/policy.yaml          workspace / organisation overrides (optional)
    <target>/.agent-forge/policy.yaml project overrides (optional, validated, untrusted)

Each capability gets one decision before scoring:

    ALLOW            -> proceeds to the usual rules and ranking
    REQUIRE_REQUEST  -> proceeds only when explicitly requested (--request / --want tag)
    DENY             -> rejected with category `policy_denied`

Scoring never overrides a policy decision. Approval *classes* (shared_file, hook, mcp) are
not policy outputs: they are structural and always enforced by `approve`/`apply`; policy can
only switch a whole class off (`classes: {hook: deny}`).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_forge.errors import WorkspaceError
from agent_forge.models.capability import Capability, Platform, RiskLevel

Verdict = Literal["allow", "deny", "require_request"]
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
_VERDICT_ORDER: dict[str, int] = {"allow": 0, "require_request": 1, "deny": 2}


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_REQUEST = "require_request"
    DENY = "deny"


class CapabilityRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deny: list[str] = Field(default_factory=list, description="id globs, e.g. 'rea.*'")
    require_request: list[str] = Field(default_factory=list, description="id globs")
    allow_only: list[str] = Field(
        default_factory=list, description="if non-empty, everything not matching is denied"
    )
    deny_tags: list[str] = Field(default_factory=list)


class GrantRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    process_execute: Verdict = "require_request"
    network_access: Verdict = "require_request"
    secrets_read: Verdict = "deny"


class ClassRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shared_file: Literal["allow", "deny"] = "allow"
    hook: Literal["allow", "deny"] = "allow"
    mcp: Literal["allow", "deny"] = "allow"


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    name: str = "unnamed"
    max_risk: RiskLevel = Field(
        default=RiskLevel.HIGH, description="capabilities above this are denied"
    )
    require_request_from_risk: RiskLevel = Field(
        default=RiskLevel.HIGH, description="capabilities at/above this need an explicit request"
    )
    capabilities: CapabilityRules = Field(default_factory=CapabilityRules)
    grants: GrantRules = Field(default_factory=GrantRules)
    classes: ClassRules = Field(default_factory=ClassRules)
    platforms: list[Platform] = Field(
        default_factory=list, description="if non-empty, other platforms are denied"
    )
    require_signoff: bool = Field(
        default=False, description="deny capabilities whose review has no signed_off_by"
    )
    max_context_chars: int | None = Field(
        default=None,
        ge=0,
        description="capabilities adding more always-loaded context than this need a request",
    )
    max_total_context_chars: int | None = Field(
        default=None,
        ge=0,
        description="budget for the always-loaded context a whole plan adds; exceeding it is "
        "reported as a decision the approver must take (the plan is not blocked)",
    )


@dataclass
class PolicySet:
    layers: list[tuple[str, Policy]] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.layers]

    @property
    def digest(self) -> str:
        """Digest of the effective layers; plans bind to it so a policy change re-plans."""
        payload = json.dumps(describe(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def evaluate(
        self, cap: Capability, platform: Platform, context_chars: int | None = None
    ) -> tuple[Decision, list[str]]:
        """Combine layers: the strictest verdict wins. Returns (decision, reasons).

        `context_chars` is the capability's always-loaded context cost on `platform`
        (registry.context_load); budget rules are skipped when it is not supplied.
        """
        worst = "allow"
        reasons: list[str] = []
        for name, pol in self.layers:
            verdict, why = _evaluate_one(pol, cap, platform, context_chars)
            if _VERDICT_ORDER[verdict] > _VERDICT_ORDER[worst]:
                worst = verdict
            reasons.extend(f"[{name}] {w}" for w in why)
        return Decision(worst), reasons

    @property
    def total_context_budget(self) -> int | None:
        """Strictest `max_total_context_chars` across layers (None = no budget)."""
        values = [
            p.max_total_context_chars
            for _, p in self.layers
            if p.max_total_context_chars is not None
        ]
        return min(values) if values else None

    def class_allowed(self, klass: str) -> bool:
        return all(
            getattr(pol.classes, klass, "allow") == "allow"
            for _, pol in self.layers
            if klass in ("shared_file", "hook", "mcp")
        )


def _evaluate_one(
    pol: Policy, cap: Capability, platform: Platform, context_chars: int | None = None
) -> tuple[str, list[str]]:
    verdict = "allow"
    reasons: list[str] = []

    def tighten(v: str, why: str) -> None:
        nonlocal verdict
        if _VERDICT_ORDER[v] > _VERDICT_ORDER[verdict]:
            verdict = v
        reasons.append(why)

    if pol.platforms and platform not in pol.platforms:
        tighten("deny", f"platform {platform.value} not allowed by policy")
    if _RISK_ORDER[cap.risk] > _RISK_ORDER[pol.max_risk]:
        tighten("deny", f"risk {cap.risk.value} exceeds max_risk {pol.max_risk.value}")
    elif _RISK_ORDER[cap.risk] >= _RISK_ORDER[pol.require_request_from_risk]:
        tighten("require_request", f"risk {cap.risk.value} requires an explicit request")
    if pol.require_signoff and not cap.review.signed_off_by:
        tighten("deny", "curation has no human sign-off (require_signoff)")
    if (
        pol.max_context_chars is not None
        and context_chars is not None
        and context_chars > pol.max_context_chars
    ):
        tighten(
            "require_request",
            f"adds {context_chars} always-loaded context chars "
            f"(max_context_chars {pol.max_context_chars})",
        )
    rules = pol.capabilities
    if rules.allow_only and not any(fnmatch.fnmatchcase(cap.id, g) for g in rules.allow_only):
        tighten("deny", "not in capabilities.allow_only")
    for g in rules.deny:
        if fnmatch.fnmatchcase(cap.id, g):
            tighten("deny", f"capability id matches deny pattern {g!r}")
    for g in rules.require_request:
        if fnmatch.fnmatchcase(cap.id, g):
            tighten("require_request", f"capability id matches require_request pattern {g!r}")
    tags = set(cap.applicability.tags)
    for t in rules.deny_tags:
        if t in tags:
            tighten("deny", f"tag {t!r} denied by policy")
    grants = cap.effective_grants
    if grants.process_execute and pol.grants.process_execute != "allow":
        tighten(pol.grants.process_execute, "executes processes (grants.process_execute)")
    if grants.network_access and pol.grants.network_access != "allow":
        tighten(pol.grants.network_access, "uses the network (grants.network_access)")
    if grants.secrets_read and pol.grants.secrets_read != "allow":
        tighten(pol.grants.secrets_read, "may read secrets (grants.secrets_read)")
    klass = "hook" if cap.kind.value == "hook" else "mcp" if cap.kind.value == "mcp" else None
    if klass and getattr(pol.classes, klass) == "deny":
        tighten("deny", f"{klass} capabilities are switched off by policy")
    if cap.install_strategy.value == "section_merge" and pol.classes.shared_file == "deny":
        tighten("deny", "shared-file sections are switched off by policy")
    return verdict, reasons


def _load_file(path: Path, *, trusted: bool) -> Policy:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise WorkspaceError(f"{path}: cannot read policy: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkspaceError(f"{path}: policy must be a mapping")
    try:
        pol = Policy.model_validate(raw)
    except ValidationError as exc:
        raise WorkspaceError(f"{path}: invalid policy: {exc.errors()[0]['msg']}") from exc
    if not trusted and pol.name == "unnamed":
        pol.name = "project"
    return pol


def load_policies(
    registry_dir: Path,
    workspace_root: Path | None = None,
    target_root: Path | None = None,
) -> PolicySet:
    """Load default -> workspace -> project policies. Missing files are skipped."""
    ps = PolicySet()
    default = registry_dir / "policies" / "default.yaml"
    if default.is_file():
        ps.layers.append(("default", _load_file(default, trusted=True)))
    else:
        ps.layers.append(("default", Policy(name="builtin-default")))
    if workspace_root is not None:
        wp = workspace_root / "policy.yaml"
        if wp.is_file():
            ps.layers.append(("workspace", _load_file(wp, trusted=True)))
    if target_root is not None:
        tp = target_root / ".agent-forge" / "policy.yaml"
        if tp.is_symlink():
            raise WorkspaceError(f"{tp}: project policy must be a regular file, not a link")
        if tp.is_file():
            # Project policies are untrusted input: they can only tighten, which the
            # strictest-wins combination guarantees. A broken file fails closed: ignoring it
            # would silently drop the restrictions it was written to add.
            try:
                ps.layers.append(("project", _load_file(tp, trusted=False)))
            except WorkspaceError as exc:
                raise WorkspaceError(
                    exc.message,
                    hint="Fix or remove .agent-forge/policy.yaml; nothing is planned while it is invalid.",
                ) from exc
    return ps


def describe(ps: PolicySet) -> list[dict[str, Any]]:
    return [{"layer": n, **p.model_dump(mode="json")} for n, p in ps.layers]
