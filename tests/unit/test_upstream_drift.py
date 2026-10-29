"""Which curated capabilities changed upstream since their recorded revision."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_forge.models.capability import Capability
from agent_forge.sources.provenance import upstream_drift
from tests.conftest import _git, base_manifest


def _commit(repo: Path, files: dict[str, str]) -> str:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _cap(revision: str, paths: list[str]) -> Capability:
    m = base_manifest(
        "up.skill",
        provenance="upstream",
        source={"source_id": "up", "revision": revision, "paths": paths},
    )
    return Capability.model_validate(m)


def test_reports_only_changes_under_the_capability_paths(tmp_path: Path) -> None:
    repo = tmp_path / "up stream ü"
    repo.mkdir()
    _git(repo, "init", "-q")
    first = _commit(repo, {"skills/a/SKILL.md": "a1", "skills/b/SKILL.md": "b1"})
    head = _commit(repo, {"skills/b/SKILL.md": "b2", "README.md": "r"})

    assert upstream_drift(_cap(first, ["skills/a"]), repo, head) == []
    assert upstream_drift(_cap(first, ["skills/b/SKILL.md"]), repo, head) == ["skills/b/SKILL.md"]
    assert upstream_drift(_cap(head, ["skills/b"]), repo, head) == []


def test_unknown_revision_is_not_reported_as_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    head = _commit(repo, {"x.md": "x"})
    assert upstream_drift(_cap("0" * 40, ["x.md"]), repo, head) is None
