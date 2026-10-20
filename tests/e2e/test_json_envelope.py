"""JSON envelope v1 (6-month plan, phase 4): every `--json` command prints the same shape,
automation can rely on `envelope`, `command`, `ok` and `data`."""

from __future__ import annotations

import json
from datetime import datetime

import jsonschema
import pytest
from typer.testing import CliRunner

from agent_forge import __version__
from agent_forge.cli import app
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.e2e
runner = CliRunner()
SCHEMA = json.loads(
    (REPO_ROOT / "registry" / "schema" / "envelope.schema.json").read_text(encoding="utf-8")
)

BACKEND = {
    "pyproject.toml": "[project]\nname='api'\nversion='0'\ndependencies=['fastapi','pytest']\n",
}


def _env(args: list[str], expect: int = 0) -> dict:
    res = runner.invoke(app, args, catch_exceptions=False)
    assert res.exit_code == expect, f"{args}\n{res.output}"
    doc = json.loads(res.stdout)
    jsonschema.validate(doc, SCHEMA)
    assert doc["envelope"] == 1 and doc["agent_forge"] == __version__
    datetime.fromisoformat(doc["generated_at"])
    return doc


def test_every_json_command_uses_the_envelope(real_workspace, make_project) -> None:
    ws = str(real_workspace.root)
    root = make_project("env", kind="claude", files=BACKEND)
    w = ["--workspace", ws, "--json"]

    cases: list[tuple[list[str], str, type]] = [
        (["catalog", *w], "agent-forge catalog", list),
        (["catalog", "show", "ecc.tdd-workflow", *w], "agent-forge catalog show", dict),
        (["scan", str(root), *w], "agent-forge scan", dict),
        (["assign", str(root), *w], "agent-forge assign", dict),
        (["plans", *w], "agent-forge plans", list),
        (["policy", *w], "agent-forge policy", dict),
        (["doctor", *w], "agent-forge doctor", list),
        (["audit", *w], "agent-forge audit", list),
        (["stats", *w], "agent-forge stats", dict),
        (["status", str(root), *w], "agent-forge status", dict),
        (["drift", str(root), *w], "agent-forge drift", dict),
        (["check", str(root), *w], "agent-forge check", dict),
        (["sync", str(root), "--yes", *w], "agent-forge sync", dict),
        (["impact", "ecc.tdd-workflow", *w], "agent-forge impact", dict),
        (["validate", *w, "--no-provenance"], "agent-forge validate", dict),
        (["sources", "list", *w], "agent-forge sources list", list),
    ]
    for args, command, kind in cases:
        doc = _env(args)
        assert doc["command"] == command, args
        assert isinstance(doc["data"], kind), args
        assert doc["ok"] is True, args

    forge = _env(["forge", str(root), "--yes", "--shared-files", *w])
    assert forge["command"] == "agent-forge forge" and forge["data"]["steps"]
    tx_id = next(s["transaction_id"] for s in forge["data"]["steps"] if s.get("transaction_id"))
    rb = _env(["rollback", tx_id, "--yes", *w])
    assert rb["command"] == "agent-forge rollback" and rb["data"]["transaction_id"].startswith(
        "rb-"
    )

    # a failing report keeps the envelope and says ok: false
    (root / ".agent-forge").mkdir(exist_ok=True)
    (root / ".agent-forge" / "managed.json").write_text("{broken", encoding="utf-8")
    bad = _env(["check", str(root), *w], expect=12)
    assert bad["ok"] is False and bad["data"]["ok"] is False


def test_errors_never_print_json_on_stdout(real_workspace) -> None:
    res = runner.invoke(
        app,
        [
            "apply",
            "plan-20990101-000000-abcdef",
            "--yes",
            "--workspace",
            str(real_workspace.root),
            "--json",
        ],
    )
    assert res.exit_code == 6 and res.stdout.strip() == ""
