"""Workspace discovery and configuration.

A *workspace* is a directory containing `agent-forge.yaml`. It owns:
  registry/   curated capability manifests + assets (versioned, human-reviewed)
  sources/    sources.yaml manifest and git checkouts of upstream repositories
  state/      runtime state: plans, transactions, reports, cache, sqlite index

Resolution order: explicit --workspace > $AGENT_FORGE_HOME > walk up from cwd > ~/.agent-forge.
The workspace is deliberately independent from any target project.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_forge.errors import WorkspaceError

WORKSPACE_MARKER = "agent-forge.yaml"
ENV_HOME = "AGENT_FORGE_HOME"
DEFAULT_HOME_DIRNAME = ".agent-forge"


@dataclass(frozen=True)
class WorkspaceConfig:
    """Resolved, validated workspace configuration (paths are absolute)."""

    root: Path
    registry_dir: Path
    sources_dir: Path
    checkouts_dir: Path
    state_dir: Path
    raw: dict[str, Any] = field(default_factory=dict)
    # Additional registries in priority order (first wins on a duplicate id); the core
    # `registry_dir` is always the last, lowest-priority layer. Configured as
    #   registries:
    #     - { name: team, path: /srv/agent-forge-team-registry }
    extra_registries: tuple[tuple[str, Path], ...] = ()

    @property
    def registry_layers(self) -> list[tuple[str, Path]]:
        """(name, directory) for every registry, highest priority first; core is last."""
        return [*self.extra_registries, ("core", self.registry_dir)]

    @property
    def marker(self) -> Path:
        return self.root / WORKSPACE_MARKER

    @property
    def plans_dir(self) -> Path:
        return self.state_dir / "plans"

    @property
    def transactions_dir(self) -> Path:
        return self.state_dir / "transactions"

    @property
    def reports_dir(self) -> Path:
        return self.state_dir / "reports"

    @property
    def cache_dir(self) -> Path:
        return self.state_dir / "cache"

    @property
    def database_path(self) -> Path:
        return self.state_dir / "agent-forge.sqlite3"

    @property
    def audit_path(self) -> Path:
        return self.state_dir / "audit.jsonl"

    @property
    def sources_manifest(self) -> Path:
        return self.sources_dir / "sources.yaml"

    @property
    def capabilities_dir(self) -> Path:
        return self.registry_dir / "capabilities"

    @property
    def schema_dir(self) -> Path:
        return self.registry_dir / "schema"

    @property
    def policies_dir(self) -> Path:
        return self.registry_dir / "policies"

    @property
    def scan_limits(self) -> dict[str, int]:
        scan = self.raw.get("scan") or {}
        return {**DEFAULT_CONFIG["scan"], **scan}

    def ensure_state_dirs(self) -> None:
        for d in (
            self.state_dir,
            self.plans_dir,
            self.transactions_dir,
            self.reports_dir,
            self.cache_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "registry_dir": "registry",
    "sources_dir": "sources",
    "checkouts_dir": "sources/checkouts",
    "state_dir": "state",
    "scan": {
        "max_file_bytes": 1_048_576,
        "max_files": 20_000,
        "max_depth": 12,
    },
}


def default_home() -> Path:
    return Path.home() / DEFAULT_HOME_DIRNAME


def _walk_up_for_marker(start: Path) -> Path | None:
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / WORKSPACE_MARKER).is_file():
            return candidate
    return None


def locate_workspace(explicit: Path | None = None, *, cwd: Path | None = None) -> Path | None:
    """Return the workspace root directory or None if none can be found. Creates nothing."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser().resolve()
    found = _walk_up_for_marker(cwd or Path.cwd())
    if found is not None:
        return found
    home = default_home()
    if (home / WORKSPACE_MARKER).is_file():
        return home
    return None


def _resolve_dir(root: Path, value: Any, key: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkspaceError(f"agent-forge.yaml: '{key}' must be a non-empty string")
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (root / p).resolve()


def load_workspace(root: Path) -> WorkspaceConfig:
    """Load and validate `agent-forge.yaml` under `root`."""
    root = root.expanduser().resolve()
    marker = root / WORKSPACE_MARKER
    if not marker.is_file():
        raise WorkspaceError(
            f"No Agent Forge workspace at {root} (missing {WORKSPACE_MARKER}).",
            hint="Run `agent-forge init` here, pass --workspace PATH, or set AGENT_FORGE_HOME.",
        )
    try:
        raw = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"Cannot parse {marker}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkspaceError(f"{marker} must contain a mapping at top level")
    merged: dict[str, Any] = {**DEFAULT_CONFIG, **raw}
    return WorkspaceConfig(
        root=root,
        registry_dir=_resolve_dir(root, merged["registry_dir"], "registry_dir"),
        sources_dir=_resolve_dir(root, merged["sources_dir"], "sources_dir"),
        checkouts_dir=_resolve_dir(root, merged["checkouts_dir"], "checkouts_dir"),
        state_dir=_resolve_dir(root, merged["state_dir"], "state_dir"),
        raw=merged,
        extra_registries=_extra_registries(root, merged.get("registries")),
    )


def _extra_registries(root: Path, value: Any) -> tuple[tuple[str, Path], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WorkspaceError("agent-forge.yaml: 'registries' must be a list")
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for i, entry in enumerate(value):
        if isinstance(entry, str):
            entry = {"name": f"registry{i + 1}", "path": entry}
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise WorkspaceError(
                f"agent-forge.yaml: registries[{i}] must be a path or {{name, path}}"
            )
        name = str(entry.get("name") or f"registry{i + 1}")
        if name == "core" or name in seen:
            raise WorkspaceError(
                f"agent-forge.yaml: registry name {name!r} is reserved or repeated"
            )
        seen.add(name)
        out.append((name, _resolve_dir(root, entry["path"], f"registries[{i}].path")))
    return tuple(out)


def require_workspace(explicit: Path | None = None) -> WorkspaceConfig:
    root = locate_workspace(explicit)
    if root is None:
        raise WorkspaceError(
            "No Agent Forge workspace found.",
            hint="Run `agent-forge init` in the directory you want to use as the workspace.",
        )
    return load_workspace(root)
