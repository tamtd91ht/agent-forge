"""Phase 4: dependency version constraints, licence-notice check, deprecation notice in status."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from agent_forge.cli import app
from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import Capability, Platform, parse_dependency, version_satisfies
from agent_forge.registry.loader import load_registry
from agent_forge.registry.validator import validate_registry
from agent_forge.scanner.project_profile import scan_project
from tests.conftest import base_manifest, make_workspace, skill_assets, unwrap, write_capability

runner = CliRunner()


def test_parse_and_satisfy() -> None:
    assert parse_dependency("ecc.rules.common") == ("ecc.rules.common", [])
    cid, cons = parse_dependency("ecc.rules.common >=1.1.0, <2.0.0")
    assert cid == "ecc.rules.common" and cons == [(">=", "1.1.0"), ("<", "2.0.0")]
    assert version_satisfies("1.5.0", cons) and not version_satisfies("2.0.0", cons)
    assert version_satisfies("1.9.9", [("^", "1.2.0")]) and not version_satisfies(
        "2.0.0", [("^", "1.2.0")]
    )
    assert version_satisfies("1.2.0", [("==", "1.2.0")])
    for bad in ("", "Bad.Id >=1.0.0", "x.y ~1.0.0", "x.y >=1.0"):
        with pytest.raises(ValueError):
            parse_dependency(bad)
    with pytest.raises(ValidationError):
        Capability.model_validate(base_manifest("t.d", dependencies=["t.a >=1.0.0", "t.a"]))
    cap = Capability.model_validate(base_manifest("t.d", dependencies=["t.a >=2.0.0"]))
    assert cap.dependency_ids == ["t.a"]
    assert (
        cap.unsatisfied_dependency("t.a", "1.0.0") == "t.d requires t.a >=2.0.0, registry has 1.0.0"
    )
    assert cap.unsatisfied_dependency("t.a", "2.1.0") is None


def test_registry_and_matching_enforce_constraints(synthetic_registry: Path, make_project) -> None:
    write_capability(
        synthetic_registry,
        base_manifest("t.needs-new-always", dependencies=["t.always >=9.0.0"]),
        skill_assets("needs-new-always"),
    )
    reg = load_registry(synthetic_registry)
    rr = validate_registry(reg)
    assert any("requires t.always >=9.0.0, registry has 1.0.0" in e for e in rr.errors)
    profile = scan_project(make_project("deps", kind="claude"))
    res = evaluate(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,)))
    rej = next(r for r in res.rejected if r.capability.id == "t.needs-new-always")
    assert rej.category == "dependency_missing" and "registry has 1.0.0" in rej.reasons[0]
    assert "t.needs-always" in {
        c.capability.id for c in res.recommended
    }  # unconstrained still fine


def test_missing_license_notice_is_an_error(synthetic_registry: Path) -> None:
    m = base_manifest("t.notice-missing")
    m["license"]["notice_file"] = "claude_code/LICENSE-X.txt"
    write_capability(synthetic_registry, m, skill_assets("notice-missing"))
    rr = validate_registry(load_registry(synthetic_registry))
    assert any("license.notice_file" in e and "t.notice-missing" in e for e in rr.errors)


def test_status_prints_deprecation_notice(
    tmp_path: Path, synthetic_registry: Path, make_project
) -> None:
    ws = make_workspace(tmp_path / "ws", synthetic_registry)
    root = make_project("dep", kind="claude")
    w = ["--workspace", str(ws.root)]
    report = unwrap(
        runner.invoke(
            app,
            ["forge", str(root), "--yes", "--shared-files", "--json", *w],
            catch_exceptions=False,
        ).stdout
    )
    assert any(s["status"] == "applied" for s in report["steps"])
    manifest = synthetic_registry / "capabilities" / "t.always" / "capability.yaml"
    text = manifest.read_text(encoding="utf-8").replace(
        "status: curated", "status: deprecated\nreplaced_by: t.tagged"
    )
    manifest.write_text(text, encoding="utf-8")
    out = runner.invoke(app, ["status", str(root), *w], catch_exceptions=False)
    assert out.exit_code == 0
    flat = " ".join(out.output.split())
    assert "deprecated: t.always is deprecated in the registry; use t.tagged" in flat
    assert "deprecation-policy.md" in flat
