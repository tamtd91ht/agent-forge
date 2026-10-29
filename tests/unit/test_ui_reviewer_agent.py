"""forge.agent.ui-reviewer: browser-only tools, a read-only audit script that parses, and the
ground rules that keep it off production and away from writes."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from agent_forge.adapters import get_adapter
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.registry.loader import load_registry
from agent_forge.util import parse_frontmatter
from tests.conftest import REAL_REGISTRY

CID = "forge.agent.ui-reviewer"
LC = load_registry(REAL_REGISTRY).get(CID)
PATH = LC.assets_dir / LC.capability.destinations[0].source
TEXT = PATH.read_text(encoding="utf-8")
FM, BODY = parse_frontmatter(TEXT)
SCRIPT = re.search(r"```js\n(.*?)```", BODY, re.S).group(1)


def test_tools_are_read_and_playwright_only() -> None:
    tools = [t.strip() for t in FM["tools"].split(",")]
    assert tools[:3] == ["Read", "Grep", "Glob"]
    assert all(t.startswith("mcp__playwright__browser_") for t in tools[3:])
    assert not {"Bash", "Edit", "Write", "MultiEdit"} & set(tools)
    # no form filling or file upload tools
    assert not any(t.endswith(("fill_form", "type", "file_upload", "select_option")) for t in tools)


def test_manifest_depends_on_the_browser_server_and_declares_it() -> None:
    cap = LC.capability
    assert cap.kind == CapabilityKind.AGENT and cap.platforms == [Platform.CLAUDE_CODE]
    assert any(d.startswith("mcp.playwright") for d in cap.dependencies)
    assert "drives_browser" in [str(p.value if hasattr(p, "value") else p) for p in cap.permissions]
    assert (
        get_adapter(Platform.CLAUDE_CODE).validate_content(
            CapabilityKind.AGENT, cap.destinations[0].dest, TEXT
        )
        == []
    )


def test_ground_rules_are_stated() -> None:
    flat = " ".join(BODY.split())
    for phrase in (
        "Never production",
        "Never submit a form",
        "Never type credentials",
        "do not start servers yourself",
        "Never claim a check you did not perform",
    ):
        assert phrase in flat, phrase


def test_audit_script_only_reads_the_page() -> None:
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        ".submit(",
        ".click(",
        "innerHTML",
        "WebSocket",
    ):
        assert forbidden not in SCRIPT, forbidden
    for key in (
        "lowContrast",
        "offScaleRadius",
        "offScaleFontSize",
        "unlabeledControls",
        "smallTargets",
        "solidActions",
        "horizontalOverflow",
    ):
        assert key in SCRIPT, key


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_audit_script_parses(tmp_path) -> None:
    f = tmp_path / "audit.js"
    f.write_text(f"const audit = {SCRIPT.strip()};\n", encoding="utf-8")
    r = subprocess.run([shutil.which("node"), "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
