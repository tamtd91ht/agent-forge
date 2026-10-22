"""`agent-forge import`: bring hand-written agent assets under management, in place (ADR-0011).

A project usually has skills, subagents, rules and commands that nobody installed: the team
wrote them. Until they are recorded, `status`, `usage`, `drift`, `remove` and the decision
record cannot see them. `build_import_plan` records them in `.agent-forge/managed.json` as
`local.<kind>.<name>` entries (version `0.0.0`, one record per logical asset across
platforms, the current file hashes) and nothing else: the plan's only operation is the
manifest write, so the files themselves are never copied, rewritten or moved. Approval,
apply, transaction and rollback are the ordinary ones; rolling back restores the previous
manifest and leaves the files alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_forge import __version__
from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.errors import PlanError, SafetyViolation
from agent_forge.models.capability import Platform, RiskLevel
from agent_forge.models.plan import (
    Approval,
    FileOperation,
    OperationKind,
    Plan,
    SelectedCapability,
)
from agent_forge.models.project import (
    LOCAL_ID_PREFIX,
    LOCAL_VERSION,
    AgentAsset,
    ManagedCapabilityRecord,
    ProjectProfile,
    is_local,
)
from agent_forge.planner.builder import (
    _identity,
    _manifest_content,
    _TargetReader,
    transaction_id_for,
)
from agent_forge.registry.loader import Registry
from agent_forge.scanner.agent_detection import MANAGED_MANIFEST
from agent_forge.util import new_id, normalize_newlines, now_iso, sha256_text

ADOPTABLE_KINDS: tuple[str, ...] = ("skill", "agent", "rule", "command")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def local_id(kind: str, name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-") or "unnamed"
    return f"{LOCAL_ID_PREFIX}{kind}.{slug}"


def _asset_name(asset: AgentAsset) -> str:
    parts = asset.path.split("/")
    if parts[-1] == "SKILL.md" and len(parts) >= 2:
        return parts[-2]
    return parts[-1].rsplit(".", 1)[0]


def adoptable_assets(
    profile: ProjectProfile, *, kinds: tuple[str, ...] | None = None, paths: tuple[str, ...] = ()
) -> list[AgentAsset]:
    """Hand-written assets of an adoptable kind: not owned by a registry install (a local
    record's files are included, so a re-import can refresh their hashes)."""
    wanted = set(kinds or ADOPTABLE_KINDS)
    unknown = wanted - set(ADOPTABLE_KINDS)
    if unknown:
        raise PlanError(
            "cannot import kind(s) " + ", ".join(sorted(unknown)),
            hint="Importable kinds: " + ", ".join(ADOPTABLE_KINDS) + ".",
        )
    owned = {rel for rec in profile.managed if not rec.is_local for rel in rec.files}
    out = [
        a
        for a in profile.assets
        if a.kind in wanted
        and a.platform is not None
        and (a.managed_by is None or is_local(a.managed_by))
        and a.path not in owned
        and not _asset_name(a).startswith("_")
    ]
    if paths:
        prefixes = tuple(p.rstrip("/") for p in paths)
        out = [a for a in out if any(a.path == p or a.path.startswith(p + "/") for p in prefixes)]
    return sorted(out, key=lambda a: a.path)


def _entry(
    cid: str,
    record: ManagedCapabilityRecord,
    why: str,
    adds: list[str],
    first: AgentAsset | None = None,
) -> SelectedCapability:
    kind, _, name = cid.removeprefix(LOCAL_ID_PREFIX).partition(".")
    return SelectedCapability(
        capability_id=cid,
        version=LOCAL_VERSION,
        platform=first.platform if first is not None and first.platform else Platform.CLAUDE_CODE,
        score=0.0,
        risk=RiskLevel.LOW,
        reasons=[why],
        solves=f"tracks the project's own {kind} '{name}'",
        adds=adds,
        validation=["file hashes recorded in .agent-forge/managed.json"],
        rollback="restore the previous managed.json; the files are never touched",
    )


def build_import_plan(
    reg: Registry,
    profile: ProjectProfile,
    *,
    kinds: tuple[str, ...] | None = None,
    paths: tuple[str, ...] = (),
) -> Plan:
    """A plan whose only operation records the adopted assets in the managed manifest."""
    if profile.managed_manifest_valid is False:
        raise PlanError(
            "target managed manifest is invalid; refusing to import",
            hint="See `agent-forge scan` warnings.",
        )
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    assets = adoptable_assets(profile, kinds=kinds, paths=paths)
    groups: dict[str, list[AgentAsset]] = {}
    for a in assets:
        groups.setdefault(local_id(a.kind, _asset_name(a)), []).append(a)
    records = [r.model_copy(deep=True) for r in profile.managed]
    existing = {r.capability_id: r for r in records if r.is_local}
    selected: list[SelectedCapability] = []
    notes: list[str] = []
    skipped: list[str] = []
    plan_id = new_id("plan")
    # a local record whose files are all gone is dropped; nothing is left to track
    for cid, rec in sorted(existing.items()):
        if all(not resolve_in_root(root, rel).is_file() for rel in rec.files):
            records.remove(rec)
            notes.append(f"{cid}: every adopted file is gone; dropped from the manifest")
            selected.append(_entry(cid, rec, "every adopted file is gone; untracked", []))
    for cid, items in sorted(groups.items()):
        files: dict[str, str] = {}
        for a in items:
            try:
                p = resolve_in_root(root, a.path)
            except SafetyViolation as exc:
                skipped.append(f"{a.path}: {exc.message}")
                continue
            if not p.is_file() or p.is_symlink():
                skipped.append(f"{a.path}: not a regular file")
                continue
            try:
                text = normalize_newlines(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                skipped.append(f"{a.path}: not UTF-8 text")
                continue
            files[a.path] = sha256_text(text)
        if not files:
            continue
        previous = existing.get(cid)
        if previous is not None and previous.files == files:
            continue  # already recorded with these hashes
        record = ManagedCapabilityRecord(
            capability_id=cid,
            version=LOCAL_VERSION,
            transaction_id=transaction_id_for(plan_id),
            installed_at="(set at apply time)",
            files=files,
        )
        if previous is not None:
            records[records.index(previous)] = record
            why = "re-import: recorded hashes refreshed to the current files"
        else:
            records.append(record)
            why = "hand-written; adopted in place, content untouched"
        first = items[0]
        selected.append(_entry(cid, record, why, [f"track {rel}" for rel in sorted(files)], first))
    ops: list[FileOperation] = []
    if selected:
        manifest_text = _manifest_content(records)
        current_manifest = reader.read(MANAGED_MANIFEST)
        ops.append(
            FileOperation(
                op_id="op001",
                kind=OperationKind.MANIFEST,
                path=MANAGED_MANIFEST,
                content=manifest_text,
                content_sha256=sha256_text(manifest_text),
                before_sha256=sha256_text(current_manifest)
                if current_manifest is not None
                else None,
                after_sha256=sha256_text(manifest_text),
                reason=f"record {len(selected)} hand-written asset(s) as local.* entries",
            )
        )
    else:
        notes.append("nothing to import: every adoptable asset is already recorded, or none exists")
    notes.extend(f"skipped {s}" for s in skipped)
    notes.extend(reader.problems)
    return Plan(
        plan_id=plan_id,
        kind="import",
        created_at=now_iso(),
        forge_version=__version__,
        target=_identity(profile),
        target_path=profile.target_path,
        registry_digest=reg.digest,
        selected=selected,
        operations=ops,
        risk=RiskLevel.LOW,
        validation_plan=["managed manifest lists every adopted asset with its current hash"],
        rollback_strategy="restore the previous managed.json via `agent-forge rollback`; "
        "adopted files are never written",
        notes=notes,
        approval=Approval(required=True),
    )
