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
    "path", ["C:/Windows/x", "CON", "a/NUL.txt", ".git/config", r"\\srv\share\x"]
)
def test_managed_manifest_rejects_every_unsafe_path_form(make_project, path: str) -> None:
    bad = {
        "version": "1",
        "capabilities": [
            {
                "capability_id": "x",
                "version": "1.0.0",
                "transaction_id": "t",
                "installed_at": "now",
                "files": {path: "h"},
            }
        ],
    }
    root = make_project("badpaths2", files={".agent-forge/managed.json": json.dumps(bad)})
    assert not scan_project(root).managed


def test_scan_read_is_bounded_when_file_grows(tmp_path: Path) -> None:
    root = tmp_path / "grow"
    root.mkdir()
    f = root / "notes.md"
    f.write_text("small", encoding="utf-8")
    w = Walker(root, max_files=10, max_file_bytes=100)
    list(w.walk())
    f.write_text("x" * 10_000, encoding="utf-8")  # grows after the walk recorded its size
    assert w.read_text("notes.md") is None
    assert w.read_bytes("notes.md") is None


@pytest.mark.parametrize(
    "name", [".env", ".env.production", "id_ed25519", "x.pem", "credentials.json", "secrets.yaml"]
)
def test_looks_secret(name: str) -> None:
    assert looks_secret(name)


@pytest.mark.parametrize("name", [".env.example", "README.md", "package.json"])
def test_not_secret(name: str) -> None:
    assert not looks_secret(name)


def test_low_confidence_detection_is_reported(make_project) -> None:
    root = make_project(
        "lowconf", files={"scripts/a.ts": "export {}\n", "scripts/b.ts": "export {}\n"}
    )
    profile = scan_project(root)
    assert "typescript" not in profile.language_names
    assert any("low-confidence language 'typescript'" in w for w in profile.warnings)


def test_profile_override_file(make_project) -> None:
    root = make_project(
        "override",
        files={
            ".agent-forge/profile.yaml": (
                "languages: [java]\nframeworks: [spring]\nproject_types: [backend]\n"
                "ignore: [python, test:pytest]\n"
            )
        },
    )
    profile = scan_project(root)
    assert {"java"} <= profile.language_names and "python" not in profile.language_names
    assert "spring" in profile.framework_names and "test:pytest" not in profile.framework_names
    assert "backend" in profile.project_type_names
    java = next(d for d in profile.languages if d.name == "java")
    assert java.confidence == 1.0 and java.evidence[0].path == ".agent-forge/profile.yaml"


def test_invalid_profile_override_is_reported_not_applied(make_project) -> None:
    root = make_project("override-bad", files={".agent-forge/profile.yaml": "languages: java\n"})
    profile = scan_project(root)
    assert any("profile.yaml ignored" in w for w in profile.warnings)
    assert "java" not in profile.language_names


# ---- traits (ADR-0010) -----------------------------------------------------------------------

_TENANT_SRC = (
    "def list_orders(tenant_id: str, page: int) -> list:\n"
    "    return repo.find({'tenantId': tenant_id}, page=page)\n"
)


def test_traits_are_detected_from_source_with_evidence(make_project) -> None:
    files = {f"src/svc/module{i}.py": _TENANT_SRC for i in range(5)}
    files["src/billing/wallet.py"] = "class Wallet:\n    def refund(self, invoice): ...\n"
    files["src/other.py"] = "x = 1\n"
    root = make_project("tenant", files=files)
    profile = scan_project(root)
    assert "multi_tenant" in profile.trait_names
    mt = next(d for d in profile.traits if d.name == "multi_tenant")
    assert mt.confidence >= 0.6
    assert mt.evidence[0].path == "*" and "sampled source files" in mt.evidence[0].detail
    assert any(e.path.startswith("src/svc/") for e in mt.evidence)
    # one money file out of eight: a low-confidence hint, not a trait used for recommendations
    assert "money" not in profile.trait_names
    assert any("low-confidence trait 'money'" in w for w in profile.warnings)
    assert profile.fingerprint() != scan_project(make_project("plain-fp")).fingerprint()


def test_event_driven_trait_follows_a_broker_dependency(make_project) -> None:
    root = make_project(
        "broker",
        files={
            "pyproject.toml": (
                "[project]\nname='x'\nversion='0'\ndependencies=['pytest','aiokafka']\n"
            )
        },
    )
    profile = scan_project(root)
    assert "kafka" in profile.framework_names
    ev = next(d for d in profile.traits if d.name == "event_driven")
    assert ev.confidence >= 0.8 and ev.evidence[0].path == "pyproject.toml"


def test_project_without_traits_keeps_its_fingerprint(make_project) -> None:
    root = make_project("plain2")
    profile = scan_project(root)
    assert profile.traits == []
    before = profile.fingerprint()
    profile.traits = []  # explicit: the payload key is absent, not an empty list
    assert profile.fingerprint() == before


def test_trait_override_confirms_and_rules_out(make_project) -> None:
    files = {f"src/m{i}.py": _TENANT_SRC for i in range(4)}
    files[".agent-forge/profile.yaml"] = "traits: [pii, bogus]\nignore: [multi_tenant]\n"
    root = make_project("trait-override", files=files)
    profile = scan_project(root)
    assert "multi_tenant" not in profile.trait_names
    pii = next(d for d in profile.traits if d.name == "pii")
    assert pii.confidence == 1.0 and pii.evidence[0].path == ".agent-forge/profile.yaml"
    assert any("unknown trait 'bogus'" in w for w in profile.warnings)


def test_trait_sampling_spreads_across_top_level_directories(make_project) -> None:
    # 400 token-free files in the first directory alone exceed the sample size; the tenant
    # identifiers live in the last directory and must still be seen.
    files = {f"aaa/f{i:03d}.py": "x = 1\n" for i in range(400)}
    files.update({f"zzz/m{i:03d}.py": _TENANT_SRC for i in range(100)})
    profile = scan_project(make_project("spread", files=files))
    assert "multi_tenant" in profile.trait_names
    mt = next(d for d in profile.traits if d.name == "multi_tenant")
    assert mt.confidence >= 0.6
