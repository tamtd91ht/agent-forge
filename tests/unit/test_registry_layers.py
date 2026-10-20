"""Several registries with priority (6-month plan, phase 1): a team registry layered over
the core one; a duplicate id resolves to the higher-priority layer and is reported."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_forge.config import load_workspace
from agent_forge.errors import WorkspaceError
from agent_forge.registry.loader import load_registries, load_registry
from agent_forge.validation.engine import validate_workspace
from tests.conftest import base_manifest, make_workspace, skill_assets, write_capability


def _team_registry(tmp_path: Path) -> Path:
    team = tmp_path / "team-registry"
    (team / "capabilities").mkdir(parents=True)
    # overrides a core id with a different body, and adds one of its own
    write_capability(team, base_manifest("t.always"), skill_assets("always", "Team variant."))
    write_capability(team, base_manifest("team.only"), skill_assets("only"))
    return team


def test_team_registry_wins_on_duplicate_id_and_is_reported(
    synthetic_registry: Path, tmp_path: Path
) -> None:
    team = _team_registry(tmp_path)
    core_only = load_registry(synthetic_registry)
    merged = load_registries([("team", team), ("core", synthetic_registry)])
    assert merged.items["t.always"].registry == "team"
    assert merged.items["t.always"].directory == team / "capabilities" / "t.always"
    assert merged.items["team.only"].registry == "team"
    assert merged.items["t.python-only"].registry == "core"
    assert merged.shadowed == [("t.always", "team", "core")]
    assert set(core_only.items) < set(merged.items)
    # the override is part of the registry state plans bind to
    assert merged.digest != core_only.digest


def test_workspace_config_parses_registries_in_priority_order(
    synthetic_registry: Path, tmp_path: Path
) -> None:
    team = _team_registry(tmp_path)
    ws = make_workspace(tmp_path / "ws", synthetic_registry)
    cfg = yaml.safe_load(ws.marker.read_text(encoding="utf-8"))
    cfg["registries"] = [{"name": "team", "path": str(team)}, str(tmp_path / "other")]
    ws.marker.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    ws = load_workspace(ws.root)
    assert [n for n, _ in ws.registry_layers] == ["team", "registry2", "core"]
    assert ws.registry_layers[-1][1] == synthetic_registry.resolve()

    for bad in ([{"name": "core", "path": str(team)}], [{"path": 3}], "not-a-list"):
        cfg["registries"] = bad
        ws.marker.write_text(yaml.safe_dump(cfg), encoding="utf-8")
        with pytest.raises(WorkspaceError):
            load_workspace(ws.root)


def test_validate_warns_about_shadowed_capabilities(
    synthetic_registry: Path, tmp_path: Path
) -> None:
    team = _team_registry(tmp_path)
    ws = make_workspace(tmp_path / "ws", synthetic_registry)
    merged = load_registries([("team", team), ("core", synthetic_registry)])
    rep = validate_workspace(ws, merged, provenance=False)
    assert any("t.always" in w.message and "'team' wins" in w.message for w in rep.warnings)
    assert rep.ok  # a shadow is a warning, not an error
