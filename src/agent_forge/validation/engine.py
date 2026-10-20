"""`agent-forge validate`: registry integrity, managed installation integrity, config syntax."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from agent_forge.adapters import get_adapter, platform_owning
from agent_forge.apply.backup import valid_backup_name
from agent_forge.apply.filesystem_safety import resolve_in_root
from agent_forge.apply.jsonmerge import contains_fragment
from agent_forge.apply.sections import find_section
from agent_forge.config import WorkspaceConfig
from agent_forge.errors import ApplyError, SafetyViolation
from agent_forge.models.capability import CapabilityKind, CapabilityStatus, Platform
from agent_forge.models.project import ProjectProfile
from agent_forge.models.transaction import Transaction
from agent_forge.registry.loader import Registry
from agent_forge.registry.validator import validate_registry
from agent_forge.sources.manager import SourceManager
from agent_forge.sources.provenance import verify_capability_provenance
from agent_forge.storage.transactions import Store
from agent_forge.util import normalize_newlines, parse_frontmatter, read_json, sha256_text


@dataclass
class Finding:
    level: str  # error | warning | info
    scope: str  # registry | provenance | managed | config | adapter | transactions
    message: str


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    checks_run: int = 0

    def add(self, level: str, scope: str, message: str) -> None:
        self.findings.append(Finding(level, scope, message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_workspace(
    ws: WorkspaceConfig, reg: Registry, *, provenance: bool = True
) -> ValidationReport:
    rep = ValidationReport()
    rr = validate_registry(reg)
    rep.checks_run += 1
    for e in rr.errors:
        rep.add("error", "registry", e)
    for w in rr.warnings:
        rep.add("warning", "registry", w)
    for cid, winner, loser in reg.shadowed:
        rep.add(
            "warning",
            "registry",
            f"{cid}: defined in registry '{loser}' and '{winner}'; '{winner}' wins (higher priority)",
        )
    if provenance:
        try:
            mgr = SourceManager(ws)
        except Exception as exc:
            rep.add("warning", "provenance", f"sources manifest unavailable: {exc}")
            mgr = None
        if mgr is not None:
            for cap in reg.capabilities():
                pr = verify_capability_provenance(cap, mgr)
                rep.checks_run += 1
                if cap.source.source_id == "workspace":
                    continue
                if not pr.checkout_present:
                    rep.add(
                        "info",
                        "provenance",
                        f"{cap.id}: source checkout not present; revision not verified",
                    )
                elif pr.revision_present is False:
                    rep.add(
                        "error",
                        "provenance",
                        f"{cap.id}: recorded revision {pr.revision} not found in checkout",
                    )
                if pr.paths_missing:
                    rep.add(
                        "warning",
                        "provenance",
                        f"{cap.id}: upstream paths missing at recorded revision: {', '.join(pr.paths_missing)}",
                    )
    return rep


def validate_target(
    ws: WorkspaceConfig, reg: Registry, store: Store, profile: ProjectProfile
) -> ValidationReport:
    rep = ValidationReport()
    root = Path(profile.canonical_path)
    if profile.managed_manifest_valid is False:
        rep.add("error", "managed", ".agent-forge/managed.json is present but invalid")
    elif profile.managed_manifest_valid is None:
        rep.add("info", "managed", "no managed capabilities (nothing installed by Agent Forge)")
    seen_dest: dict[str, str] = {}
    for rec in profile.managed:
        rep.checks_run += 1
        cap = reg.items.get(rec.capability_id)
        if cap is None:
            rep.add(
                "warning", "managed", f"{rec.capability_id}: not in registry (orphaned install)"
            )
        elif cap.capability.version != rec.version:
            rep.add(
                "info",
                "managed",
                f"{rec.capability_id}: installed {rec.version}, registry {cap.capability.version} (run `upgrade`)",
            )
        if cap is not None and cap.capability.status in (
            CapabilityStatus.DEPRECATED,
            CapabilityStatus.REVOKED,
            CapabilityStatus.REJECTED,
        ):
            status = cap.capability.status
            instead = (
                f"; use {cap.capability.replaced_by} instead" if cap.capability.replaced_by else ""
            )
            rep.add(
                "error" if status == CapabilityStatus.REVOKED else "warning",
                "managed",
                f"{rec.capability_id}: installed but now {status.value} in the registry{instead} "
                f"(`agent-forge remove . {rec.capability_id}`)",
            )
        if cap is not None:
            installed_versions = {m.capability_id: m.version for m in profile.managed}
            for dep in cap.capability.dependency_ids:
                if dep not in installed_versions:
                    rep.add(
                        "error",
                        "managed",
                        f"{rec.capability_id}: dependency {dep} is not installed",
                    )
                elif why := cap.capability.unsatisfied_dependency(dep, installed_versions[dep]):
                    rep.add("error", "managed", why.replace("registry has", "installed is"))
            installed = {m.capability_id for m in profile.managed}
            for conf in cap.capability.conflicts:
                if conf in installed:
                    rep.add(
                        "error", "managed", f"{rec.capability_id}: conflicts with installed {conf}"
                    )
        for rel, expected in rec.files.items():
            if rel in seen_dest and seen_dest[rel] != rec.capability_id:
                rep.add(
                    "error",
                    "managed",
                    f"{rel}: claimed by both {seen_dest[rel]} and {rec.capability_id}",
                )
            seen_dest[rel] = rec.capability_id
            try:
                p = resolve_in_root(root, rel)
            except SafetyViolation as exc:
                rep.add("error", "managed", f"{rec.capability_id}: {exc.message}")
                continue
            if not p.is_file():
                rep.add("error", "managed", f"{rec.capability_id}: managed file missing: {rel}")
                continue
            text = normalize_newlines(p.read_text(encoding="utf-8", errors="replace"))
            if sha256_text(text) != expected:
                rep.add(
                    "warning",
                    "managed",
                    f"{rec.capability_id}: {rel} modified locally (drift); rollback will preserve it",
                )
            platform = _platform_for_path(rel)
            kind = cap.capability.kind if cap else None
            if platform and kind and _is_primary(kind, rel):
                problems = get_adapter(platform).validate_content(kind, rel, text)
                for pr in problems:
                    rep.add("warning", "adapter", f"{rel}: {pr}")
        for rel, fragment in rec.json_merges.items():
            try:
                p = resolve_in_root(root, rel)
                text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
                present = contains_fragment(text, fragment)
            except (SafetyViolation, ApplyError) as exc:
                rep.add("error", "managed", f"{rec.capability_id}: {rel}: {exc.message}")
                continue
            if not present:
                rep.add(
                    "warning",
                    "managed",
                    f"{rec.capability_id}: merged entries no longer present in {rel} (edited?)",
                )
        for rel, sid in rec.sections.items():
            try:
                p = resolve_in_root(root, rel)
                text = (
                    normalize_newlines(p.read_text(encoding="utf-8", errors="replace"))
                    if p.is_file()
                    else ""
                )
                info = find_section(text, sid)
            except (SafetyViolation, ApplyError) as exc:
                rep.add("error", "managed", f"{rec.capability_id}: {rel}: {exc.message}")
                continue
            if info is None:
                rep.add(
                    "warning",
                    "managed",
                    f"{rec.capability_id}: managed section '{sid}' no longer present in {rel}",
                )
            elif info.version != rec.version:
                rep.add(
                    "info",
                    "managed",
                    f"{rec.capability_id}: section '{sid}' in {rel} carries version {info.version}, manifest says {rec.version}",
                )
    _check_config_syntax(root, profile, rep)
    _check_duplicate_skills(profile, rep)
    _check_transactions(store, profile, rep)
    return rep


def _platform_for_path(rel: str) -> Platform | None:
    return platform_owning(rel)


def _is_primary(kind: CapabilityKind, rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name == "SKILL.md" if kind == CapabilityKind.SKILL else name.endswith(".md")


def _check_config_syntax(root: Path, profile: ProjectProfile, rep: ValidationReport) -> None:
    for rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".mcp.json",
        ".codex/hooks.json",
        ".cursor/mcp.json",
        ".gemini/settings.json",
    ):
        p = root / rel
        if p.is_file():
            rep.checks_run += 1
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except ValueError as exc:
                rep.add("error", "config", f"{rel}: invalid JSON: {exc}")
    for a in profile.assets:
        if a.kind == "skill" and a.path.endswith("SKILL.md"):
            p = root / a.path
            if p.is_file():
                fm, _ = parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
                if a.platform in (Platform.CODEX, Platform.COPILOT, Platform.GEMINI) and not (
                    fm.get("name") and fm.get("description")
                ):
                    rep.add(
                        "warning",
                        "adapter",
                        f"{a.path}: {a.platform.value} skills require name and description frontmatter",
                    )


def _check_duplicate_skills(profile: ProjectProfile, rep: ValidationReport) -> None:
    by_name: dict[tuple[str, str], list[str]] = {}
    for a in profile.assets:
        if a.kind in ("skill", "agent", "rule"):
            by_name.setdefault((a.kind, a.name.lower()), []).append(a.path)
    for (kind, name), paths in by_name.items():
        if len(paths) > 1:
            platforms = {p.split("/")[0] for p in paths}
            level = "info" if len(platforms) > 1 else "warning"
            rep.add(level, "managed", f"duplicate {kind} '{name}': " + ", ".join(paths))


def _check_transactions(store: Store, profile: ProjectProfile, rep: ValidationReport) -> None:
    for row in store.list_transactions(profile.canonical_path, limit=100):
        rep.checks_run += 1
        path = Path(row["path"])
        if not path.is_file():
            rep.add("error", "transactions", f"{row['transaction_id']}: record file missing")
            continue
        try:
            tx = Transaction.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            rep.add("error", "transactions", f"{row['transaction_id']}: corrupted record: {exc}")
            continue
        if not tx.integrity_ok():
            rep.add(
                "error", "transactions", f"{tx.transaction_id}: integrity hash mismatch (edited?)"
            )
        reason = store.recovery_reason(tx)
        if reason:
            rep.add(
                "error",
                "transactions",
                f"{tx.transaction_id}: {reason}; run `agent-forge rollback {tx.transaction_id}`",
            )
        for op in tx.operations:
            if op.backup and not valid_backup_name(op.backup):
                rep.add(
                    "error",
                    "transactions",
                    f"{tx.transaction_id}: invalid backup reference for {op.path} (tampered record?)",
                )
                continue
            if (
                op.applied
                and op.backup
                and not store.backup_dir(tx.transaction_id).joinpath(op.backup).is_file()
            ):
                rep.add(
                    "warning", "transactions", f"{tx.transaction_id}: backup missing for {op.path}"
                )
