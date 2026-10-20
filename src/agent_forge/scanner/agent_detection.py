"""Agent-platform detection and inventory, plus validation of the managed manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from agent_forge import MANAGED_MANIFEST_VERSION
from agent_forge.adapters import all_adapters
from agent_forge.apply.filesystem_safety import validate_relative_path
from agent_forge.errors import SafetyViolation
from agent_forge.models.project import AgentAsset, ManagedCapabilityRecord, PlatformDetection
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import sha256_text

MANAGED_DIR = ".agent-forge"
MANAGED_MANIFEST = f"{MANAGED_DIR}/managed.json"


@dataclass
class AgentInventory:
    platforms: list[PlatformDetection] = field(default_factory=list)
    assets: list[AgentAsset] = field(default_factory=list)
    managed: list[ManagedCapabilityRecord] = field(default_factory=list)
    managed_manifest_valid: bool | None = None
    warnings: list[str] = field(default_factory=list)


def detect_agents(walker: Walker) -> AgentInventory:
    inv = AgentInventory()
    for adapter in all_adapters():
        det = adapter.detect(walker)
        if det is not None:
            inv.platforms.append(det)
        inv.assets.extend(adapter.collect_assets(walker))
    # Generic instruction files other tools read (recorded, not owned by any adapter)
    for name in (".cursorrules", ".windsurfrules", ".clinerules", ".junie/guidelines.md"):
        if walker.exists(name):
            text = walker.read_text(name) or ""
            inv.assets.append(
                AgentAsset(
                    platform=None,
                    kind="instruction",
                    name=name,
                    path=name,
                    sha256=sha256_text(text),
                )
            )
    _load_managed(walker, inv)
    _mark_managed_assets(inv)
    return inv


def parse_managed_manifest(text: str) -> tuple[list[ManagedCapabilityRecord], list[str]]:
    """Validate a managed.json document. Returns (records, problems)."""
    problems: list[str] = []
    try:
        data = json.loads(text)
    except ValueError as exc:
        return [], [f"managed manifest is not valid JSON: {exc}"]
    if not isinstance(data, dict):
        return [], ["managed manifest must be a JSON object"]
    if str(data.get("version")) != MANAGED_MANIFEST_VERSION:
        problems.append(f"managed manifest version {data.get('version')!r} is not supported")
    caps = data.get("capabilities")
    if not isinstance(caps, list):
        return [], [*problems, "managed manifest has no 'capabilities' list"]
    records: list[ManagedCapabilityRecord] = []
    seen: set[str] = set()
    for item in caps:
        try:
            rec = ManagedCapabilityRecord.model_validate(item)
        except ValidationError as exc:
            problems.append(f"invalid managed record: {exc.errors()[0]['msg']}")
            continue
        if rec.capability_id in seen:
            problems.append(f"duplicate managed record for {rec.capability_id}")
            continue
        for rel in [*rec.files, *rec.sections, *rec.json_merges]:
            try:
                validate_relative_path(rel)
            except SafetyViolation:
                problems.append(f"managed record {rec.capability_id} lists unsafe path {rel!r}")
                break
        else:
            seen.add(rec.capability_id)
            records.append(rec)
    return records, problems


def _load_managed(walker: Walker, inv: AgentInventory) -> None:
    if not walker.exists(MANAGED_MANIFEST):
        inv.managed_manifest_valid = None
        return
    text = walker.read_text(MANAGED_MANIFEST)
    if text is None:
        inv.managed_manifest_valid = False
        inv.warnings.append(f"{MANAGED_MANIFEST} could not be read (too large or binary)")
        return
    records, problems = parse_managed_manifest(text)
    inv.managed_manifest_valid = not problems
    inv.warnings.extend(f"{MANAGED_MANIFEST}: {p}" for p in problems)
    for rec in records:
        drift: list[str] = []
        for rel, expected in rec.files.items():
            current = walker.read_text(rel)
            if current is None:
                drift.append(f"{rel} (missing)")
            elif sha256_text(current) != expected:
                drift.append(rel)
        rec.drift = drift
        inv.managed.append(rec)


def _mark_managed_assets(inv: AgentInventory) -> None:
    owners: dict[str, str] = {}
    for rec in inv.managed:
        for rel in rec.files:
            owners[rel] = rec.capability_id
        for rel in rec.sections:
            owners.setdefault(rel, rec.capability_id)
    for asset in inv.assets:
        if asset.path in owners and asset.kind != "instruction":
            asset.managed_by = owners[asset.path]
