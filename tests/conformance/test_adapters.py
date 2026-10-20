"""Adapter conformance: every platform adapter honours the same contract (roadmap E5).

A new adapter is supported only when this suite passes for it unchanged.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from agent_forge.adapters import all_adapters, platform_owning
from agent_forge.adapters.base import PlatformAdapter
from agent_forge.models.capability import CapabilityKind
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.filesystem import Walker
from tests.conftest import REAL_REGISTRY

ADAPTERS = all_adapters()
IDS = [a.platform.value for a in ADAPTERS]


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_declares_its_contract(adapter: PlatformAdapter) -> None:
    info = adapter.info
    assert info.display_name and info.docs_url.startswith("https://")
    date.fromisoformat(info.verified_on)  # when the conventions were last checked
    assert info.supported_kinds, "an adapter must support at least one kind"
    assert ".agent-forge/" in info.managed_roots
    for kind in CapabilityKind:
        if kind not in info.supported_kinds:
            # unsupported kinds are explained, not silently dropped
            assert any(n.startswith(kind.value) for n in info.unsupported_notes) or (
                kind == CapabilityKind.REFERENCE  # never installed on any platform
            ), f"{kind.value} unsupported without a note"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_shared_files_are_managed_and_owned(adapter: PlatformAdapter) -> None:
    for f in adapter.info.shared_files:
        assert adapter.path_allowed(f), f
        assert adapter.is_shared_file(f)
        assert platform_owning(f) == adapter.platform, f


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_roots_map_back_to_exactly_this_adapter(adapter: PlatformAdapter) -> None:
    for root in adapter.info.managed_roots:
        probe = root + "probe.md" if root.endswith("/") else root
        if root == ".agent-forge/":
            assert platform_owning(probe) is None  # shared by every adapter
        else:
            assert platform_owning(probe) == adapter.platform, root
    assert not adapter.path_allowed("README.md")
    assert not adapter.path_allowed("src/app.py")


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_empty_project_has_no_evidence(adapter: PlatformAdapter, tmp_path: Path) -> None:
    walker = Walker(tmp_path, max_files=100, max_depth=5, max_file_bytes=1000)
    walker.ensure_walked()
    assert adapter.detect(walker) is None
    assert adapter.collect_assets(walker) == []


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_every_registry_destination_fits_the_adapter(adapter: PlatformAdapter) -> None:
    reg = load_registry(REAL_REGISTRY)
    for cap in reg.capabilities():
        for d in cap.destinations_for(adapter.platform):
            assert adapter.supports(cap.kind), f"{cap.id}: {cap.kind.value} unsupported"
            assert adapter.owns(d.dest) or adapter.owns(d.dest.rstrip("/") + "/x"), (
                f"{cap.id}: {d.dest} outside {adapter.platform.value} roots"
            )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=IDS)
def test_validate_content_rejects_wrong_places(adapter: PlatformAdapter) -> None:
    skill = "---\nname: x\ndescription: d\n---\n# x\nbody\n"
    assert adapter.validate_content(CapabilityKind.SKILL, "README.md", skill)
    if CapabilityKind.INSTRUCTION in adapter.info.supported_kinds:
        assert adapter.validate_content(CapabilityKind.INSTRUCTION, "docs/notes.md", "# x\nbody\n")
