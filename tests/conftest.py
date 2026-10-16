"""Shared fixtures: disposable workspaces, synthetic registries and target projects.

Nothing here touches the user's home directory or a real project. Every fixture lives under
pytest's tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from agent_forge.config import WORKSPACE_MARKER, WorkspaceConfig, load_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_REGISTRY = REPO_ROOT / "registry"


# ---- registry builders ---------------------------------------------------------------------


def write_capability(
    registry_dir: Path, manifest: dict, assets: dict[str, str] | None = None
) -> Path:
    """Write a capability directory from a manifest dict and {relative asset path: content}."""
    cap_dir = registry_dir / "capabilities" / manifest["id"]
    cap_dir.mkdir(parents=True, exist_ok=True)
    (cap_dir / "capability.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    for rel, content in (assets or {}).items():
        p = cap_dir / "assets" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    return cap_dir


def base_manifest(cid: str, **overrides) -> dict:
    name = cid.split(".")[-1]
    m = {
        "schema_version": "1",
        "id": cid,
        "name": name,
        "description": f"{name} capability",
        "version": "1.0.0",
        "kind": "skill",
        "category": "test",
        "purpose": "testing",
        "status": "curated",
        "provenance": "workspace",
        "source": {"source_id": "workspace"},
        "license": {"spdx": "MIT", "attribution": "tests", "redistribution_ok": True},
        "review": {"reviewed_at": "2026-10-16", "reviewer": "pytest", "rationale": "fixture"},
        "applicability": {"always": True},
        "platforms": ["claude_code", "codex"],
        "install_strategy": "file_copy",
        "destinations": [
            {
                "platform": "claude_code",
                "source": "claude_code/" + name,
                "dest": f".claude/skills/{name}",
            },
            {"platform": "codex", "source": "codex/" + name, "dest": f".agents/skills/{name}"},
        ],
    }
    m.update(overrides)
    return m


def skill_assets(name: str, body: str = "Do the thing.") -> dict[str, str]:
    skill = f"---\nname: {name}\ndescription: {name} skill for tests\n---\n\n# {name}\n\n{body}\n"
    return {f"claude_code/{name}/SKILL.md": skill, f"codex/{name}/SKILL.md": skill}


@pytest.fixture
def synthetic_registry(tmp_path: Path) -> Path:
    """A small registry exercising applicability, conflicts, dependencies and section merge."""
    reg = tmp_path / "registry"
    (reg / "capabilities").mkdir(parents=True)
    write_capability(reg, base_manifest("t.always"), skill_assets("always"))
    write_capability(
        reg,
        base_manifest(
            "t.python-only",
            applicability={"languages": ["python"], "tags": ["py"]},
        ),
        skill_assets("python-only"),
    )
    write_capability(
        reg,
        base_manifest("t.tagged", applicability={"tags": ["extra"]}),
        skill_assets("tagged"),
    )
    write_capability(
        reg,
        base_manifest("t.needs-always", dependencies=["t.always"]),
        skill_assets("needs-always"),
    )
    write_capability(
        reg,
        base_manifest("t.conflicts-always", conflicts=["t.always"], benefit_score=2),
        skill_assets("conflicts-always"),
    )
    write_capability(
        reg,
        base_manifest(
            "t.equiv",
            equivalents=[
                {
                    "kind": "skill",
                    "name_patterns": ["^my-equiv"],
                    "description": "an existing equivalent skill",
                }
            ],
        ),
        skill_assets("equiv"),
    )
    write_capability(
        reg,
        base_manifest(
            "t.notice",
            kind="instruction",
            install_strategy="section_merge",
            removal="remove_section",
            benefit_score=4,
            destinations=[
                {
                    "platform": "claude_code",
                    "source": "claude_code/notice.md",
                    "dest": "CLAUDE.md",
                    "merge": "append_section",
                    "section_id": "t-notice",
                },
                {
                    "platform": "codex",
                    "source": "codex/notice.md",
                    "dest": "AGENTS.md",
                    "merge": "append_section",
                    "section_id": "t-notice",
                },
            ],
        ),
        {
            "claude_code/notice.md": "## Notice\n\nManaged section.\n",
            "codex/notice.md": "## Notice\n\nManaged section.\n",
        },
    )
    write_capability(
        reg,
        base_manifest(
            "t.native",
            install_strategy="native_plugin",
            destinations=[],
            runtime_requirements=[{"name": "thing", "description": "needs a runtime"}],
            applicability={"tags": ["native"]},
        ),
    )
    write_capability(
        reg,
        base_manifest("t.under-review", status="under_review"),
        skill_assets("under-review"),
    )
    write_capability(
        reg,
        base_manifest(
            "t.hook",
            kind="hook",
            risk="medium",
            platforms=["claude_code"],
            destinations=[
                {
                    "platform": "claude_code",
                    "source": "claude_code/hooks.json",
                    "dest": ".claude/settings.json",
                    "merge": "json_merge",
                    "section_id": "t-hook",
                }
            ],
        ),
        {
            "claude_code/hooks.json": json.dumps(
                {
                    "hooks": {
                        "PostToolUse": [
                            {
                                "matcher": "Edit|Write",
                                "hooks": [
                                    {"type": "command", "command": "echo t-hook", "timeout": 5}
                                ],
                            }
                        ]
                    }
                }
            )
        },
    )
    write_capability(
        reg,
        base_manifest(
            "t.mcp",
            kind="mcp",
            risk="medium",
            platforms=["claude_code"],
            install_strategy="section_merge",
            destinations=[
                {
                    "platform": "claude_code",
                    "source": "claude_code/mcp.json",
                    "dest": ".mcp.json",
                    "merge": "json_merge",
                    "section_id": "t-mcp",
                }
            ],
        ),
        {
            "claude_code/mcp.json": json.dumps(
                {
                    "mcpServers": {
                        "t-server": {"type": "stdio", "command": "npx", "args": ["-y", "t"]}
                    }
                }
            )
        },
    )
    return reg


# ---- workspace -----------------------------------------------------------------------------


def make_workspace(root: Path, registry_dir: Path) -> WorkspaceConfig:
    root.mkdir(parents=True, exist_ok=True)
    (root / WORKSPACE_MARKER).write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "registry_dir": str(registry_dir),
                "sources_dir": "sources",
                "checkouts_dir": "sources/checkouts",
                "state_dir": "state",
            }
        ),
        encoding="utf-8",
    )
    (root / "sources").mkdir(exist_ok=True)
    (root / "sources" / "sources.yaml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "sources": [
                    {
                        "id": "ecc",
                        "name": "ECC",
                        "url": "https://github.com/affaan-m/ECC",
                        "license": "MIT",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ws = load_workspace(root)
    ws.ensure_state_dirs()
    return ws


@pytest.fixture
def workspace(tmp_path: Path, synthetic_registry: Path) -> WorkspaceConfig:
    return make_workspace(tmp_path / "ws", synthetic_registry)


@pytest.fixture
def real_workspace(tmp_path: Path) -> WorkspaceConfig:
    """Workspace that uses the repository's curated registry (read-only) with tmp state."""
    return make_workspace(tmp_path / "ws-real", REAL_REGISTRY)


