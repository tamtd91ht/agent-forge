from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_forge.models.capability import Platform
from agent_forge.scanner.filesystem import Walker, looks_secret
from agent_forge.scanner.project_profile import scan_project
from tests.conftest import can_symlink


def test_scan_project_without_agent_config(make_project) -> None:
    root = make_project("plain")
    profile = scan_project(root)
    assert "python" in profile.language_names
    assert not profile.platforms
    assert profile.managed_manifest_valid is None
    assert "pytest" in profile.test_commands
    assert profile.git.is_repo and profile.git.dirty is False


def test_scan_detects_claude_and_codex(make_project) -> None:
    root = make_project("both", kind="both")
    profile = scan_project(root)
    assert profile.platform_names == {Platform.CLAUDE_CODE, Platform.CODEX}
    kinds = {(a.platform, a.kind, a.name) for a in profile.assets}
    assert (Platform.CLAUDE_CODE, "skill", "my-equiv") in kinds
    assert (Platform.CLAUDE_CODE, "hook", "PostToolUse") in kinds
    assert (Platform.CODEX, "skill", "existing") in kinds
    assert (Platform.CODEX, "settings", ".codex/config.toml") in kinds


def test_scan_is_read_only_and_reports_dirty_git(make_project) -> None:
    root = make_project("dirty", kind="claude")
    (root / "src" / "new.py").write_text("x\n", encoding="utf-8")
    snapshot = {
        p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    }
    profile = scan_project(root)
    assert profile.git.dirty is True and profile.git.dirty_count >= 1
    after = {
        p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    }
    assert snapshot == after
    assert not (root / ".agent-forge").exists()


def test_scan_skips_secrets_and_excluded_dirs(make_project) -> None:
    root = make_project(
        "secrets",
        files={
            ".env": "TOKEN=abc123\n",
            "node_modules/pkg/index.js": "x",
            "id_rsa": "KEY",
            "certs/x.pem": "PEM",
        },
    )
    profile = scan_project(root)
    assert ".env" in profile.sensitive_files and "id_rsa" in profile.sensitive_files
    assert "certs/x.pem" in profile.sensitive_files
    assert "node_modules" in profile.stats.excluded_dirs
    dumped = json.dumps(profile.model_dump(mode="json"))
    assert "abc123" not in dumped and "KEY" not in dumped


def test_scan_handles_spaces_and_unicode_paths(make_project) -> None:
    root = make_project("my prøject ünïcode", kind="claude")
    profile = scan_project(root)
    assert Platform.CLAUDE_CODE in profile.platform_names
    assert "ünïcode" in profile.canonical_path


def test_walker_never_follows_symlinks(tmp_path: Path) -> None:
    if not can_symlink(tmp_path):
        pytest.skip("symlinks not permitted in this environment")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("outside", encoding="utf-8")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.md").write_text("in", encoding="utf-8")
    os.symlink(outside, root / "link_dir", target_is_directory=True)
    os.symlink(outside / "secret.md", root / "link_file")
    w = Walker(root)
    rels = {e.rel for e in w.walk()}
    assert rels == {"ok.md"}
    assert w.stats.skipped_symlinks == 2


def test_walker_respects_limits(tmp_path: Path) -> None:
    root = tmp_path / "big"
    root.mkdir()
    for i in range(30):
        (root / f"f{i}.txt").write_text("x", encoding="utf-8")
    big = root / "big.bin"
    big.write_bytes(b"\0" * 10)
    w = Walker(root, max_files=10, max_file_bytes=5)
    list(w.walk())
    assert w.stats.truncated
    assert w.read_text("big.bin") is None


def test_invalid_managed_manifest_is_rejected(make_project) -> None:
    root = make_project(
        "badmanifest",
        files={".agent-forge/managed.json": '{"version": "1", "capabilities": "nope"}'},
    )
    profile = scan_project(root)
    assert profile.managed_manifest_valid is False
    assert any("managed.json" in w for w in profile.warnings)


def test_managed_manifest_unsafe_paths_rejected(make_project) -> None:
    bad = {
        "version": "1",
        "capabilities": [
            {
                "capability_id": "x",
                "version": "1.0.0",
                "transaction_id": "t",
                "installed_at": "now",
                "files": {"../../etc/passwd": "h"},
            }
        ],
    }
    root = make_project("badpaths", files={".agent-forge/managed.json": json.dumps(bad)})
    profile = scan_project(root)
    assert profile.managed_manifest_valid is False
    assert not profile.managed


@pytest.mark.parametrize(
    "name", [".env", ".env.production", "id_ed25519", "x.pem", "credentials.json", "secrets.yaml"]
)
def test_looks_secret(name: str) -> None:
    assert looks_secret(name)


@pytest.mark.parametrize("name", [".env.example", "README.md", "package.json"])
def test_not_secret(name: str) -> None:
    assert not looks_secret(name)
