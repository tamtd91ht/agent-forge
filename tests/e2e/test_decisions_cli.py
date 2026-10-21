"""CLI of the decision layer (ADR-0007): decisions verify / diff / explain / report,
forge --decisions, status and drift integration, check with policy `required`, lint, usage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_forge.cli import app
from tests.conftest import unwrap

pytestmark = pytest.mark.e2e
runner = CliRunner()

BACKEND = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
    "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
    ".claude/rules/security.md": (
        "# Security review\n\nEvery change touching auth, input parsing or secrets gets a "
        "security review before merge; check injection, authz and secret handling.\n"
    ),
}


def run(*args: str, expect: int = 0, input: str | None = None):
    result = runner.invoke(app, list(args), input=input, catch_exceptions=False)
    assert result.exit_code == expect, f"{args}\nexit={result.exit_code}\n{result.output}"
    return result


def run_json(*args: str, expect: int = 0):
    return unwrap(run(*args, expect=expect).stdout)


def _write_record(
    root: Path, plan_id: str, decisions: list[dict], stamp: str = "2026-10-21T00:00:00Z"
) -> Path:
    d = root / ".agent-forge" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": "1",
        "plan_id": plan_id,
        "assessed_by": "pytest-model",
        "assessed_at": stamp,
        "decisions": [{"confidence": "high", "reason": "test", **x} for x in decisions],
    }
    p = d / f"{plan_id}.json"
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return p


SKIP_SECURITY = {
    "capability_id": "ecc.security-review",
    "verdict": "SKIP",
    "grounds": ["covered"],
    "covered_by": [{"path": ".claude/rules/security.md", "quote": "security review before merge"}],
}
FAKE_SKIP_TDD = {
    "capability_id": "ecc.tdd-workflow",
    "verdict": "SKIP",
    "grounds": ["covered"],
    "covered_by": [{"path": ".claude/rules/security.md", "quote": "red green refactor"}],
}
ADD_BUGS = {
    "capability_id": "mattpocock.diagnosing-bugs",
    "verdict": "ADD",
    "gap": "no debugging routine",
}


def test_verify_explain_and_status_read_the_record(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("dec", kind="claude", files=BACKEND)
    _write_record(root, "plan-1", [SKIP_SECURITY, FAKE_SKIP_TDD, ADD_BUGS])
    out = run_json("decisions", "verify", str(root), "--workspace", ws, "--json", expect=12)
    assert out["ok"] is False and out["plan_id"] == "plan-1"
    eff = out["effective"]
    assert eff["SKIP"] == ["ecc.security-review"] and eff["ASK"] == ["ecc.tdd-workflow"]
    assert eff["ADD"] == ["mattpocock.diagnosing-bugs"]
    assert out["downgraded"] == [
        {
            "capability_id": "ecc.tdd-workflow",
            "from": "SKIP",
            "to": "ASK",
            "why": [".claude/rules/security.md: quote not found in the file: 'red green refactor'"],
        }
    ]
    text = run(
        "decisions",
        "verify",
        str(
            root,
        ),
        "--workspace",
        ws,
        expect=12,
    ).output
    assert "could not prove it" in text

    ex = run_json("decisions", "explain", str(root), "ecc.security-review", "--json")
    assert ex["decision"]["verdict"] == "SKIP" and ex["assessed_by"] == "pytest-model"
    run("decisions", "explain", str(root), "nope.id", expect=6)

    st = run_json("status", str(root), "--workspace", ws, "--json")
    absent = {d["capability_id"]: d for d in st["decisions"]}
    assert set(absent) == {"ecc.security-review", "ecc.tdd-workflow"}
    assert absent["ecc.security-review"]["basis"] == [".claude/rules/security.md"]
    assert st["usage"] is None
    assert "absent by decision" in run("status", str(root), "--workspace", ws).output

    # the basis disappears -> drift says so
    (root / ".claude" / "rules" / "security.md").unlink()
    dr = run_json("drift", str(root), "--workspace", ws, "--json")
    assert [b["state"] for b in dr["decision_basis"]] == ["basis_missing", "basis_missing"]
    assert "decision basis basis_missing" in run("drift", str(root), "--workspace", ws).output


def test_forge_with_decisions_excludes_proven_skips_and_gates_on_ask(
    real_workspace, make_project
) -> None:
    ws = str(real_workspace.root)
    root = make_project("dec2", kind="claude", files=BACKEND)
    rec = _write_record(root, "plan-1", [SKIP_SECURITY, FAKE_SKIP_TDD, ADD_BUGS])
    dry = run_json(
        "forge", str(root), "--workspace", ws, "--dry-run", "--decisions", str(rec), "--json"
    )
    assert dry["decisions"]["effective"]["ASK"] == ["ecc.tdd-workflow"]
    add = next(s for s in dry["steps"] if s["label"] == "add recommended capabilities")
    assert "ecc.security-review" not in add["selected"]
    assert add["rejected"]["ecc.security-review"] == "user_excluded"
    assert "mattpocock.diagnosing-bugs" in add["selected"]
    assert "ecc.tdd-workflow" in add["selected"]  # ASK: still in the baseline on a dry run

    # a real run stops on the unresolved ASK, writes nothing
    res = runner.invoke(
        app,
        ["forge", str(root), "--workspace", ws, "--yes", "--decisions", str(rec), "--json"],
        catch_exceptions=False,
    )
    assert res.exit_code == 6 and "ecc.tdd-workflow" in res.output
    assert not (root / ".agent-forge" / "managed.json").exists()

    # the user answers with a flag; the plan binds the record's digest
    done = run_json(
        "forge",
        str(root),
        "--workspace",
        ws,
        "--yes",
        "--decisions",
        str(rec),
        "--exclude",
        "ecc.tdd-workflow",
        "--json",
    )
    add = next(s for s in done["steps"] if s["label"] == "add recommended capabilities")
    assert add["status"] == "applied"
    assert (
        "ecc.security-review" not in add["selected"] and "ecc.tdd-workflow" not in add["selected"]
    )
    plan = json.loads(
        (real_workspace.state_dir / "plans" / f"{add['plan_id']}.json").read_text(encoding="utf-8")
    )
    assert plan["decisions_digest"] == done["decisions"]["digest"]
    assert any(n.startswith("decisions: ") for n in plan["notes"])


def test_diff_and_org_report(real_workspace, make_project, tmp_path: Path) -> None:
    root = make_project("dec3", kind="claude", files=BACKEND)
    _write_record(root, "plan-1", [SKIP_SECURITY, ADD_BUGS], stamp="2026-10-01T00:00:00Z")
    _write_record(
        root,
        "plan-2",
        [
            {
                **SKIP_SECURITY,
                "verdict": "ADD",
                "grounds": [],
                "covered_by": [],
                "gap": "changed mind",
            },
            ADD_BUGS,
        ],
        stamp="2026-10-21T00:00:00Z",
    )
    diff = run_json("decisions", "diff", str(root), "--json")
    assert diff["old"]["plan_id"] == "plan-1" and diff["new"]["plan_id"] == "plan-2"
    assert [c["capability_id"] for c in diff["changes"]] == ["ecc.security-review"]
    assert (
        diff["changes"][0]["old"]["verdict"] == "SKIP"
        and diff["changes"][0]["new"]["verdict"] == "ADD"
    )
    assert "1 changed decision" in run("decisions", "diff", str(root)).output

    org = tmp_path / "org"
    for i in range(3):
        repo = org / f"repo{i}"
        (repo / "src").mkdir(parents=True)
        _write_record(repo, "plan-x", [SKIP_SECURITY, ADD_BUGS])
    report = run_json("decisions", "report", str(org), "--json")
    assert report["records"] == 3
    rows = {r["capability"]: r for r in report["capabilities"]}
    assert rows["ecc.security-review"]["verdicts"] == {"SKIP": 3}
    assert rows["ecc.security-review"]["grounds"] == {"covered": 3}
    suggestions = {(s["capability"], s["suggestion"]) for s in report["suggestions"]}
    assert ("ecc.security-review", "candidate to leave the default catalog") in suggestions
    assert ("mattpocock.diagnosing-bugs", "candidate for `capabilities.required`") in suggestions


def test_check_fails_when_a_required_capability_is_missing(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("req", kind="claude", files=BACKEND)
    (root / ".agent-forge").mkdir(exist_ok=True)
    (root / ".agent-forge" / "policy.yaml").write_text(
        yaml.safe_dump(
            {"name": "team", "capabilities": {"required": ["mattpocock.diagnosing-bugs"]}}
        ),
        encoding="utf-8",
    )
    pol = run_json("policy", str(root), "--workspace", ws, "--json")
    assert pol["required"] == ["mattpocock.diagnosing-bugs"]
    assert pol["verdicts"]["mattpocock.diagnosing-bugs"]["claude_code"]["required"] is True
    out = run_json("check", str(root), "--workspace", ws, "--json", expect=12)
    assert out["required_missing"] == ["mattpocock.diagnosing-bugs"]
    assert any("required but not installed" in f for f in out["failures"])
    # the agent or a flag cannot exclude it
    res = runner.invoke(
        app,
        [
            "forge",
            str(root),
            "--workspace",
            ws,
            "--yes",
            "--exclude",
            "mattpocock.diagnosing-bugs",
            "--json",
        ],
        catch_exceptions=False,
    )
    assert res.exit_code == 2 and "policy requires" in res.output
    done = run_json("forge", str(root), "--workspace", ws, "--yes", "--json")
    add = next(s for s in done["steps"] if s["label"] == "add recommended capabilities")
    assert "mattpocock.diagnosing-bugs" in add["selected"]
    out = run_json("check", str(root), "--workspace", ws, "--json")
    assert out["ok"] and out["required_missing"] == []


def test_lint_needs_no_workspace_and_gates_on_errors(make_project) -> None:
    root = make_project("lintp", kind="claude", files=BACKEND)
    out = run_json("lint", str(root), "--json")
    assert out["ok"] and out["always_on_total"] > 0
    assert any(f["path"] == ".claude/rules/security.md" for f in out["files"])
    assert "always-loaded context" in run("lint", str(root)).output
    run_json("lint", str(root), "--max-context", "5", "--json", expect=12)
    (root / "CLAUDE.md").write_text("# P\n\nAKIAABCDEFGHIJKLMNOP is our key\n", encoding="utf-8")
    bad = run_json("lint", str(root), "--json", expect=12)
    assert bad["findings"][0]["check"] == "secret"


def test_usage_command_reads_the_local_log(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("usep", kind="claude", files=BACKEND)
    assert "no usage log" in run("usage", str(root), "--workspace", ws).output
    run_json("forge", str(root), "--workspace", ws, "--yes", "--json")
    manifest = json.loads((root / ".agent-forge" / "managed.json").read_text(encoding="utf-8"))
    for rec in manifest["capabilities"]:
        rec["installed_at"] = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    (root / ".agent-forge" / "managed.json").write_text(json.dumps(manifest), encoding="utf-8")
    old = (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / ".agent-forge" / "usage.jsonl").write_text(
        json.dumps({"at": old, "kind": "skill", "id": "diagnosing-bugs"})
        + "\n"
        + json.dumps({"at": new, "kind": "skill", "id": "diagnosing-bugs"})
        + "\n",
        encoding="utf-8",
    )
    data = run_json("usage", str(root), "--workspace", ws, "--json")
    rows = {r["capability"]: r for r in data["by_capability"]}
    assert rows["mattpocock.diagnosing-bugs"]["invocations"] == 2
    assert "ecc.security-review" in data["unused"]
    st = run_json("status", str(root), "--workspace", ws, "--json")
    assert st["usage"]["unused"] == data["unused"]
    assert "unused:" in run("status", str(root), "--workspace", ws).output