# ---- target projects -----------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


ProjectFactory = Callable[..., Path]


@pytest.fixture
def make_project(tmp_path: Path) -> ProjectFactory:
    """Build disposable target projects: make_project(name, kind=..., git=True, files={...})."""

    def _make(
        name: str = "proj",
        *,
        kind: str = "none",
        git: bool = True,
        files: dict[str, str] | None = None,
        commit: bool = True,
    ) -> Path:
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        base: dict[str, str] = {
            "src/main.py": "print('hi')\n",
            "pyproject.toml": "[project]\nname='x'\nversion='0'\ndependencies=['pytest']\n",
        }
        if kind in ("claude", "both"):
            base["CLAUDE.md"] = "# Project\n\nUser instructions.\n"
            base[".claude/skills/my-equiv/SKILL.md"] = (
                "---\nname: my-equiv\ndescription: existing\n---\n# x\n"
            )
            base[".claude/settings.json"] = json.dumps(
                {
                    "hooks": {
                        "PostToolUse": [
                            {
                                "matcher": "Edit",
                                "hooks": [{"type": "command", "command": "echo hi"}],
                            }
                        ]
                    }
                }
            )
        if kind in ("codex", "both"):
            base["AGENTS.md"] = "# Agents\n\nCodex instructions.\n"
            base[".agents/skills/existing/SKILL.md"] = (
                "---\nname: existing\ndescription: existing\n---\n# y\n"
            )
            (root / ".codex").mkdir(exist_ok=True)
            base[".codex/config.toml"] = 'model = "gpt-5"\n'
        base.update(files or {})
        for rel, content in base.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
        if git:
            _git(root, "init", "-q")
            _git(root, "add", "-A")
            if commit:
                _git(root, "commit", "-q", "-m", "init")
        return root

    return _make


def can_symlink(tmp_path: Path) -> bool:
    target = tmp_path / "_symlink_probe_target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "_symlink_probe"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        return False
    finally:
        if link.exists() or link.is_symlink():
            link.unlink()
    return True
