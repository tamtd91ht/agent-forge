"""Bounded, read-only filesystem walker.

Guarantees: never follows symlinks, never reads files above `max_file_bytes`, never descends
into dependency/build directories, never reads secret-looking files, and stops after
`max_files` entries. Paths with spaces and non-ASCII characters are handled via pathlib.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge.models.project import ScanStats

EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn",
        "node_modules", "bower_components", ".pnpm-store", ".yarn",
        ".venv", "venv", "env", ".tox", ".nox", "__pycache__", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".eggs", "site-packages",
        "dist", "build", "out", "target", ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache",
        ".parcel-cache", "coverage", ".nyc_output", ".gradle", ".idea", ".vs", "bin", "obj",
        "vendor", "Pods", "DerivedData", ".dart_tool", ".terraform", ".serverless",
        ".agent-forge-backup",
    }
)  # fmt: skip

SECRET_FILE_NAMES: frozenset[str] = frozenset(
    {".env", ".envrc", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa"}
)
SECRET_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret")
SECRET_PREFIXES: tuple[str, ...] = (".env.", "credentials", "secrets")

BINARY_SUFFIXES: tuple[str, ...] = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".tgz", ".bz2",
    ".xz", ".7z", ".rar", ".jar", ".war", ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".class",
    ".pyc", ".wasm", ".mp3", ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".otf", ".db", ".sqlite",
)  # fmt: skip


_REPARSE = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_reparse_point(entry: os.DirEntry) -> bool:
    """Windows junctions/mount points are reparse points but not symlinks for Python."""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def looks_secret(name: str) -> bool:
    lower = name.lower()
    if lower in (".env.example", ".env.sample", ".env.template", ".env.dist"):
        return False
    return (
        lower in SECRET_FILE_NAMES
        or lower.endswith(SECRET_SUFFIXES)
        or lower.startswith(SECRET_PREFIXES)
        or lower.startswith(".env")
    )


@dataclass
class WalkEntry:
    path: Path
    rel: str
    size: int


@dataclass
class Walker:
    root: Path
    max_files: int = 20_000
    max_depth: int = 12
    max_file_bytes: int = 1_048_576
    stats: ScanStats = field(default_factory=ScanStats)
    sensitive: list[str] = field(default_factory=list)
    _index: dict[str, WalkEntry] = field(default_factory=dict)
    _walked: bool = False

    def __post_init__(self) -> None:
        self.stats.limits = {
            "max_files": self.max_files,
            "max_depth": self.max_depth,
            "max_file_bytes": self.max_file_bytes,
        }

    # ---- walking -------------------------------------------------------------------------

    def walk(self) -> Iterator[WalkEntry]:
        if self._walked:
            yield from self._index.values()
            return
        self._walked = True
        excluded: set[str] = set()
        for entry in self._walk_dir(self.root, 0, excluded):
            self._index[entry.rel] = entry
            yield entry
        self.stats.excluded_dirs = sorted(excluded)

    def _walk_dir(self, directory: Path, depth: int, excluded: set[str]) -> Iterator[WalkEntry]:
        if depth > self.max_depth:
            self.stats.truncated = True
            return
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: e.name)
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            return
        self.stats.dirs_seen += 1
        for e in entries:
            if self.stats.files_seen >= self.max_files:
                self.stats.truncated = True
                return
            try:
                is_symlink = e.is_symlink() or _is_reparse_point(e)
            except OSError:
                continue
            if is_symlink:
                # symlinks AND Windows junctions/reparse points are never followed
                self.stats.skipped_symlinks += 1
                continue
            rel = os.path.relpath(e.path, self.root).replace("\\", "/")
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name in EXCLUDED_DIR_NAMES:
                        excluded.add(rel)
                        continue
                    yield from self._walk_dir(Path(e.path), depth + 1, excluded)
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            self.stats.files_seen += 1
            if looks_secret(e.name):
                self.sensitive.append(rel)
                continue
            yield WalkEntry(path=Path(e.path), rel=rel, size=st.st_size)

    # ---- lookups -------------------------------------------------------------------------

    def ensure_walked(self) -> None:
        if not self._walked:
            for _ in self.walk():
                pass

    def exists(self, rel: str) -> bool:
        self.ensure_walked()
        return rel in self._index

    def entries(self) -> list[WalkEntry]:
        self.ensure_walked()
        return list(self._index.values())

    def find_by_name(self, name: str, *, max_depth: int | None = None) -> list[WalkEntry]:
        self.ensure_walked()
        out = []
        for rel, entry in self._index.items():
            if rel.rsplit("/", 1)[-1] == name and (
                max_depth is None or rel.count("/") <= max_depth
            ):
                out.append(entry)
        return out

    def find_by_suffix(self, suffixes: tuple[str, ...], limit: int = 5000) -> list[WalkEntry]:
        self.ensure_walked()
        out = []
        for rel, entry in self._index.items():
            if rel.lower().endswith(suffixes):
                out.append(entry)
                if len(out) >= limit:
                    break
        return out

    def under(self, prefix: str) -> list[WalkEntry]:
        self.ensure_walked()
        p = prefix.rstrip("/") + "/"
        return [e for rel, e in self._index.items() if rel.startswith(p)]

    # ---- bounded reads -------------------------------------------------------------------

    def read_text(self, rel: str) -> str | None:
        """Read a text file (bounded). Returns None for missing, oversized, or binary files."""
        self.ensure_walked()
        entry = self._index.get(rel)
        if entry is None:
            return None
        if entry.size > self.max_file_bytes:
            self.stats.skipped_large += 1
            return None
        if entry.rel.lower().endswith(BINARY_SUFFIXES):
            return None
        try:
            data = entry.path.read_bytes()
        except OSError:
            return None
        if b"\0" in data[:8192]:
            return None
        self.stats.files_read += 1
        return data.decode("utf-8", errors="replace")

    def read_bytes(self, rel: str) -> bytes | None:
        self.ensure_walked()
        entry = self._index.get(rel)
        if entry is None or entry.size > self.max_file_bytes:
            return None
        try:
            self.stats.files_read += 1
            return entry.path.read_bytes()
        except OSError:
            return None
