"""Load capability manifests from `<registry>/capabilities/<id>/capability.yaml`."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from agent_forge.errors import RegistryError
from agent_forge.models.capability import Capability, CapabilityStatus
from agent_forge.util import normalize_newlines, read_yaml, sha256_text, sha256_tree

MANIFEST_NAME = "capability.yaml"
ASSETS_DIRNAME = "assets"


@dataclass
class LoadedCapability:
    capability: Capability
    directory: Path
    assets_dir: Path
    content_digest: str
    assets_digest: str = ""
    registry: str = "core"  # name of the registry layer this entry came from

    @property
    def id(self) -> str:
        return self.capability.id


@dataclass
class Registry:
    root: Path
    items: dict[str, LoadedCapability] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    # (name, directory) of every layer that was merged, highest priority first
    layers: list[tuple[str, Path]] = field(default_factory=list)
    # ids defined in more than one layer: (id, winning layer, shadowed layer)
    shadowed: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def digest(self) -> str:
        """Digest over every manifest, asset and shipped policy, stable across machines."""
        h = hashlib.sha256()
        for cid in sorted(self.items):
            lc = self.items[cid]
            h.update(cid.encode("utf-8"))
            h.update(b"=")
            h.update(lc.content_digest.encode("ascii"))
            if lc.registry != "core":  # a team override is a different registry state
                h.update(b"@")
                h.update(lc.registry.encode("utf-8"))
            h.update(b"\n")
        policies = self.root / "policies"
        if policies.is_dir():
            for p in sorted(policies.rglob("*")):
                if p.is_file() and not p.is_symlink():
                    text = normalize_newlines(p.read_text(encoding="utf-8", errors="replace"))
                    h.update(f"policies/{p.relative_to(policies).as_posix()}=".encode())
                    h.update(sha256_text(text).encode("ascii"))
                    h.update(b"\n")
        return h.hexdigest()

    def get(self, capability_id: str) -> LoadedCapability:
        try:
            return self.items[capability_id]
        except KeyError:
            raise RegistryError(f"unknown capability: {capability_id}") from None

    def capabilities(self) -> list[Capability]:
        return [lc.capability for _, lc in sorted(self.items.items())]

    def curated(self) -> list[Capability]:
        return [c for c in self.capabilities() if c.status == CapabilityStatus.CURATED]


def _load_one(directory: Path) -> LoadedCapability:
    manifest = directory / MANIFEST_NAME
    try:
        raw = read_yaml(manifest)
    except Exception as exc:  # yaml / io errors
        raise RegistryError(f"{manifest}: cannot read manifest: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"{manifest}: manifest must be a mapping")
    try:
        cap = Capability.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise RegistryError(f"{manifest}: invalid manifest: {details}") from exc
    if cap.id != directory.name:
        raise RegistryError(
            f"{manifest}: id {cap.id!r} must match its directory name {directory.name!r}"
        )
    assets_dir = directory / ASSETS_DIRNAME
    return LoadedCapability(
        capability=cap,
        directory=directory,
        assets_dir=assets_dir,
        content_digest=sha256_tree(directory),
        assets_digest=sha256_tree(assets_dir) if assets_dir.is_dir() else sha256_text(""),
    )


def load_registry(registry_dir: Path, *, strict: bool = True) -> Registry:
    """Load all capabilities. With strict=False, invalid manifests are reported in `problems`."""
    caps_dir = registry_dir / "capabilities"
    reg = Registry(root=registry_dir)
    if not caps_dir.is_dir():
        if strict:
            raise RegistryError(f"registry has no capabilities directory: {caps_dir}")
        reg.problems.append(f"missing {caps_dir}")
        return reg
    for directory in sorted(p for p in caps_dir.iterdir() if p.is_dir()):
        if directory.name.startswith((".", "_")):
            continue
        if not (directory / MANIFEST_NAME).is_file():
            msg = f"{directory}: no {MANIFEST_NAME}"
            if strict:
                raise RegistryError(msg)
            reg.problems.append(msg)
            continue
        try:
            lc = _load_one(directory)
        except RegistryError as exc:
            if strict:
                raise
            reg.problems.append(exc.message)
            continue
        reg.items[lc.id] = lc
    return reg


def load_registries(layers: list[tuple[str, Path]], *, strict: bool = True) -> Registry:
    """Merge several registries, highest priority first; the last layer is the core.

    A capability id present in two layers resolves to the first one and is recorded in
    `shadowed` so `validate`/`doctor` can show it. The core's `policies/` are the only
    shipped policies: extra registries contribute capabilities, not policy.
    """
    if not layers:
        raise RegistryError("no registry configured")
    _, core_dir = layers[-1]
    merged = Registry(root=core_dir, layers=list(layers))
    origin: dict[str, str] = {}
    for name, directory in layers:
        reg = load_registry(directory, strict=strict)
        merged.problems.extend(f"[{name}] {p}" for p in reg.problems)
        for cid, lc in reg.items.items():
            lc.registry = name
            if cid in merged.items:
                merged.shadowed.append((cid, origin[cid], name))
                continue
            merged.items[cid] = lc
            origin[cid] = name
    return merged
