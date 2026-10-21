"""`examples/lint-messy`: every lint finding is expected and nothing else is flagged.

The fixture is built to be found out (duplicate rules, a pipe-to-shell hook, a disabled MCP
server) and to tempt false positives (a `${API_KEY}` placeholder, a benign `ruff format`
hook, a rule that contradicts CLAUDE.md, which only the skill may judge). Changing the lint
rules means re-reviewing `expected_lint.json` in the same change.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app
from agent_forge.lint import lint_project
from tests.conftest import REPO_ROOT, unwrap

pytestmark = pytest.mark.e2e
EXAMPLE = REPO_ROOT / "examples" / "lint-messy"
EXPECTED = json.loads((EXAMPLE / "expected_lint.json").read_text(encoding="utf-8"))


def test_lint_messy_findings_match_the_reviewed_expectations() -> None:
    rep = lint_project(EXAMPLE / "project")
    got = [{"level": f.level, "check": f.check, "path": f.path} for f in rep.findings]
    assert got == EXPECTED["findings"], got
    assert rep.always_on_total == EXPECTED["always_on_total"]
    assert [{"path": f.path, "chars": f.chars} for f in rep.files] == EXPECTED["files"]
    assert rep.counts == EXPECTED["counts"]
    flagged = {f.path for f in rep.findings}
    for never in EXPECTED["never_flagged"]:
        assert never not in flagged, never
    # the designed problems are all there, each exactly once
    checks = sorted((f.level, f.check) for f in rep.findings)
    assert ("error", "hook") in checks and checks.count(("error", "hook")) == 1
    assert ("warning", "mcp") in checks and checks.count(("warning", "mcp")) == 1
    assert checks.count(("warning", "duplicate")) == 2
    assert not any(f.check == "secret" for f in rep.findings)  # placeholders are not secrets


def test_lint_messy_through_the_cli_is_a_gate() -> None:
    res = CliRunner().invoke(app, ["lint", str(EXAMPLE / "project"), "--json"])
    assert res.exit_code == 12, res.output
    doc = unwrap(res.stdout)
    assert doc["ok"] is False
    assert [f["check"] for f in doc["findings"] if f["level"] == "error"] == ["hook"]
