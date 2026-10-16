"""Filesystem boundary enforcement.

Every path Agent Forge writes inside a target project goes through `resolve_in_root`.
It rejects absolute paths, traversal, drive letters, reserved names and any symlink in the
chain (existing components are checked with `lstat`, never followed), and finally verifies
that the resolved path is inside the resolved root.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from agent_forge.errors import SafetyViolation

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip
_BAD_CHARS = re.compile(r"[\x00-\x1f<>:\"|?*]")


def validate_relative_path(rel: str) -> list[str]:
    """Return the validated path components of a relative, POSIX-style path."""
    if not rel or rel.strip() != rel:
        raise SafetyViolation(f"empty or whitespace-padded path: {rel!r}")
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or norm.startswith("//"):
        raise SafetyViolation(f"absolute path not allowed: {rel!r}")
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts:
        raise SafetyViolation(f"path resolves to the root itself: {rel!r}")
    for part in parts:
        if part == "..":
            raise SafetyViolation(f"path traversal not allowed: {rel!r}")
        if _BAD_CHARS.search(part):
            raise SafetyViolation(f"illegal character in path component {part!r}")
        if part.split(".")[0].upper() in _WINDOWS_RESERVED:
            raise SafetyViolation(f"reserved device name in path: {part!r}")
        if part.endswith((" ", ".")):
            raise SafetyViolation(f"path component may not end with space or dot: {part!r}")
    return parts


def resolve_in_root(root: Path, rel: str, *, allow_missing: bool = True) -> Path:
    """Resolve `rel` under `root` safely.

    - `root` must exist and is resolved (symlinked roots are allowed; what matters is that
      nothing *inside* escapes it).
    - No existing component may be a symlink (checked with lstat, not followed).
    - The final path must be inside the resolved root.
    """
    real_root = root.resolve(strict=True)
    parts = validate_relative_path(rel)
    cur = real_root
    for part in parts:
        cur = cur / part
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            if not allow_missing:
                raise SafetyViolation(f"path does not exist: {rel!r}") from None
            # remaining components do not exist yet; nothing more to check for symlinks
            continue
        except OSError as exc:
            raise SafetyViolation(f"cannot stat {cur}: {exc}") from exc
        if cur.is_symlink() or _is_reparse_point(st):
            raise SafetyViolation(f"symlink or reparse point in path: {cur.relative_to(real_root)}")
    final = cur
    try:
        final.relative_to(real_root)
    except ValueError:
        raise SafetyViolation(f"path escapes target root: {rel!r}") from None
    return final


def _is_reparse_point(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(os, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse)


def is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def assert_regular_file_or_missing(path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise SafetyViolation(f"refusing to operate on symlink: {path}")
        if not path.is_file():
            raise SafetyViolation(f"destination exists and is not a regular file: {path}")
