from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_forge.apply.filesystem_safety import resolve_in_root, validate_relative_path
from agent_forge.errors import SafetyViolation
from agent_forge.util import atomic_write_text
from tests.conftest import can_symlink

pytestmark = pytest.mark.security


@pytest.mark.parametrize(
    "bad",
    [
        "../x.md",
        "a/../../x.md",
        "/etc/passwd",
        "C:/Windows/system.ini",
        "C:\\Windows\\x",
        "\\\\server\\share\\x",
        "a/./../../b",
        "",
        " x.md",
        "CON",
        "dir/NUL.txt",
        "bad\x00name",
        "trailing. ",
        "a/b<c",
    ],
)
def test_rejects_unsafe_relative_paths(bad: str) -> None:
    with pytest.raises(SafetyViolation):
        validate_relative_path(bad)


@pytest.mark.parametrize(
    "ok", [".claude/skills/x/SKILL.md", "CLAUDE.md", "a/b/c.md", "ünï cødé/file.md", "./x.md"]
)
def test_accepts_normal_paths(ok: str) -> None:
    assert validate_relative_path(ok)


def test_resolve_stays_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    p = resolve_in_root(root, ".claude/skills/x/SKILL.md")
    assert root.resolve() in p.parents
    with pytest.raises(SafetyViolation):
        resolve_in_root(root, "../escape.md")


def test_symlink_escape_is_blocked(tmp_path: Path) -> None:
    if not can_symlink(tmp_path):
        pytest.skip("symlinks not permitted in this environment")
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / ".claude", target_is_directory=True)
    with pytest.raises(SafetyViolation, match="symlink"):
        resolve_in_root(root, ".claude/skills/x/SKILL.md")
    (root / "real.md").write_text("x", encoding="utf-8")
    os.symlink(root / "real.md", root / "link.md")
    with pytest.raises(SafetyViolation, match="symlink"):
        resolve_in_root(root, "link.md")


def test_atomic_write_leaves_no_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".out.md.")]
    assert not leftovers


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=1, max_size=40))
def test_fuzzed_paths_never_escape(tmp_path_factory, s: str) -> None:
    root = tmp_path_factory.mktemp("fuzz")
    try:
        p = resolve_in_root(root, s)
    except SafetyViolation:
        return
    assert root.resolve() in p.parents
