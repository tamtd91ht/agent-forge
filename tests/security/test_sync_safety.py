"""`sync` is a write path: it must refuse an invalid or unsafe managed manifest before any
write and never touch anything outside the project."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_forge.cli import app

pytestmark = pytest.mark.security
runner = CliRunner()


def test_sync_refuses_manifest_with_unsafe_path_and_writes_nothing(
    real_workspace, make_project, tmp_path: Path
) -> None:
    ws = str(real_workspace.root)
    root = make_project("unsafe-sync", kind="claude")
    outside = tmp_path / "outside.md"
    outside.write_text("untouched\n", encoding="utf-8")
    (root / ".agent-forge").mkdir()
    (root / ".agent-forge" / "managed.json").write_text(
        json.dumps(
            {
                "version": "1",
                "capabilities": [
                    {
                        "capability_id": "ecc.tdd-workflow",
                        "version": "1.0.0",
                        "transaction_id": "tx-20260101-000000-abcdef",
                        "installed_at": "2026-01-01T00:00:00+00:00",
                        "files": {"../outside.md": "0" * 64},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    snapshot = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = runner.invoke(app, ["sync", str(root), "--workspace", ws, "--yes"])
    assert result.exit_code == 6, result.output
    assert "invalid" in result.output
    assert outside.read_text(encoding="utf-8") == "untouched\n"
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == snapshot
    tx_dir = Path(ws) / "state" / "transactions"
    assert not tx_dir.exists() or not any(tx_dir.iterdir())
