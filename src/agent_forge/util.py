"""Small shared helpers: hashing, ids, timestamps, atomic writes, frontmatter parsing."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(3)}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """Deterministic digest of a directory tree (relative paths + file hashes).

    Files are visited in code-point order of their POSIX relative path, never in `Path`
    order: `WindowsPath` compares case-insensitively and `PosixPath` does not, so sorting
    Path objects gave a different digest on Windows than on Linux/macOS for any tree with
    an upper-case file next to a lower-case one (the v0.2.0-v0.3.0 pins).
    """
    h = hashlib.sha256()
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    for p in sorted(files, key=lambda q: q.relative_to(root).as_posix()):
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_file(p).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory and os.replace, so readers never see partial content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter dict, body). Invalid YAML yields ({}, text)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        # Not valid YAML, yet the tools read it: a description such as
        # "Use when … Triggered by: x, y" is the common case. Keep the top-level
        # `key: value` lines so name / description are still known.
        data = _lenient_frontmatter(m.group(1))
    if not isinstance(data, dict):
        return {}, text
    return data, text[m.end() :]


def _lenient_frontmatter(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in block.splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            out[km.group(1)] = km.group(2).strip().strip("'\"")
    return out


def markdown_headings(text: str, max_level: int = 3) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m and len(m.group(1)) <= max_level:
            out.append(m.group(2))
    return out


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def to_posix(path: str | Path) -> str:
    return str(path).replace("\\", "/")
