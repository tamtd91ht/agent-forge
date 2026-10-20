"""Windows junctions are reparse points, not symlinks for Python: they must still be refused.

Junctions can be created without administrator rights, which is exactly why a malicious
target project could use one to point `.claude/` at a directory outside the project.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent_forge.apply.filesystem_safety import resolve_in_root, safe_write_bytes
from agent_forge.errors import SafetyViolation
from agent_forge.scanner.filesystem import Walker

pytestmark = [
    pytest.mark.security,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions"),
]


def _junction(link: Path, target: Path) -> bool:
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
    )
    return proc.returncode == 0 and link.exists()


def test_walker_skips_junctions(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("outside", encoding="utf-8")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.md").write_text("in", encoding="utf-8")
    if not _junction(root / "jlink", outside):
        pytest.skip("cannot create junction here")
    w = Walker(root)
    rels = {e.rel for e in w.walk()}
    assert rels == {"ok.md"}
    assert w.stats.skipped_symlinks == 1


def test_resolve_refuses_junction_component(tmp_path: Path) -> None:
    outside = tmp_path / "outside2"
    outside.mkdir()
    root = tmp_path / "proj2"
    root.mkdir()
    if not _junction(root / ".claude", outside):
        pytest.skip("cannot create junction here")
    with pytest.raises(SafetyViolation, match="symlink or reparse point"):
        resolve_in_root(root, ".claude/skills/x/SKILL.md")


def test_link_created_after_preflight_is_refused(tmp_path: Path) -> None:
    """A directory swapped for a junction between planning and writing is caught at write time."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "proj"
    root.mkdir()
    resolve_in_root(root, ".claude/skills/x/SKILL.md")  # what pre-flight saw: nothing there yet
    if not _junction(root / ".claude", outside):
        pytest.skip("cannot create junction here")
    with pytest.raises(SafetyViolation):
        safe_write_bytes(root, ".claude/skills/x/SKILL.md", b"payload")
    assert not any(outside.rglob("*"))
