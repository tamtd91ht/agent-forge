"""Every documented exit code is produced by a real CLI path (roadmap F4, cli-reference.md)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app
from agent_forge.storage.locks import target_lock
from agent_forge.storage.transactions import Store
from tests.conftest import unwrap

pytestmark = pytest.mark.e2e
runner = CliRunner()


def code(*args: str) -> int:
    return runner.invoke(app, list(args)).exit_code


def _forge(ws: str, root: Path) -> dict:
    out = runner.invoke(
        app, ["forge", str(root), "--workspace", ws, "--yes", "--shared-files", "--json"]
    )
    assert out.exit_code == 0, out.output
    return unwrap(out.stdout)


def test_exit_codes(real_workspace, make_project, tmp_path: Path, monkeypatch) -> None:
    ws = str(real_workspace.root)
    root = make_project("codes", kind="claude")

    assert code("assign", "--workspace", ws) == 2  # usage: missing PATH
    assert code("scan", str(root), "--workspace", str(tmp_path / "nowhere")) == 3
    broken = tmp_path / "broken-reg"
    (broken / "capabilities" / "x.bad").mkdir(parents=True)
    (broken / "capabilities" / "x.bad" / "capability.yaml").write_text("id: [", encoding="utf-8")
    bad_ws = tmp_path / "bad-ws"
    bad_ws.mkdir()
    (bad_ws / "agent-forge.yaml").write_text(
        f"version: 1\nregistry_dir: {broken.as_posix()}\nstate_dir: state\n", encoding="utf-8"
    )
    assert code("catalog", "--workspace", str(bad_ws)) == 4
    assert code("scan", str(tmp_path / "missing"), "--workspace", ws) == 5
    assert code("approve", "plan-20990101-000000-abcdef", "--workspace", ws) == 6

    plan = unwrap(runner.invoke(app, ["assign", str(root), "--workspace", ws, "--json"]).stdout)
    assert code("apply", plan["plan_id"], "--workspace", ws, "--yes") == 8  # never approved
    (root / "CLAUDE.md").write_text("# changed after planning\n", encoding="utf-8")
    assert code("approve", plan["plan_id"], "--workspace", ws, "--shared-files") == 7

    plan2 = unwrap(runner.invoke(app, ["assign", str(root), "--workspace", ws, "--json"]).stdout)
    assert (
        code("approve", plan2["plan_id"], "--workspace", ws, "--shared-files", "--hooks", "--mcp")
        == 0
    )
    with target_lock(real_workspace, plan2["target"]["canonical_path"], "another writer"):
        assert code("apply", plan2["plan_id"], "--workspace", ws, "--yes") == 10

    report = _forge(ws, make_project("codes-rb", kind="claude"))
    tx_id = next(s["transaction_id"] for s in report["steps"] if s.get("transaction_id"))
    store = Store(real_workspace)
    tx = store.load_transaction(tx_id)
    target = Path(tx.target_canonical_path)
    edited = next(o for o in tx.operations if o.path.endswith(".md") and o.before_sha256 is None)
    (target / edited.path).write_text("user edit\n", encoding="utf-8")
    assert code("rollback", tx_id, "--workspace", ws, "--yes") == 11

    with_backup = [o for o in tx.operations if o.backup][-1]  # newest: restored from backup
    with_backup.backup = "../../outside.0123456789ab"
    store.save_transaction(tx)  # re-sealed: a well-formed record pointing outside its backups
    assert code("rollback", tx_id, "--workspace", ws, "--yes", "--partial") == 9

    assert code("validate", str(target), "--workspace", ws) == 12
    assert code("sources", "sync", "ecc", "--workspace", ws) == 13

    plan3 = unwrap(
        runner.invoke(
            app,
            ["assign", str(make_project("codes-af", kind="claude")), "--workspace", ws, "--json"],
        ).stdout
    )
    approval = tmp_path / "approval.yaml"
    approval.write_text(
        "version: 1\napproved_by: ci\napproved_at: '2026-10-20'\nclasses: []\ncapabilities: {}\n",
        encoding="utf-8",
    )
    assert (
        code("approve", plan3["plan_id"], "--workspace", ws, "--approval-file", str(approval)) == 14
    )

    # 15: the coding tool is older than the adapter's verified range (stubbed `claude`)
    from agent_forge.adapters import tool_versions as tv

    class _Old:
        stdout, stderr, returncode = "1.0.0 (Claude Code)", "", 0

    monkeypatch.setattr(tv.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(tv.subprocess, "run", lambda *a, **k: _Old())
    assert code("assign", str(root), "--workspace", ws, "--platform", "claude_code") == 15
