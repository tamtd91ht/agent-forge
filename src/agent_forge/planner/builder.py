"""Build assign/upgrade plans from match results. Plans never write to the target."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge import MANAGED_MANIFEST_VERSION, __version__
from agent_forge.adapters import get_adapter
from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.apply.jsonmerge import (
    conflicts,
    contains_fragment,
    parse_fragment,
    remove_fragment,
    replace_fragment,
)
from agent_forge.apply.sections import find_section, upsert_section
from agent_forge.errors import ApplyError, PlanError, SafetyViolation
from agent_forge.matching.rules import Candidate, MatchContext, MatchResult, evaluate
from agent_forge.models.capability import (
    Capability,
    CapabilityKind,
    CapabilityStatus,
    Destination,
    InstallStrategy,
    MergeStrategy,
    Platform,
    RiskLevel,
)
from agent_forge.models.plan import (
    Approval,
    FileOperation,
    OperationKind,
    Plan,
    RejectedCapability,
    SelectedCapability,
    TargetIdentity,
)
from agent_forge.models.project import ManagedCapabilityRecord, ProjectProfile
from agent_forge.registry.loader import LoadedCapability, Registry
from agent_forge.registry.validator import resolve_dependencies
from agent_forge.scanner.agent_detection import MANAGED_MANIFEST
from agent_forge.util import new_id, normalize_newlines, now_iso, sha256_text

_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


def transaction_id_for(plan_id: str) -> str:
    """Deterministic transaction id so the managed manifest can be fixed at plan time."""
    return "tx-" + plan_id.removeprefix("plan-")


@dataclass
class _TargetReader:
    root: Path
    cache: dict[str, str | None] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def read(self, rel: str) -> str | None:
        if rel in self.cache:
            return self.cache[rel]
        try:
            p = resolve_in_root(self.root, rel)
        except SafetyViolation as exc:
            self.problems.append(f"{rel}: {exc.message}")
            self.cache[rel] = None
            return None
        if not p.exists() or p.is_symlink() or not p.is_file():
            self.cache[rel] = None
            return None
        try:
            text = normalize_newlines(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            self.problems.append(f"{rel}: destination exists but cannot be read as UTF-8 text")
            text = None
        self.cache[rel] = text
        return text


def _asset_files(lc: LoadedCapability, dest: Destination) -> list[tuple[str, str]]:
    """Return [(dest_rel_path, content)] for a destination (file or directory source)."""
    src = lc.assets_dir / dest.source
    if not src.exists():
        raise PlanError(f"{lc.id}: asset missing: assets/{dest.source}")
    out: list[tuple[str, str]] = []
    if src.is_file():
        out.append((dest.dest.rstrip("/"), _read_asset(src, lc.id)))
        return out
    base = dest.dest.rstrip("/")
    for p in sorted(src.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(src).as_posix()
            out.append((f"{base}/{rel}", _read_asset(p, lc.id)))
    return out


def _read_asset(path: Path, cid: str) -> str:
    try:
        return normalize_newlines(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise PlanError(
            f"{cid}: asset {path.name} is not UTF-8 text; binary assets are not supported"
        ) from exc


def _manifest_content(records: list[ManagedCapabilityRecord]) -> str:
    data = {
        "version": MANAGED_MANIFEST_VERSION,
        "generated_by": f"agent-forge {__version__}",
        "note": "Managed by Agent Forge. Edit installed files freely; drift is detected, never overwritten.",
        "capabilities": [
            r.model_dump(mode="json", exclude={"drift"})
            for r in sorted(records, key=lambda r: r.capability_id)
        ],
    }
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def _ops_for_candidate(
    lc: LoadedCapability,
    platform: Platform,
    reader: _TargetReader,
    plan_id: str,
    op_counter: list[int],
) -> tuple[list[FileOperation], ManagedCapabilityRecord]:
    cap = lc.capability
    adapter = get_adapter(platform)
    ops: list[FileOperation] = []
    record = ManagedCapabilityRecord(
        capability_id=cap.id,
        version=cap.version,
        transaction_id=transaction_id_for(plan_id),
        installed_at="(set at apply time)",
    )
    for dest in cap.destinations_for(platform):
        if dest.merge == MergeStrategy.APPEND_SECTION:
            assert dest.section_id
            body = _asset_files(lc, dest)[0][1]
            current = reader.read(dest.dest)
            projected = upsert_section(current, dest.section_id, cap.id, cap.version, body)
            problems = adapter.validate_content(cap.kind, dest.dest, body)
            if problems:
                raise PlanError(
                    f"{cap.id}: content for {dest.dest} fails {adapter.info.display_name} rules: "
                    + "; ".join(problems)
                )
            op_counter[0] += 1
            ops.append(
                FileOperation(
                    op_id=f"op{op_counter[0]:03d}",
                    kind=OperationKind.MERGE_SECTION,
                    path=dest.dest,
                    capability_id=cap.id,
                    capability_version=cap.version,
                    platform=platform,
                    section_id=dest.section_id,
                    content=body,
                    content_sha256=sha256_text(body),
                    before_sha256=sha256_text(current) if current is not None else None,
                    after_sha256=sha256_text(projected),
                    shared_file=True,
                    requires_extra_approval=True,
                    approval_class="shared_file",
                    reason=f"add managed section '{dest.section_id}' to shared file (existing content preserved)",
                )
            )
            record.sections[dest.dest] = dest.section_id
            reader.cache[dest.dest] = projected
            continue
        if dest.merge == MergeStrategy.JSON_MERGE:
            op, fragment = _json_merge_op(lc, dest, platform, reader, op_counter, previous=None)
            ops.append(op)
            record.json_merges[dest.dest] = fragment
            continue
        for rel, content in _asset_files(lc, dest):
            if not adapter.path_allowed(rel):
                raise PlanError(
                    f"{cap.id}: destination {rel} is outside {adapter.info.display_name} managed roots"
                )
            problems = (
                adapter.validate_content(cap.kind, rel, content)
                if rel.endswith(".md") and _is_primary(cap, rel)
                else []
            )
            if problems:
                raise PlanError(
                    f"{cap.id}: {rel} fails {adapter.info.display_name} rules: "
                    + "; ".join(problems)
                )
            current = reader.read(rel)
            kind = OperationKind.CREATE if current is None else OperationKind.REPLACE
            if current is not None and dest.merge == MergeStrategy.CREATE_ONLY:
                raise PlanError(f"{cap.id}: {rel} already exists and merge strategy is create_only")
            op_counter[0] += 1
            ops.append(
                FileOperation(
                    op_id=f"op{op_counter[0]:03d}",
                    kind=kind,
                    path=rel,
                    capability_id=cap.id,
                    capability_version=cap.version,
                    platform=platform,
                    content=content,
                    content_sha256=sha256_text(content),
                    before_sha256=sha256_text(current) if current is not None else None,
                    after_sha256=sha256_text(content),
                    shared_file=adapter.is_shared_file(rel),
                    requires_extra_approval=adapter.is_shared_file(rel),
                    reason=f"install {cap.kind.value} '{cap.name}' for {adapter.info.display_name}",
                )
            )
            record.files[rel] = sha256_text(content)
            reader.cache[rel] = content
    return ops, record


def _json_merge_op(
    lc: LoadedCapability,
    dest: Destination,
    platform: Platform,
    reader: _TargetReader,
    op_counter: list[int],
    *,
    previous: dict | None,
) -> tuple[FileOperation, dict]:
    """Build a MERGE_JSON operation for a hooks / mcpServers fragment."""
    cap = lc.capability
    adapter = get_adapter(platform)
    assert dest.section_id
    text = _asset_files(lc, dest)[0][1]
    try:
        fragment = parse_fragment(text)
    except ApplyError as exc:
        raise PlanError(f"{cap.id}: assets/{dest.source}: {exc.message}") from exc
    problems = adapter.validate_content(cap.kind, dest.dest, text)
    if problems:
        raise PlanError(
            f"{cap.id}: fragment for {dest.dest} fails {adapter.info.display_name} rules: "
            + "; ".join(problems)
        )
    current = reader.read(dest.dest)
    try:
        clash = conflicts(remove_fragment(current, previous) if previous else current, fragment)
        if clash:
            raise PlanError(
                f"{cap.id}: {dest.dest} already defines MCP server(s) {', '.join(clash)} with a "
                "different configuration; remove them or --exclude this capability"
            )
        projected = replace_fragment(current, previous, fragment, path_hint=dest.dest)
    except ApplyError as exc:
        raise PlanError(f"{cap.id}: {exc.message}") from exc
    reader.cache[dest.dest] = projected
    klass = (
        "hook"
        if cap.kind == CapabilityKind.HOOK
        else "mcp"
        if cap.kind == CapabilityKind.MCP
        else "shared_file"
    )
    op_counter[0] += 1
    op = FileOperation(
        op_id=f"op{op_counter[0]:03d}",
        kind=OperationKind.MERGE_JSON,
        path=dest.dest,
        capability_id=cap.id,
        capability_version=cap.version,
        platform=platform,
        section_id=dest.section_id,
        content=text,
        content_sha256=sha256_text(text),
        before_sha256=sha256_text(current) if current is not None else None,
        after_sha256=sha256_text(projected),
        shared_file=True,
        requires_extra_approval=True,
        approval_class=klass,
        previous_content=json.dumps(previous, sort_keys=True) if previous else None,
        reason=f"merge {cap.kind.value} fragment '{dest.section_id}' into {dest.dest} "
        f"(other entries preserved; needs `approve --{klass if klass != 'shared_file' else 'shared-files'}`)",
    )
    return op, fragment


def _is_primary(cap: Capability, rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if cap.kind.value == "skill":
        return name == "SKILL.md"
    return name.endswith(".md")


def _selected_entry(
    cand: Candidate, lc: LoadedCapability, ops: list[FileOperation]
) -> SelectedCapability:
    cap = cand.capability
    adapter = get_adapter(cand.platform)
    adds = [f"{o.kind.value} {o.path}" for o in ops]
    validation = [f"{v.type} {v.path}" for v in cap.validation] or [
        f"{adapter.info.display_name} format rules on installed files",
        "file hashes recorded in .agent-forge/managed.json",
    ]
    rollback = (
        "delete created files / restore backups of modified files via `agent-forge rollback`"
        if cap.removal == "delete_managed_files"
        else "remove managed section via `agent-forge rollback`"
    )
    return SelectedCapability(
        capability_id=cap.id,
        version=cap.version,
        platform=cand.platform,
        score=round(cand.score.total, 2),
        risk=cap.risk,
        reasons=[*cand.reasons, *cand.score.explain()],
        solves=cap.purpose,
        existing=cand.existing,
        adds=adds,
        dependencies=list(cap.dependencies),
        conflicts=list(cap.conflicts),
        validation=validation,
        rollback=rollback,
        optional=cand.optional,
    )


def _identity(profile: ProjectProfile) -> TargetIdentity:
    return TargetIdentity(
        canonical_path=profile.canonical_path,
        git_root=profile.git.root,
        git_head=profile.git.head,
        git_dirty=profile.git.dirty,
        profile_fingerprint=profile.fingerprint(),
    )


def build_assign_plan(
    reg: Registry, profile: ProjectProfile, ctx: MatchContext
) -> tuple[Plan, MatchResult]:
    match = evaluate(reg, profile, ctx)
    plan_id = new_id("plan")
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    ops: list[FileOperation] = []
    selected: list[SelectedCapability] = []
    records: list[ManagedCapabilityRecord] = (
        list(profile.managed) if profile.managed_manifest_valid else []
    )
    counter = [0]
    chosen = match.recommended
    order = resolve_dependencies(reg, [c.capability.id for c in chosen])
    by_key = {(c.capability.id, c.platform): c for c in chosen}
    rejected_for_approval: list[RejectedCapability] = []
    for cid in order:
        for platform in ctx.platforms:
            cand = by_key.get((cid, platform))
            if cand is None:
                continue
            lc = reg.get(cid)
            cap_ops, record = _ops_for_candidate(lc, platform, reader, plan_id, counter)
            needed = sorted({o.approval_class for o in cap_ops} - ctx.allowed_classes)
            if needed:
                counter[0] -= len(cap_ops)
                rejected_for_approval.append(
                    RejectedCapability(
                        capability_id=cid,
                        version=lc.capability.version,
                        reasons=[
                            "needs explicit approval class(es) not granted: " + ", ".join(needed),
                            "re-run with "
                            + " ".join(
                                {
                                    "shared_file": "--shared-files",
                                    "hook": "--hooks",
                                    "mcp": "--mcp",
                                }.get(k, k)
                                for k in needed
                            ),
                        ],
                        category="needs_approval",
                    )
                )
                continue
            ops.extend(cap_ops)
            existing_rec = next((r for r in records if r.capability_id == cid), None)
            if existing_rec is not None:
                existing_rec.files.update(record.files)
                existing_rec.sections.update(record.sections)
                existing_rec.json_merges.update(record.json_merges)
                existing_rec.version = record.version
                existing_rec.transaction_id = record.transaction_id
            else:
                records.append(record)
            selected.append(_selected_entry(cand, lc, cap_ops))
    if ops:
        counter[0] += 1
        manifest_text = _manifest_content(records)
        current_manifest = reader.read(MANAGED_MANIFEST)
        ops.append(
            FileOperation(
                op_id=f"op{counter[0]:03d}",
                kind=OperationKind.MANIFEST,
                path=MANAGED_MANIFEST,
                content=manifest_text,
                content_sha256=sha256_text(manifest_text),
                before_sha256=sha256_text(current_manifest)
                if current_manifest is not None
                else None,
                after_sha256=sha256_text(manifest_text),
                reason="record managed capabilities, versions and file hashes",
            )
        )
    rejected = [
        RejectedCapability(
            capability_id=r.capability.id,
            version=r.capability.version,
            reasons=r.reasons,
            category=r.category,
        )
        for r in match.rejected
    ]
    rejected.extend(rejected_for_approval)
    selected = [
        s
        for s in selected
        if s.capability_id not in {r.capability_id for r in rejected_for_approval}
    ]
    for opt in match.optional:
        rejected.append(
            RejectedCapability(
                capability_id=opt.capability.id,
                version=opt.capability.version,
                reasons=[
                    *opt.reasons,
                    "re-run with --include-optional or --request <id> to include",
                ],
                category="optional",
            )
        )
    risk = max((s.risk for s in selected), key=lambda r: _RISK_ORDER[r], default=RiskLevel.LOW)
    notes = [*match.notes, *(f"warning: {p}" for p in reader.problems)]
    if profile.git.is_repo and profile.git.dirty:
        notes.append(
            "target has uncommitted changes; commit or stash before applying for an easy git-level review"
        )
    plan = Plan(
        plan_id=plan_id,
        kind="assign",
        created_at=now_iso(),
        forge_version=__version__,
        target=_identity(profile),
        target_path=profile.target_path,
        registry_digest=reg.digest,
        selected=selected,
        rejected=rejected,
        dependency_order=order,
        operations=ops,
        risk=risk,
        validation_plan=_validation_plan(selected, profile),
        rollback_strategy=(
            "Each operation records before/after hashes and a backup; `agent-forge rollback <tx>` "
            "restores files that still match their post-apply hash and refuses the rest."
        ),
        user_decisions=match.user_decisions,
        notes=notes,
        approval=Approval(required=True),
    )
    return plan, match


def _validation_plan(selected: list[SelectedCapability], profile: ProjectProfile) -> list[str]:
    out = [
        "verify every written file hashes to its planned content",
        "validate installed files against platform format rules",
        "verify .agent-forge/managed.json round-trips",
    ]
    if profile.test_commands:
        out.append(
            "project test commands are NOT run automatically: " + "; ".join(profile.test_commands)
        )
    return out


def build_upgrade_plan(reg: Registry, profile: ProjectProfile, ctx: MatchContext) -> Plan:
    """Compare managed capabilities with the registry; produce replace/merge operations."""
    plan_id = new_id("plan")
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    ops: list[FileOperation] = []
    selected: list[SelectedCapability] = []
    rejected: list[RejectedCapability] = []
    notes: list[str] = []
    decisions: list[str] = []
    counter = [0]
    if profile.managed_manifest_valid is None:
        notes.append("target has no .agent-forge/managed.json; nothing to upgrade (use `assign`)")
    elif profile.managed_manifest_valid is False:
        raise PlanError(
            "target managed manifest is invalid; refusing to plan an upgrade",
            hint="See `agent-forge scan` warnings.",
        )
    records = [r.model_copy(deep=True) for r in profile.managed]
    for rec in records:
        if rec.capability_id not in reg.items:
            notes.append(
                f"{rec.capability_id}: no longer in the registry; left untouched (remove manually or via rollback)"
            )
            continue
        lc = reg.get(rec.capability_id)
        cap = lc.capability
        if cap.status == CapabilityStatus.DEPRECATED:
            notes.append(f"{cap.id}: deprecated in registry; not upgraded automatically")
            rejected.append(
                RejectedCapability(
                    capability_id=cap.id,
                    version=cap.version,
                    reasons=["deprecated"],
                    category="not_applicable",
                )
            )
            continue
        if cap.status != CapabilityStatus.CURATED or cap.install_strategy not in (
            InstallStrategy.FILE_COPY,
            InstallStrategy.SECTION_MERGE,
        ):
            notes.append(
                f"{cap.id}: registry entry is no longer installable ({cap.status.value}); left untouched"
            )
            continue
        if rec.drift:
            decisions.append(
                f"{cap.id}: locally modified files ({', '.join(rec.drift)}); upgrade skipped to preserve your changes"
            )
            rejected.append(
                RejectedCapability(
                    capability_id=cap.id,
                    version=cap.version,
                    reasons=["local drift: " + ", ".join(rec.drift)],
                    category="conflict",
                )
            )
            continue
        if rec.version == cap.version:
            continue
        old_version = rec.version
        missing_deps = [d for d in cap.dependencies if d not in {r.capability_id for r in records}]
        if missing_deps:
            rejected.append(
                RejectedCapability(
                    capability_id=cap.id,
                    version=cap.version,
                    reasons=[
                        f"new version requires {', '.join(missing_deps)} (run `assign --request ...`)"
                    ],
                    category="dependency_missing",
                )
            )
            continue
        installed_ids = {r.capability_id for r in records}
        if set(cap.conflicts) & installed_ids:
            rejected.append(
                RejectedCapability(
                    capability_id=cap.id,
                    version=cap.version,
                    reasons=[
                        "new version conflicts with installed "
                        + ", ".join(sorted(set(cap.conflicts) & installed_ids))
                    ],
                    category="conflict",
                )
            )
            continue
        platforms = [p for p in ctx.platforms if p in cap.platforms] or [p for p in cap.platforms]
        cap_ops: list[FileOperation] = []
        new_record = ManagedCapabilityRecord(
            capability_id=cap.id,
            version=cap.version,
            transaction_id=transaction_id_for(plan_id),
            installed_at="(set at apply time)",
        )
        for platform in platforms:
            platform_ops, prec = _ops_for_candidate_upgrade(
                lc, platform, reader, rec, plan_id, counter
            )
            cap_ops.extend(platform_ops)
            new_record.files.update(prec.files)
            new_record.sections.update(prec.sections)
        # files that the old version managed but the new one does not -> remove
        for old_rel, old_hash in rec.files.items():
            if old_rel not in new_record.files:
                counter[0] += 1
                cap_ops.append(
                    FileOperation(
                        op_id=f"op{counter[0]:03d}",
                        kind=OperationKind.REMOVE,
                        path=old_rel,
                        capability_id=cap.id,
                        capability_version=cap.version,
                        before_sha256=old_hash,
                        reason="file no longer part of the capability",
                    )
                )
        needed = sorted({o.approval_class for o in cap_ops} - ctx.allowed_classes)
        if needed:
            counter[0] -= len(cap_ops)
            rejected.append(
                RejectedCapability(
                    capability_id=cap.id,
                    version=cap.version,
                    reasons=["upgrade needs approval class(es) not granted: " + ", ".join(needed)],
                    category="needs_approval",
                )
            )
            continue
        ops.extend(cap_ops)
        rec.files = new_record.files
        rec.sections = new_record.sections
        rec.json_merges = new_record.json_merges
        rec.version = cap.version
        rec.transaction_id = new_record.transaction_id
        selected.append(
            SelectedCapability(
                capability_id=cap.id,
                version=cap.version,
                platform=platforms[0],
                score=0.0,
                risk=cap.risk,
                reasons=[
                    f"upgrade {rec.capability_id}: installed {old_version} -> registry {cap.version}"
                ],
                solves=cap.purpose,
                adds=[f"{o.kind.value} {o.path}" for o in cap_ops],
                dependencies=list(cap.dependencies),
                conflicts=list(cap.conflicts),
                validation=["hash verification", "platform format rules"],
                rollback="restore previous version from transaction backups",
            )
        )
    if ops:
        counter[0] += 1
        manifest_text = _manifest_content(records)
        current_manifest = reader.read(MANAGED_MANIFEST)
        ops.append(
            FileOperation(
                op_id=f"op{counter[0]:03d}",
                kind=OperationKind.MANIFEST,
                path=MANAGED_MANIFEST,
                content=manifest_text,
                content_sha256=sha256_text(manifest_text),
                before_sha256=sha256_text(current_manifest)
                if current_manifest is not None
                else None,
                after_sha256=sha256_text(manifest_text),
                reason="update managed manifest",
            )
        )
    risk = max((s.risk for s in selected), key=lambda r: _RISK_ORDER[r], default=RiskLevel.LOW)
    return Plan(
        plan_id=plan_id,
        kind="upgrade",
        created_at=now_iso(),
        forge_version=__version__,
        target=_identity(profile),
        target_path=profile.target_path,
        registry_digest=reg.digest,
        selected=selected,
        rejected=rejected,
        dependency_order=[s.capability_id for s in selected],
        operations=ops,
        risk=risk,
        validation_plan=_validation_plan(selected, profile),
        rollback_strategy="restore previous file versions from transaction backups where post-apply hashes still match",
        user_decisions=decisions,
        notes=[*notes, *(f"warning: {p}" for p in reader.problems)],
        approval=Approval(required=True),
    )


def _ops_for_candidate_upgrade(
    lc: LoadedCapability,
    platform: Platform,
    reader: _TargetReader,
    old: ManagedCapabilityRecord,
    plan_id: str,
    counter: list[int],
) -> tuple[list[FileOperation], ManagedCapabilityRecord]:
    """Like _ops_for_candidate but existing managed files are replaced, not treated as collisions."""
    cap = lc.capability
    adapter = get_adapter(platform)
    ops: list[FileOperation] = []
    record = ManagedCapabilityRecord(
        capability_id=cap.id,
        version=cap.version,
        transaction_id=transaction_id_for(plan_id),
        installed_at="(set at apply time)",
    )
    for dest in cap.destinations_for(platform):
        if dest.merge == MergeStrategy.APPEND_SECTION:
            assert dest.section_id
            body = _asset_files(lc, dest)[0][1]
            current = reader.read(dest.dest)
            existing = find_section(current, dest.section_id) if current else None
            if current is not None and existing is None and dest.dest in old.sections:
                raise PlanError(
                    f"{cap.id}: managed section {dest.section_id} missing from {dest.dest}; resolve manually"
                )
            projected = upsert_section(current, dest.section_id, cap.id, cap.version, body)
            if (
                existing is not None
                and existing.body == body.strip("\n")
                and existing.version == cap.version
            ):
                record.sections[dest.dest] = dest.section_id
                continue
            counter[0] += 1
            ops.append(
                FileOperation(
                    op_id=f"op{counter[0]:03d}",
                    kind=OperationKind.MERGE_SECTION,
                    path=dest.dest,
                    capability_id=cap.id,
                    capability_version=cap.version,
                    platform=platform,
                    section_id=dest.section_id,
                    content=body,
                    content_sha256=sha256_text(body),
                    before_sha256=sha256_text(current) if current is not None else None,
                    after_sha256=sha256_text(projected),
                    shared_file=True,
                    requires_extra_approval=True,
                    approval_class="shared_file",
                    reason=f"update managed section '{dest.section_id}'",
                )
            )
            record.sections[dest.dest] = dest.section_id
            reader.cache[dest.dest] = projected
            continue
        if dest.merge == MergeStrategy.JSON_MERGE:
            previous = old.json_merges.get(dest.dest)
            current = reader.read(dest.dest)
            new_fragment = parse_fragment(_asset_files(lc, dest)[0][1])
            if previous == new_fragment and contains_fragment(current, new_fragment):
                record.json_merges[dest.dest] = new_fragment
                continue  # unchanged
            op, fragment = _json_merge_op(lc, dest, platform, reader, counter, previous=previous)
            ops.append(op)
            record.json_merges[dest.dest] = fragment
            continue
        for rel, content in _asset_files(lc, dest):
            if not adapter.path_allowed(rel):
                raise PlanError(f"{cap.id}: destination {rel} is outside managed roots")
            current = reader.read(rel)
            new_hash = sha256_text(content)
            record.files[rel] = new_hash
            if current is not None and sha256_text(current) == new_hash:
                continue  # unchanged
            if current is not None and rel not in old.files:
                raise PlanError(
                    f"{cap.id}: {rel} exists but is not managed by the installed version; resolve manually"
                )
            counter[0] += 1
            ops.append(
                FileOperation(
                    op_id=f"op{counter[0]:03d}",
                    kind=OperationKind.CREATE if current is None else OperationKind.REPLACE,
                    path=rel,
                    capability_id=cap.id,
                    capability_version=cap.version,
                    platform=platform,
                    content=content,
                    content_sha256=new_hash,
                    before_sha256=sha256_text(current) if current is not None else None,
                    after_sha256=new_hash,
                    shared_file=adapter.is_shared_file(rel),
                    requires_extra_approval=adapter.is_shared_file(rel),
                    reason=f"upgrade {cap.kind.value} '{cap.name}'",
                )
            )
            reader.cache[rel] = content
    return ops, record
