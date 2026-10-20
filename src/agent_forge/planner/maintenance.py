"""Maintenance plans: drift report, `remove` and `repair`.

All three operate on the managed manifest (`.agent-forge/managed.json`) and the registry.
They produce ordinary plans (same approval + apply path); nothing here writes to the target.

Repair strategies (per capability, chosen explicitly by the user):
  restore   rewrite drifted managed files from the registry at the *installed* version if that
            version is still in the registry (otherwise refused) — user edits are replaced,
            which is why it is a plan with before-hashes and backups, never silent
  unmanage  drop the capability from the manifest; files stay as they are and become
            user-owned (no file operation except the manifest)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge import __version__
from agent_forge.adapters import platform_owning
from agent_forge.apply.jsonmerge import contains_fragment, remove_fragment
from agent_forge.apply.sections import find_section, remove_section, upsert_section
from agent_forge.errors import ApplyError, PlanError
from agent_forge.models.capability import MergeStrategy, Platform
from agent_forge.models.plan import (
    Approval,
    FileOperation,
    OperationKind,
    Plan,
    RejectedCapability,
    RiskLevel,
    SelectedCapability,
)
from agent_forge.models.project import ProjectProfile
from agent_forge.planner.builder import (
    _asset_files,
    _identity,
    _json_merge_op,
    _manifest_content,
    _TargetReader,
    transaction_id_for,
)
from agent_forge.registry.loader import Registry
from agent_forge.scanner.agent_detection import MANAGED_MANIFEST
from agent_forge.util import new_id, now_iso, sha256_text

# ---- drift ---------------------------------------------------------------------------------


@dataclass
class DriftItem:
    capability_id: str
    path: str
    kind: str  # file | section | json
    expected: str | None
    actual: str | None
    state: str  # ok | modified | missing | section_missing | entries_missing


@dataclass
class DriftReport:
    target: str
    items: list[DriftItem] = field(default_factory=list)

    @property
    def drifted(self) -> list[DriftItem]:
        return [i for i in self.items if i.state != "ok"]

    def by_capability(self) -> dict[str, list[DriftItem]]:
        out: dict[str, list[DriftItem]] = {}
        for i in self.items:
            out.setdefault(i.capability_id, []).append(i)
        return out


def drift_report(profile: ProjectProfile) -> DriftReport:
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    rep = DriftReport(target=profile.canonical_path)
    for rec in profile.managed:
        for rel, expected in rec.files.items():
            cur = reader.read(rel)
            actual = sha256_text(cur) if cur is not None else None
            state = "missing" if cur is None else ("ok" if actual == expected else "modified")
            rep.items.append(DriftItem(rec.capability_id, rel, "file", expected, actual, state))
        for rel, sid in rec.sections.items():
            cur = reader.read(rel)
            try:
                info = find_section(cur, sid) if cur else None
            except ApplyError:
                info = None
            state = "ok" if info is not None else "section_missing"
            rep.items.append(DriftItem(rec.capability_id, rel, "section", sid, None, state))
        for rel, fragment in rec.json_merges.items():
            cur = reader.read(rel)
            try:
                present = contains_fragment(cur, fragment)
            except ApplyError:
                present = False
            state = "ok" if present else "entries_missing"
            rep.items.append(DriftItem(rec.capability_id, rel, "json", None, None, state))
    return rep


def _platform_for(rel: str) -> Platform | None:
    return platform_owning(rel)


# ---- remove --------------------------------------------------------------------------------


def build_remove_plan(
    reg: Registry,
    profile: ProjectProfile,
    capability_ids: list[str],
    *,
    keep_modified: bool = False,
) -> Plan:
    """Plan the removal of managed capabilities (files, sections, merged entries, manifest)."""
    if profile.managed_manifest_valid is not True:
        raise PlanError("target has no valid .agent-forge/managed.json; nothing to remove")
    records = {r.capability_id: r.model_copy(deep=True) for r in profile.managed}
    missing = [c for c in capability_ids if c not in records]
    if missing:
        raise PlanError("not managed in this project: " + ", ".join(missing))
    dependants = [
        r.capability_id
        for r in records.values()
        if r.capability_id not in capability_ids
        and r.capability_id in reg.items
        and set(reg.items[r.capability_id].capability.dependency_ids) & set(capability_ids)
    ]
    if dependants:
        raise PlanError(
            "other managed capabilities depend on what you are removing: " + ", ".join(dependants),
            hint="Remove them too, or keep the dependency.",
        )
    plan_id = new_id("plan")
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    ops: list[FileOperation] = []
    selected: list[SelectedCapability] = []
    decisions: list[str] = []
    counter = 0
    for cid in capability_ids:
        rec = records[cid]
        cap_ops: list[FileOperation] = []
        for rel, expected in rec.files.items():
            cur = reader.read(rel)
            if cur is None:
                continue
            if sha256_text(cur) != expected:
                if keep_modified:
                    decisions.append(
                        f"{cid}: {rel} was modified; kept as user-owned (--keep-modified)"
                    )
                    continue
                raise PlanError(
                    f"{cid}: {rel} was modified after install; refusing to delete it",
                    hint="Revert your edits, or pass --keep-modified to unmanage modified files.",
                )
            counter += 1
            cap_ops.append(
                FileOperation(
                    op_id=f"op{counter:03d}",
                    kind=OperationKind.REMOVE,
                    path=rel,
                    capability_id=cid,
                    platform=_platform_for(rel),
                    capability_version=rec.version,
                    before_sha256=expected,
                    reason=f"remove managed file of {cid}",
                )
            )
            reader.cache[rel] = None
        for rel, sid in rec.sections.items():
            cur = reader.read(rel)
            if cur is None or find_section(cur, sid) is None:
                continue
            projected = remove_section(cur, sid)
            counter += 1
            cap_ops.append(
                FileOperation(
                    op_id=f"op{counter:03d}",
                    kind=OperationKind.REMOVE_SECTION,
                    path=rel,
                    capability_id=cid,
                    platform=_platform_for(rel),
                    capability_version=rec.version,
                    section_id=sid,
                    before_sha256=sha256_text(cur),
                    after_sha256=sha256_text(projected),
                    shared_file=True,
                    requires_extra_approval=True,
                    approval_class="shared_file",
                    reason=f"remove managed section '{sid}' of {cid}",
                )
            )
            reader.cache[rel] = projected
        for rel, fragment in rec.json_merges.items():
            cur = reader.read(rel)
            if cur is None or not contains_fragment(cur, fragment):
                continue
            projected = remove_fragment(cur, fragment, path_hint=rel)
            text = json.dumps(fragment)
            klass = "mcp" if "mcpServers" in fragment else "hook"
            counter += 1
            cap_ops.append(
                FileOperation(
                    op_id=f"op{counter:03d}",
                    kind=OperationKind.REMOVE_JSON,
                    path=rel,
                    capability_id=cid,
                    platform=_platform_for(rel),
                    capability_version=rec.version,
                    section_id=f"remove-{cid}",
                    content=text,
                    content_sha256=sha256_text(text),
                    before_sha256=sha256_text(cur),
                    after_sha256=sha256_text(projected) if projected else None,
                    shared_file=True,
                    requires_extra_approval=True,
                    approval_class=klass,
                    reason=f"remove merged {klass} entries of {cid}",
                )
            )
            reader.cache[rel] = projected if projected else None
        ops.extend(cap_ops)
        del records[cid]
        selected.append(
            SelectedCapability(
                capability_id=cid,
                version=rec.version,
                platform=Platform.CLAUDE_CODE,
                score=0.0,
                risk=RiskLevel.LOW,
                reasons=["requested removal"],
                adds=[f"{o.kind.value} {o.path}" for o in cap_ops],
                rollback="restore from transaction backups",
            )
        )
    counter += 1
    manifest_text = _manifest_content(list(records.values()))
    current_manifest = reader.read(MANAGED_MANIFEST)
    ops.append(
        FileOperation(
            op_id=f"op{counter:03d}",
            kind=OperationKind.MANIFEST,
            path=MANAGED_MANIFEST,
            content=manifest_text,
            content_sha256=sha256_text(manifest_text),
            before_sha256=sha256_text(current_manifest) if current_manifest is not None else None,
            after_sha256=sha256_text(manifest_text),
            reason="drop removed capabilities from the managed manifest",
        )
    )
    return Plan(
        plan_id=plan_id,
        kind="remove",
        created_at=now_iso(),
        forge_version=__version__,
        target=_identity(profile),
        target_path=profile.target_path,
        registry_digest=reg.digest,
        selected=selected,
        dependency_order=list(capability_ids),
        operations=ops,
        risk=RiskLevel.LOW,
        validation_plan=["managed manifest no longer lists the removed capabilities"],
        rollback_strategy="restore removed files and sections from transaction backups",
        user_decisions=decisions,
        approval=Approval(required=True),
    )


# ---- repair --------------------------------------------------------------------------------


def build_repair_plan(
    reg: Registry,
    profile: ProjectProfile,
    strategy: str,
    capability_ids: list[str] | None = None,
) -> Plan:
    """restore: rewrite drifted files from the registry; unmanage: drop from the manifest."""
    if strategy not in ("restore", "unmanage"):
        raise PlanError(f"unknown repair strategy {strategy!r}; use restore or unmanage")
    if profile.managed_manifest_valid is not True:
        raise PlanError("target has no valid .agent-forge/managed.json; nothing to repair")
    report = drift_report(profile)
    drifted_ids = sorted({i.capability_id for i in report.drifted})
    targets = capability_ids or drifted_ids
    unknown = [c for c in targets if c not in {r.capability_id for r in profile.managed}]
    if unknown:
        raise PlanError("not managed in this project: " + ", ".join(unknown))
    records = {r.capability_id: r.model_copy(deep=True) for r in profile.managed}
    plan_id = new_id("plan")
    root = Path(profile.canonical_path)
    reader = _TargetReader(root)
    ops: list[FileOperation] = []
    selected: list[SelectedCapability] = []
    rejected: list[RejectedCapability] = []
    notes: list[str] = []
    counter = [0]
    for cid in targets:
        rec = records[cid]
        items = [i for i in report.items if i.capability_id == cid and i.state != "ok"]
        if not items:
            notes.append(f"{cid}: no drift")
            continue
        if strategy == "unmanage":
            del records[cid]
            selected.append(
                SelectedCapability(
                    capability_id=cid,
                    version=rec.version,
                    platform=Platform.CLAUDE_CODE,
                    score=0.0,
                    risk=RiskLevel.LOW,
                    reasons=[f"unmanage: {len(items)} drifted item(s) become user-owned"],
                    rollback="re-run assign to manage again",
                )
            )
            continue
        lc = reg.items.get(cid)
        if lc is None or lc.capability.version != rec.version:
            rejected.append(
                RejectedCapability(
                    capability_id=cid,
                    version=rec.version,
                    reasons=[
                        "installed version is not in the registry; use `upgrade` instead of restore"
                    ],
                    category="conflict",
                )
            )
            continue
        cap = lc.capability
        cap_ops: list[FileOperation] = []
        for platform in cap.platforms:
            for dest in cap.destinations_for(platform):
                if dest.merge == MergeStrategy.JSON_MERGE:
                    if rec.json_merges.get(dest.dest) is None:
                        continue
                    if any(i.path == dest.dest and i.kind == "json" for i in items):
                        op, _fragment = _json_merge_op(
                            lc, dest, platform, reader, counter, previous=None
                        )
                        cap_ops.append(op)
                    continue
                if dest.merge == MergeStrategy.APPEND_SECTION:
                    assert dest.section_id
                    if dest.dest not in rec.sections or not any(
                        i.path == dest.dest and i.kind == "section" for i in items
                    ):
                        continue
                    body = _asset_files(lc, dest)[0][1]
                    current = reader.read(dest.dest)
                    projected = upsert_section(current, dest.section_id, cid, cap.version, body)
                    counter[0] += 1
                    cap_ops.append(
                        FileOperation(
                            op_id=f"op{counter[0]:03d}",
                            kind=OperationKind.MERGE_SECTION,
                            path=dest.dest,
                            capability_id=cid,
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
                            reason=f"restore managed section '{dest.section_id}' (section_missing)",
                        )
                    )
                    reader.cache[dest.dest] = projected
                    continue
                for rel, content in _asset_files(lc, dest):
                    item = next((i for i in items if i.path == rel and i.kind == "file"), None)
                    if item is None or rel not in rec.files:
                        continue
                    cur = reader.read(rel)
                    counter[0] += 1
                    cap_ops.append(
                        FileOperation(
                            op_id=f"op{counter[0]:03d}",
                            kind=OperationKind.CREATE if cur is None else OperationKind.REPLACE,
                            path=rel,
                            capability_id=cid,
                            capability_version=cap.version,
                            platform=platform,
                            content=content,
                            content_sha256=sha256_text(content),
                            before_sha256=sha256_text(cur) if cur is not None else None,
                            after_sha256=sha256_text(content),
                            reason=f"restore {rel} to registry content ({item.state})",
                        )
                    )
                    reader.cache[rel] = content
                    rec.files[rel] = sha256_text(content)
        if not cap_ops:
            notes.append(f"{cid}: nothing restorable (use `upgrade`)")
            continue
        ops.extend(cap_ops)
        rec.transaction_id = transaction_id_for(plan_id)
        selected.append(
            SelectedCapability(
                capability_id=cid,
                version=cap.version,
                platform=cap.platforms[0],
                score=0.0,
                risk=cap.risk,
                reasons=[f"restore {len(cap_ops)} drifted file(s) — your edits will be replaced"],
                adds=[f"{o.kind.value} {o.path}" for o in cap_ops],
                rollback="previous content is backed up by the transaction",
            )
        )
    if selected:
        counter[0] += 1
        manifest_text = _manifest_content(list(records.values()))
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
                reason="update managed manifest after repair",
            )
        )
    return Plan(
        plan_id=plan_id,
        kind=f"repair:{strategy}",
        created_at=now_iso(),
        forge_version=__version__,
        target=_identity(profile),
        target_path=profile.target_path,
        registry_digest=reg.digest,
        selected=selected,
        rejected=rejected,
        operations=ops,
        risk=RiskLevel.MEDIUM if strategy == "restore" and ops else RiskLevel.LOW,
        validation_plan=[
            "managed files hash to registry content"
            if strategy == "restore"
            else "manifest updated"
        ],
        rollback_strategy="transaction backups hold the pre-repair content",
        user_decisions=[
            f"{i.capability_id}: {i.path} is {i.state}"
            for i in report.drifted
            if i.capability_id in targets
        ],
        notes=notes,
        approval=Approval(required=True),
    )


__all__ = ["DriftItem", "DriftReport", "build_remove_plan", "build_repair_plan", "drift_report"]
