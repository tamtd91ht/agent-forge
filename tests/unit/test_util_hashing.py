"""`sha256_tree` must give the same digest on every OS: registry pins, plan registry digests
and approvals all depend on it (v0.2.0-v0.3.0 pinned Windows-order digests, see 0.3.1)."""

from __future__ import annotations

from pathlib import Path

from agent_forge.util import sha256_tree

# Computed independently of Path ordering (POSIX relative paths in code-point order, each
# followed by NUL, the file's sha256 hex and a newline). CI runs this on Windows, Linux and
# macOS, so any ordering difference between the platforms fails here first.
KNOWN_DIGEST = "7d4dfc3f3f774682058052c43788dcda17e9e4b49da58969cea067af6d2e0ab6"


def test_sha256_tree_is_independent_of_os_path_ordering(tmp_path: Path) -> None:
    # Upper-case next to lower-case: the case where WindowsPath and PosixPath sort differently.
    (tmp_path / "LICENSE.txt").write_text("l", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "SKILL.md").write_text("s", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("b", encoding="utf-8")
    assert sha256_tree(tmp_path) == KNOWN_DIGEST


def test_sha256_tree_changes_when_a_file_is_renamed_by_case(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    before = sha256_tree(tmp_path)
    (tmp_path / "a.md").rename(tmp_path / "A.md")
    assert sha256_tree(tmp_path) != before


def test_sha256_tree_ignores_directories_and_only_hashes_files(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "x.md").write_text("x", encoding="utf-8")
    only_file = sha256_tree(tmp_path)
    (tmp_path / "another-empty").mkdir()
    assert sha256_tree(tmp_path) == only_file
