"""Hard applicability/compatibility rules, then ranking.

Order of evaluation per (capability, platform):
  1. lifecycle status and install strategy        -> reject (not installable)
  2. platform support                              -> reject (unsupported_platform)
  3. user exclusions                               -> reject (user_excluded)
  4. applicability conditions                      -> reject (not_applicable)
  5. already installed at same version             -> reject (already_installed)
  6. equivalent existing functionality             -> reject (equivalent_exists) unless requested
  7. destination collisions with user-owned files  -> reject (conflict) + user decision
  8. declared conflicts                            -> reject (conflict)
  9. dependencies curated and applicable           -> reject (dependency_missing)
 10. risk / permissions                            -> optional unless requested
 11. a dependant of an optional dependency        -> optional too, unless requested
     (pulled-in dependencies go through policy and steps 10-11 like any candidate)
Only then are survivors scored and ranked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_forge.adapters import get_adapter
from agent_forge.matching.conflicts import (
    declared_conflicts,
    destination_collisions,
    find_equivalents,
)
from agent_forge.matching.scoring import ScoreBreakdown, score
from agent_forge.models.capability import (
    Capability,
    CapabilityStatus,
    InstallStrategy,
    Platform,
    RiskLevel,
)
from agent_forge.models.project import ProjectProfile
from agent_forge.policy.engine import Decision, PolicySet
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import Registry


@dataclass(frozen=True)
class MatchContext:
    platforms: tuple[Platform, ...]
    wanted_tags: frozenset[str] = frozenset()
    excluded_ids: frozenset[str] = frozenset()
    requested_ids: frozenset[str] = frozenset()
    include_optional: bool = False
    # Approval classes the caller is prepared to grant. Capabilities whose operations need a
    # class outside this set are left out of the plan (reported as needs_approval), so that a
    # plan built for `forge` without --hooks never contains hook entries at all.
    allowed_classes: frozenset[str] = frozenset({"standard", "shared_file", "hook", "mcp"})
    # Layered policy (default -> workspace -> project). None = built-in default only.
    policy: PolicySet | None = None


@dataclass
class Candidate:
    capability: Capability
    platform: Platform
    reasons: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    score: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    optional: bool = False
    dependency_of: list[str] = field(default_factory=list)


@dataclass
class Rejection:
    capability: Capability
    platform: Platform | None
    category: str
    reasons: list[str]


@dataclass
class MatchResult:
    platforms: list[Platform]
    recommended: list[Candidate] = field(default_factory=list)
    optional: list[Candidate] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    user_decisions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def choose_platforms(
    profile: ProjectProfile, explicit: tuple[Platform, ...] | None
) -> tuple[list[Platform], list[str]]:
    notes: list[str] = []
    if explicit:
        return list(explicit), notes
    detected = sorted(profile.platform_names, key=lambda p: p.value)
    if detected:
        notes.append(
            "platforms chosen from detected configuration: " + ", ".join(p.value for p in detected)
        )
        return detected, notes
    notes.append("no agent platform detected; defaulting to claude_code (override with --platform)")
    return [Platform.CLAUDE_CODE], notes


def _applicability(
    cap: Capability, profile: ProjectProfile, ctx: MatchContext
) -> tuple[bool, int, list[str]]:
    """Return (applies, specificity, reasons)."""
    app = cap.applicability
    reasons: list[str] = []
    requested = cap.id in ctx.requested_ids or bool(ctx.wanted_tags & set(app.tags))
    if requested:
        reasons.append(
            "explicitly requested"
            if cap.id in ctx.requested_ids
            else "matches requested tag(s): " + ", ".join(sorted(ctx.wanted_tags & set(app.tags)))
        )
    if app.always:
        reasons.append("applies to every project")
        return True, 0, reasons
    dims = 0
    matched = 0
    if app.project_types:
        dims += 1
        hit = profile.project_type_names & set(app.project_types)
        if hit:
            matched += 1
            reasons.append("project type: " + ", ".join(sorted(hit)))
    if app.languages:
        dims += 1
        hit = profile.language_names & set(app.languages)
        if hit:
            matched += 1
            reasons.append("language: " + ", ".join(sorted(hit)))
    if app.frameworks:
        dims += 1
        hit = profile.framework_names & set(app.frameworks)
        if hit:
            matched += 1
            reasons.append("framework: " + ", ".join(sorted(hit)))
    if app.any_of_files:
        dims += 1
        present = [
            f
            for f in app.any_of_files
            if any(a.path == f for a in profile.assets) or _file_present(profile, f)
        ]
        if present:
            matched += 1
            reasons.append("file present: " + ", ".join(present))
    if dims == 0:
        # only tags: applicable only when requested
        return requested, 0, reasons or ["no applicability conditions; only installed on request"]
    applies = matched == dims or requested
    if not applies:
        reasons.append("applicability conditions not met")
    return applies, matched, reasons


def _file_present(profile: ProjectProfile, rel: str) -> bool:
    # ProjectProfile does not carry the whole file index; assets + known manifests are checked
    # by the scanner. Capabilities should prefer languages/frameworks for applicability.
    return any(
        e.path == rel
        for d in (*profile.languages, *profile.frameworks, *profile.project_types)
        for e in d.evidence
    )


def evaluate(reg: Registry, profile: ProjectProfile, ctx: MatchContext) -> MatchResult:
    result = MatchResult(platforms=list(ctx.platforms))
    installed = {m.capability_id: m.version for m in profile.managed}
    selected_ids: set[str] = set()
    candidates: list[Candidate] = []

    for cap in reg.capabilities():
        for platform in ctx.platforms:
            verdict = _evaluate_one(cap, platform, reg, profile, ctx, installed, selected_ids)
            if isinstance(verdict, Rejection):
                result.rejected.append(verdict)
                continue
            candidates.append(verdict)
            selected_ids.add(cap.id)

    # dependencies: pull in automatically when curated + supported; else reject the dependant
    by_id = {c.capability.id: c for c in candidates}
    # A dependency that was itself rejected for a hard reason (policy, platform, runtime,
    # exclusion, conflict ...) must not be pulled back in through the back door.
    _SATISFIABLE = {"not_applicable", "already_installed"}
    for cand in list(candidates):
        for dep in cand.capability.dependencies:
            if dep in by_id:
                by_id[dep].dependency_of.append(cand.capability.id)
                continue
            if dep in installed:
                continue  # satisfied by an existing managed install
            blocked = next(
                (
                    r
                    for r in result.rejected
                    if r.capability.id == dep
                    and r.platform == cand.platform
                    and r.category not in _SATISFIABLE
                ),
                None,
            )
            try:
                dep_cap = reg.get(dep).capability
            except Exception:
                dep_cap = None
            # A not-applicable dependency never reached the policy check in _evaluate_one.
            policy_block = (
                _policy_block(reg, dep_cap, cand.platform, ctx) if dep_cap is not None else None
            )
            if (
                blocked is not None
                or policy_block is not None
                or dep_cap is None
                or not dep_cap.installable
                or cand.platform not in dep_cap.platforms
                or dep in ctx.excluded_ids
            ):
                candidates.remove(cand)
                if blocked is not None:
                    why = f"requires {dep!r}, which was rejected ({blocked.category})"
                elif policy_block is not None:
                    why = f"requires {dep!r}, which was rejected ({policy_block})"
                else:
                    why = f"requires {dep!r}, which is not installable on {cand.platform.value}"
                result.rejected.append(
                    Rejection(cand.capability, cand.platform, "dependency_missing", [why])
                )
                break
            dep_cand = Candidate(
                dep_cap,
                cand.platform,
                reasons=[f"dependency of {cand.capability.id}"],
                dependency_of=[cand.capability.id],
            )
            dep_cand.score = score(
                dep_cap, profile, wanted_tags=set(ctx.wanted_tags), specificity=0
            )
            _apply_optional(dep_cand, _is_requested(dep_cap, ctx), ctx)
            candidates.append(dep_cand)
            by_id[dep] = dep_cand

    _reconcile_optional_dependencies(candidates, ctx)

    # declared conflicts among survivors: keep the higher-scored one, reject the other
    chosen: dict[str, Candidate] = {}
    chosen_ids: set[str] = set(installed)
    for cand in sorted(candidates, key=lambda c: -c.score.total):
        clash = declared_conflicts(cand.capability, chosen_ids)
        clash += [
            c.capability.id
            for c in chosen.values()
            if cand.capability.id in c.capability.conflicts and c.capability.id not in clash
        ]
        if clash:
            result.rejected.append(
                Rejection(
                    cand.capability,
                    cand.platform,
                    "conflict",
                    [f"conflicts with selected {', '.join(clash)}"],
                )
            )
            continue
        chosen[cand.capability.id + "@" + cand.platform.value] = cand
        chosen_ids.add(cand.capability.id)

    for cand in sorted(chosen.values(), key=lambda c: (-c.score.total, c.capability.id)):
        (result.optional if cand.optional else result.recommended).append(cand)
    for rj in result.rejected:
        if rj.category == "conflict" and "user-owned" in " ".join(rj.reasons):
            result.user_decisions.append(f"{rj.capability.id}: {rj.reasons[0]}")
    return result


def _is_requested(cap: Capability, ctx: MatchContext) -> bool:
    return cap.id in ctx.requested_ids or bool(ctx.wanted_tags & set(cap.applicability.tags))


def _policy_block(
    reg: Registry, cap: Capability, platform: Platform, ctx: MatchContext
) -> str | None:
    """Rejection category when policy keeps `cap` out of the plan, else None."""
    if ctx.policy is None:
        return None
    decision, _why = ctx.policy.evaluate(cap, platform, context_chars(reg.get(cap.id), platform))
    if decision == Decision.DENY:
        return "policy_denied"
    if decision == Decision.REQUIRE_REQUEST and not _is_requested(cap, ctx):
        return "policy_requires_request"
    return None


def _apply_optional(cand: Candidate, requested: bool, ctx: MatchContext) -> None:
    """Risk / permissions / low score make a candidate optional unless it was requested."""
    cap = cand.capability
    if requested:
        return
    if cap.risk == RiskLevel.HIGH:
        cand.reasons.append("high risk: listed as optional, install only on request")
    elif cap.permissions:
        cand.reasons.append("requires permissions (" + ", ".join(cap.permissions) + "): optional")
    elif cand.score.total < 3.0:
        cand.reasons.append(f"low score ({cand.score.total:.1f}): optional")
    else:
        return
    cand.optional = True
    if ctx.include_optional:
        cand.optional = False
        cand.reasons.append("promoted by --include-optional")


def _reconcile_optional_dependencies(candidates: list[Candidate], ctx: MatchContext) -> None:
    """Never recommend a capability whose dependency stays optional (i.e. out of the plan).

    A requested dependant promotes its dependency (transitively); otherwise the dependant
    becomes optional too. `forced` only grows, so the loop terminates.
    """
    by_key = {(c.capability.id, c.platform): c for c in candidates}
    forced = {c.capability.id for c in candidates if _is_requested(c.capability, ctx)}
    changed = True
    while changed:
        changed = False
        for cand in candidates:
            if cand.optional:
                continue
            for dep in cand.capability.dependencies:
                dep_cand = by_key.get((dep, cand.platform))
                if dep_cand is None or not dep_cand.optional:
                    continue
                if cand.capability.id in forced:
                    dep_cand.optional = False
                    dep_cand.reasons.append(
                        f"promoted: dependency of requested {cand.capability.id}"
                    )
                    forced.add(dep)
                else:
                    cand.optional = True
                    cand.reasons.append(f"depends on optional {dep}: optional")
                changed = True
                break


def _evaluate_one(
    cap: Capability,
    platform: Platform,
    reg: Registry,
    profile: ProjectProfile,
    ctx: MatchContext,
    installed: dict[str, str],
    selected_ids: set[str],
) -> Candidate | Rejection:
    adapter = get_adapter(platform)
    requested = _is_requested(cap, ctx)

    if cap.status != CapabilityStatus.CURATED:
        return Rejection(
            cap,
            platform,
            "not_curated"
            if cap.install_strategy != InstallStrategy.REFERENCE_ONLY
            else "reference_only",
            [f"status is {cap.status.value}; only curated capabilities are installable"],
        )
    if cap.install_strategy == InstallStrategy.REFERENCE_ONLY:
        return Rejection(
            cap,
            platform,
            "reference_only",
            ["reference-only capability: informs recommendations, never installed"],
        )
    lc = reg.get(cap.id)
    if cap.integrity is not None and cap.integrity.assets_sha256 != lc.assets_digest:
        # content changed after it was reviewed and pinned: never install unreviewed bytes
        return Rejection(
            cap,
            platform,
            "integrity_mismatch",
            [
                "assets differ from the reviewed, pinned digest "
                f"({lc.assets_digest[:12]} != {cap.integrity.assets_sha256[:12]}); "
                "re-review and re-pin with scripts/pin_integrity.py"
            ],
        )
    if platform not in cap.platforms:
        return Rejection(
            cap,
            platform,
            "unsupported_platform",
            [f"not available for {adapter.info.display_name}"],
        )
    if not adapter.supports(cap.kind):
        return Rejection(
            cap,
            platform,
            "unsupported_platform",
            [f"{adapter.info.display_name} adapter does not support kind {cap.kind.value!r}"],
        )
    if cap.id in ctx.excluded_ids:
        return Rejection(cap, platform, "user_excluded", ["excluded by --exclude"])
    for d in cap.destinations_for(platform):
        if not adapter.path_allowed(d.dest):
            return Rejection(
                cap,
                platform,
                "unsupported_platform",
                [f"destination {d.dest} is outside the adapter's managed roots"],
            )

    applies, specificity, reasons = _applicability(cap, profile, ctx)
    if not applies:
        return Rejection(cap, platform, "not_applicable", reasons)

    # Policy runs after applicability only so that irrelevant capabilities read as
    # "not applicable" rather than "policy"; a denial is still enforced before planning.
    if ctx.policy is not None:
        decision, why = ctx.policy.evaluate(cap, platform, context_chars(reg.get(cap.id), platform))
        if decision == Decision.DENY:
            return Rejection(cap, platform, "policy_denied", ["denied by policy", *why])
        if decision == Decision.REQUIRE_REQUEST and not requested:
            return Rejection(
                cap,
                platform,
                "policy_requires_request",
                ["policy requires an explicit --request/--want for this capability", *why],
            )

    # Applicability comes first so a backend-only project never sees UI runtime hints.
    if cap.install_strategy == InstallStrategy.NATIVE_PLUGIN:
        hints = [
            f"{r.name}: {r.description}" + (f" ({r.install_hint})" if r.install_hint else "")
            for r in cap.runtime_requirements
        ]
        return Rejection(
            cap,
            platform,
            "needs_runtime",
            ["requires a native runtime/plugin that Agent Forge will not install", *hints],
        )

    if cap.id in installed:
        if installed[cap.id] == cap.version:
            return Rejection(
                cap, platform, "already_installed", [f"already installed at version {cap.version}"]
            )
        reasons.append(
            f"installed version {installed[cap.id]} differs from registry {cap.version} (use `upgrade`)"
        )
        return Rejection(cap, platform, "already_installed", reasons)

    existing: list[str] = []
    equivalents = find_equivalents(cap, profile, platform)
    if equivalents:
        existing = [f"{h.asset_path} ({h.matched_by}: {h.description})" for h in equivalents]
        if not requested:
            return Rejection(
                cap,
                platform,
                "equivalent_exists",
                ["project already has equivalent functionality: " + "; ".join(existing)],
            )
        reasons.append("installed despite existing equivalent because it was explicitly requested")

    collisions = destination_collisions(cap, profile, platform)
    if collisions:
        return Rejection(
            cap,
            platform,
            "conflict",
            [
                f"destination exists and is user-owned: {', '.join(collisions)} "
                "(remove or rename it, or choose another capability)"
            ],
        )

    cand = Candidate(cap, platform, reasons=reasons, existing=existing)
    cand.score = score(cap, profile, wanted_tags=set(ctx.wanted_tags), specificity=specificity)
    _apply_optional(cand, requested, ctx)
    return cand
