"""The workspace-authored design-token guard, run exactly as Claude Code would run it."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.conftest import REAL_REGISTRY

SCRIPT = (
    REAL_REGISTRY
    / "capabilities/forge.hook.design-token-guard/assets/claude_code/scripts/design_token_guard.mjs"
)
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _run(tool_input: dict | str, tool: str = "Write") -> subprocess.CompletedProcess[str]:
    payload = (
        tool_input
        if isinstance(tool_input, str)
        else json.dumps({"tool_name": tool, "tool_input": tool_input})
    )
    return subprocess.run(
        [str(NODE), str(SCRIPT)], input=payload, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("src/components/Button.tsx", '<div style={{ color: "#1e3150" }} />'),
        ("src/components/Card.tsx", 'className="bg-[#f5f6fa] rounded-[20px]"'),
        ("src/app/page.module.css", ".title { color: #333; }"),
        ("src/ui/Badge.vue", "<style>.b { background: rgba(255, 89, 85, 0.1); }</style>"),
        (
            "mobile/screens/Home.tsx",
            "const s = StyleSheet.create({ a: { borderColor: '#E7EAF0' } });",
        ),
        ("src/x.scss", "a { color: hsl(200, 100%, 50%); }"),
    ],
)
def test_raw_colour_in_ui_file_warns(path: str, text: str) -> None:
    r = _run({"file_path": path, "content": text})
    assert r.returncode == 2, (path, text)
    assert "design-token-guard (PostToolUse warning" in r.stderr
    assert "line 1:" in r.stderr


def test_known_value_names_its_token() -> None:
    r = _run({"file_path": "src/A.tsx", "content": 'const c = "#56CC6E";'})
    assert r.returncode == 2 and "-> use token: success" in r.stderr


def test_edit_and_multiedit_payloads_are_read() -> None:
    assert _run({"file_path": "src/A.tsx", "new_string": "color: '#fff'"}, "Edit").returncode == 2
    multi = {
        "file_path": "src/A.tsx",
        "edits": [{"old_string": "a", "new_string": "fill='#00b1ff'"}],
    }
    assert _run(multi, "MultiEdit").returncode == 2


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (
            "src/components/Button.tsx",
            '<button className="bg-success text-white rounded-medium" />',
        ),
        ("src/components/Button.tsx", 'style={{ color: "var(--primary)" }}'),
        ("src/app/globals.css", ":root { --primary: #1e3150; }"),
        ("src/styles/tokens.css", ".x { color: #1e3150; }"),
        ("src/theme/index.ts", "primary: '#1e3150',"),
        ("tailwind.config.ts", "primary: '#1e3150'"),
        ("src/components/Button.test.tsx", 'expect(color).toBe("#1e3150")'),
        ("src/components/Button.stories.tsx", 'args: { color: "#1e3150" }'),
        ("src/A.css", "  --surface: #ffffff;"),
        ("src/A.tsx", "// was #1e3150 in the mock-up"),
        ("src/A.tsx", 'const brand = "#ff0000"; // design-token-ok: partner logo colour'),
        ("src/A.tsx", '<a href="#top">Top</a> <a href="#section-2">x</a>'),
        ("src/A.tsx", "const entity = '&#123;';"),
        ("src/server/handler.py", 'color = "#1e3150"'),
        ("README.md", "Primary is `#1e3150`."),
    ],
)
def test_tokens_theme_files_and_non_ui_text_pass(path: str, text: str) -> None:
    r = _run({"file_path": path, "content": text})
    assert r.returncode == 0, (path, text, r.stderr)
    assert r.stderr == ""


def test_report_is_capped() -> None:
    text = "\n".join(f".c{i} {{ color: #{i:06x}; }}" for i in range(20))
    r = _run({"file_path": "src/a.css", "content": text})
    assert r.returncode == 2 and r.stderr.count("  line ") == 8


@pytest.mark.parametrize("payload", ["", "not json", "[]", '{"tool_input": 5}', "{}"])
def test_malformed_payload_fails_open(payload: str) -> None:
    assert _run(payload).returncode == 0
