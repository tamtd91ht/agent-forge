"""`agent-forge forge`: one-shot scan -> upgrade -> assign -> approve -> apply -> validate."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app

pytestmark = pytest.mark.e2e
runner = CliRunner()


def run(*args: str, expect: int = 0, input: str | None = None):
    result = runner.invoke(app, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\nexit={result.exit_code}\n{result.output}"
    return result


def run_json(*args: str, expect: int = 0):
    return json.loads(run(*args, expect=expect).stdout)


BACKEND_FILES = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
    "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
}


def test_forge_backend_only_gets_backend_capabilities(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("api service", kind="claude", files=BACKEND_FILES)
    report = run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")
    assert (
        report["profile"]["project_types"] == ["backend"]
        or "backend" in report["profile"]["project_types"]
    )
    assert "frontend" not in report["profile"]["project_types"]
    steps = {s["label"]: s for s in report["steps"]}
    add = steps["add recommended capabilities"]
    assert add["status"] == "applied"
    assert "ecc.security-review" in add["selected"]
    assert "ecc.error-handling" in add["selected"]  # python
    # project-aware: nothing UI-related for a backend service
    assert "uiux.guidelines" not in add["selected"]
    assert add["rejected"]["uiux.guidelines"] == "not_applicable"
    assert add["rejected"]["uiux.full-toolkit"] == "not_applicable"
    # tag-only / UI-only native capabilities are not even hinted at for a backend service
    assert add["rejected"]["rea.reverse-engineer-anything"] == "not_applicable"
    assert report["needs_runtime"] == {}
    assert report["validation"]["ok"]
    assert (root / ".claude" / "skills" / "security-review" / "SKILL.md").is_file()
    assert not (root / ".claude" / "skills" / "ui-ux-guidelines").exists()
    assert "agent-forge:begin" in (root / "CLAUDE.md").read_text(encoding="utf-8")
    # second run: nothing to do (idempotent)
    report2 = run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")
    assert all(s["status"] == "nothing_to_do" for s in report2["steps"])


def test_forge_frontend_gets_ui_guidelines(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project(
        "web app",
        files={
            "package.json": json.dumps(
                {"name": "web", "dependencies": {"react": "19", "next": "15"}}
            ),
            "tsconfig.json": "{}",
        },
    )
    (root / "pyproject.toml").unlink()
    (root / "src" / "main.py").unlink()
    report = run_json("forge", str(root), "--workspace", ws, "--yes", "--json")
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    assert "uiux.guidelines" in add["selected"]
    assert "ecc.error-handling" in add["selected"]  # typescript/javascript
    # no --shared-files: the notice capability is left out (needs_approval), nothing else is blocked
    assert add["rejected"]["forge.managed-notice"] == "needs_approval"
    assert "forge.managed-notice" in add["needs_approval"]
    assert not (root / "CLAUDE.md").exists()
    assert (root / ".claude" / "skills" / "ui-ux-guidelines" / "SKILL.md").is_file()


def test_forge_dry_run_writes_nothing(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("dry", kind="claude", files=BACKEND_FILES)
    before = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts
    )
    report = run_json(
        "forge", str(root), "--workspace", ws, "--dry-run", "--shared-files", "--json"
    )
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    assert before == after
    assert all(s["status"] == "planned" for s in report["steps"])
    assert "validation" not in report


def test_forge_requires_tty_or_yes(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("notty", kind="claude", files=BACKEND_FILES)
    run("forge", str(root), "--workspace", ws, expect=6)
    assert not (root / ".claude" / "skills" / "security-review").exists()


def test_forge_adds_karpathy_principles_section(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("karpathy", kind="claude", files=BACKEND_FILES)
    report = run_json("forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json")
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    assert "karpathy.principles" in add["selected"]
    # the skill variant is tag-only: never installed alongside the always-on section
    assert "karpathy.guidelines" not in add["selected"]
    claude_md = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.startswith("# Project\n\nUser instructions.\n")
    assert "agent-forge:begin id=karpathy-principles" in claude_md
    assert "### 3. Surgical changes" in claude_md
    assert not (root / ".claude" / "skills" / "karpathy-guidelines").exists()


def test_forge_skips_karpathy_when_project_already_has_it(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    files = dict(BACKEND_FILES)
    files["CLAUDE.md"] = "# Project\n\n## 1. Think Before Coding\n\nAsk first.\n"
    root = make_project("karpathy present", kind="claude", files=files)
    report = run_json(
        "forge", str(root), "--workspace", ws, "--dry-run", "--shared-files", "--json"
    )
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    assert "karpathy.principles" not in add["selected"]
    assert add["rejected"]["karpathy.principles"] == "equivalent_exists"


def test_forge_karpathy_skill_on_request(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("karpathy skill", kind="claude", files=BACKEND_FILES)
    report = run_json(
        "forge",
        str(root),
        "--workspace",
        ws,
        "--yes",
        "--shared-files",
        "--want",
        "guidelines-skill",
        "--json",
    )
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    # an explicit request outranks the always-on section it conflicts with
    assert "karpathy.guidelines" in add["selected"]
    assert add["rejected"]["karpathy.principles"] == "conflict"
    assert "karpathy-principles" not in (root / "CLAUDE.md").read_text(encoding="utf-8")
    skill = root / ".claude" / "skills" / "karpathy-guidelines"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "LICENSE-KARPATHY.txt").is_file()


def test_forge_grill_with_docs_pulls_its_skill_dependencies(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("mattpocock skills", kind="claude", files=BACKEND_FILES)
    report = run_json(
        "forge",
        str(root),
        "--workspace",
        ws,
        "--yes",
        "--shared-files",
        "--want",
        "grill-with-docs",
        "--json",
    )
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    for cid in ("mattpocock.grill-with-docs", "mattpocock.grilling", "mattpocock.domain-modeling"):
        assert cid in add["selected"]
    assert "mattpocock.diagnosing-bugs" in add["selected"]  # always-on
    assert "mattpocock.tdd" not in add["selected"]  # tag-only alternative to ecc.tdd-workflow
    skills = root / ".claude" / "skills"
    assert "disable-model-invocation: true" in (skills / "grill-with-docs" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert (skills / "diagnosing-bugs" / "scripts" / "hitl-loop.template.sh").is_file()
    assert (skills / "grilling" / "LICENSE-MATTPOCOCK.txt").is_file()


def test_plan_reports_always_loaded_context(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("ctx", kind="claude", files=BACKEND_FILES)
    plan = run_json("assign", str(root), "--workspace", ws, "--want", "grill-with-docs", "--json")
    ctx = {s["capability_id"]: s["context_chars"] for s in plan["selected"]}
    assert ctx["mattpocock.grill-with-docs"] == 0  # user-invoked: no description in context
    assert ctx["mattpocock.grilling"] > 0
    assert ctx["karpathy.principles"] > 1000  # a CLAUDE.md section is loaded in full


def test_forge_git_guard_shares_settings_with_secret_guard(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("git guard", kind="claude", files=BACKEND_FILES)
    report = run_json(
        "forge",
        str(root),
        "--workspace",
        ws,
        "--yes",
        "--shared-files",
        "--hooks",
        "--want",
        "git-guard",
        "--json",
    )
    add = {s["label"]: s for s in report["steps"]}["add recommended capabilities"]
    assert {"forge.hook.guard-dangerous-git", "forge.hook.guard-secrets-python"} <= set(
        add["selected"]
    )
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [h["command"] for g in settings["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert any("guard_git.py" in c for c in commands)
    assert any("guard_secrets.py" in c for c in commands)
    assert (root / ".claude" / "hooks" / "agent-forge" / "guard_git.py").is_file()
