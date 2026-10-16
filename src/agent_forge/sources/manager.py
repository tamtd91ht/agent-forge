"""Source manager: approved upstream repositories, their checkouts and sync status.

Cloning is *not* installing. Nothing from a checkout is executed. Checkout content is
untrusted until a reviewer curates it into the registry.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_forge.config import WorkspaceConfig
from agent_forge.errors import SourceError
from agent_forge.util import now_iso, read_json, read_yaml, write_json

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_URL_RE = re.compile(r"^(https://|git@|ssh://)")


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    url: str
    license: str
    default_branch: str = "main"
    pinned_revision: str | None = Field(default=None, description="Reviewer-approved revision")
    trust: str = Field(default="untrusted", description="untrusted | reviewed")
    homepage: str | None = None
    notes: list[str] = Field(default_factory=list)
    redistribution_notes: str | None = None

    def validate_url(self) -> None:
        if not _URL_RE.match(self.url):
            raise SourceError(f"source {self.id}: unsupported url scheme: {self.url}")


class SourcesManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    sources: list[SourceSpec]


@dataclass
class SourceStatus:
    spec: SourceSpec
    checkout: Path
    present: bool
    head: str | None = None
    head_date: str | None = None
    remote_url: str | None = None
    remote_matches: bool | None = None
    dirty: bool | None = None
    recorded_revision: str | None = None
    upstream_head: str | None = None
    behind: int | None = None
    changed_files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.spec.id,
            "name": self.spec.name,
            "url": self.spec.url,
            "license": self.spec.license,
            "checkout": str(self.checkout),
            "present": self.present,
            "head": self.head,
            "head_date": self.head_date,
            "remote_matches": self.remote_matches,
            "dirty": self.dirty,
            "recorded_revision": self.recorded_revision,
            "pinned_revision": self.spec.pinned_revision,
            "upstream_head": self.upstream_head,
            "behind": self.behind,
            "changed_files": self.changed_files,
            "problems": self.problems,
        }


def _git(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceError("git is not available on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError(f"git {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        raise SourceError(
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


class SourceManager:
    def __init__(self, ws: WorkspaceConfig) -> None:
        self.ws = ws
        self.manifest = self._load_manifest()
        self.state_path = ws.cache_dir / "sources-state.json"

    def _load_manifest(self) -> SourcesManifest:
        path = self.ws.sources_manifest
        if not path.is_file():
            raise SourceError(f"sources manifest not found: {path}", hint="Run `agent-forge init`.")
        try:
            data = read_yaml(path)
            manifest = SourcesManifest.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise SourceError(f"{path}: invalid sources manifest: {exc}") from exc
        ids = [s.id for s in manifest.sources]
        if len(ids) != len(set(ids)):
            raise SourceError(f"{path}: duplicate source ids")
        for s in manifest.sources:
            s.validate_url()
        return manifest

    def _state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            try:
                data = read_json(self.state_path)
                if isinstance(data, dict):
                    return data
            except ValueError:
                pass
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        write_json(self.state_path, state)

    def checkout_dir(self, spec: SourceSpec) -> Path:
        return self.ws.checkouts_dir / spec.id

    def get(self, source_id: str) -> SourceSpec:
        for s in self.manifest.sources:
            if s.id == source_id:
                return s
        raise SourceError(f"unknown source: {source_id}")

    # ---- status --------------------------------------------------------------------------

    def status(self, spec: SourceSpec, *, fetch: bool = False) -> SourceStatus:
        checkout = self.checkout_dir(spec)
        st = SourceStatus(spec=spec, checkout=checkout, present=(checkout / ".git").exists())
        st.recorded_revision = self._state().get(spec.id, {}).get("revision")
        if not st.present:
            return st
        try:
            st.head = _git(["rev-parse", "HEAD"], checkout)
            st.head_date = _git(["log", "-1", "--format=%cI"], checkout)
            st.remote_url = _git(["remote", "get-url", "origin"], checkout)
            st.remote_matches = _normalize_url(st.remote_url) == _normalize_url(spec.url)
            st.dirty = bool(_git(["status", "--porcelain", "--untracked-files=no"], checkout))
            if fetch:
                _git(["fetch", "--quiet", "origin", spec.default_branch], checkout, timeout=600)
                st.upstream_head = _git(["rev-parse", "FETCH_HEAD"], checkout)
                if st.upstream_head != st.head:
                    st.behind = int(
                        _git(["rev-list", "--count", f"HEAD..{st.upstream_head}"], checkout) or 0
                    )
                    diff = _git(["diff", "--name-only", st.head, st.upstream_head], checkout)
                    st.changed_files = [line for line in diff.splitlines() if line]
                else:
                    st.behind = 0
        except SourceError as exc:
            st.problems.append(exc.message)
        if st.remote_matches is False:
            st.problems.append(
                f"checkout remote {st.remote_url} does not match manifest url {spec.url}"
            )
        return st

    def list_status(self, *, fetch: bool = False) -> list[SourceStatus]:
        return [self.status(s, fetch=fetch) for s in self.manifest.sources]

    # ---- clone / sync --------------------------------------------------------------------

    def clone(self, spec: SourceSpec) -> SourceStatus:
        checkout = self.checkout_dir(spec)
        if (checkout / ".git").exists():
            st = self.status(spec)
            if st.recorded_revision is None and st.head:
                self.record(spec, st.head)
                st.recorded_revision = st.head
            return st
        if checkout.exists() and any(checkout.iterdir()):
            raise SourceError(
                f"checkout directory {checkout} exists and is not empty; refusing to clone into it"
            )
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _git(
            ["clone", "--quiet", "--branch", spec.default_branch, "--", spec.url, str(checkout)],
            timeout=900,
        )
        if spec.pinned_revision:
            _git(["checkout", "--quiet", "--detach", spec.pinned_revision], checkout)
        st = self.status(spec)
        self.record(spec, st.head)
        return st

    def record(self, spec: SourceSpec, revision: str | None) -> None:
        if revision and not _SHA_RE.match(revision):
            raise SourceError(f"refusing to record non-SHA revision {revision!r}")
        state = self._state()
        state[spec.id] = {"revision": revision, "recorded_at": now_iso(), "url": spec.url}
        self._save_state(state)

    def sync(self, spec: SourceSpec, *, update: bool = False) -> SourceStatus:
        """Fetch upstream and report changes. Only move the checkout when `update=True`."""
        st = self.status(spec, fetch=True)
        if not st.present:
            raise SourceError(
                f"source {spec.id} is not cloned", hint="Run `agent-forge sources clone`."
            )
        if update and st.upstream_head and st.upstream_head != st.head:
            if st.dirty:
                raise SourceError(
                    f"source {spec.id} checkout has local modifications; refusing to update"
                )
            if spec.pinned_revision:
                raise SourceError(
                    f"source {spec.id} is pinned to {spec.pinned_revision}; update the manifest first"
                )
            _git(["checkout", "--quiet", "--detach", st.upstream_head], st.checkout)
            st = self.status(spec, fetch=False)
            self.record(spec, st.head)
        return st


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    u = url.strip().rstrip("/")
    u = u.removesuffix(".git")
    return u.lower()
