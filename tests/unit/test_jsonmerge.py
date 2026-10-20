from __future__ import annotations

import json

import pytest

from agent_forge.apply.jsonmerge import (
    conflicts,
    contains_fragment,
    parse_fragment,
    remove_fragment,
    replace_fragment,
    upsert_fragment,
)
from agent_forge.errors import ApplyError
from tests.conftest import unwrap

HOOK = {
    "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "x"}]}]}
}
MCP = {"mcpServers": {"ctx": {"type": "stdio", "command": "npx", "args": ["-y", "ctx"]}}}
USER = json.dumps(
    {
        "permissions": {"allow": ["Bash(git:*)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "user-stop"}]}]},
        "mcpServers": {"mine": {"command": "mine"}},
    },
    indent=4,
)


def test_upsert_into_missing_file() -> None:
    out = upsert_fragment(None, HOOK)
    assert unwrap(out) == HOOK
    assert contains_fragment(out, HOOK)


def test_upsert_preserves_user_entries_and_is_idempotent() -> None:
    out = upsert_fragment(USER, HOOK)
    data = unwrap(out)
    assert data["permissions"] == {"allow": ["Bash(git:*)"]}
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "user-stop"
    assert data["hooks"]["PostToolUse"] == HOOK["hooks"]["PostToolUse"]
    assert data["mcpServers"]["mine"] == {"command": "mine"}
    assert upsert_fragment(out, HOOK) == out  # no duplicates


def test_remove_restores_semantics() -> None:
    merged = upsert_fragment(USER, HOOK)
    merged = upsert_fragment(merged, MCP)
    back = remove_fragment(remove_fragment(merged, MCP), HOOK)
    assert unwrap(back) == unwrap(USER)
    assert remove_fragment(upsert_fragment(None, MCP), MCP) == ""


def test_mcp_conflict_detected_and_refused() -> None:
    other = json.dumps({"mcpServers": {"ctx": {"command": "different"}}})
    assert conflicts(other, MCP) == ["ctx"]
    with pytest.raises(ApplyError, match="different"):
        upsert_fragment(other, MCP)
    # removal never touches a server that is not ours
    assert unwrap(remove_fragment(other, MCP))["mcpServers"]["ctx"] == {"command": "different"}


def test_replace_fragment_upgrades_in_place() -> None:
    v1 = HOOK
    v2 = {
        "hooks": {
            "PostToolUse": [
                {"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "y"}]}
            ]
        }
    }
    cur = upsert_fragment(USER, v1)
    out = replace_fragment(cur, v1, v2)
    data = unwrap(out)
    assert data["hooks"]["PostToolUse"] == v2["hooks"]["PostToolUse"]
    assert data["hooks"]["Stop"]
    assert contains_fragment(out, v2) and not contains_fragment(out, v1)


@pytest.mark.parametrize(
    "bad",
    [
        "[]",
        "{}",
        '{"other": 1}',
        '{"hooks": []}',
        '{"hooks": {"E": {}}}',
        '{"mcpServers": {"a": 1}}',
        "not json",
    ],
)
def test_parse_fragment_rejects(bad: str) -> None:
    with pytest.raises(ApplyError):
        parse_fragment(bad)


def test_invalid_existing_file_is_refused() -> None:
    with pytest.raises(ApplyError, match="not valid JSON"):
        upsert_fragment("{oops", HOOK, path_hint=".claude/settings.json")
    with pytest.raises(ApplyError, match="JSON object"):
        upsert_fragment("[]", HOOK)
