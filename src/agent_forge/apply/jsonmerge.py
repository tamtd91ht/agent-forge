"""Merge/remove JSON *fragments* in settings files (`.claude/settings.json`, `.mcp.json`).

A fragment is a JSON object with one or both top-level keys:

    {"hooks": {"<Event>": [ <matcher group>, ... ]}}
    {"mcpServers": {"<name>": { ...server config... }}}

Semantics (both idempotent):
  upsert: hook groups are appended to the event list unless a deep-equal group already
          exists; MCP servers are set by name — an existing server with a *different*
          config is a conflict and the merge is refused.
  remove: deep-equal hook groups are removed (empty event lists / empty `hooks` are
          dropped); MCP servers are removed only when their config still deep-equals ours.

Everything else in the file (other keys, other hooks, other servers) is preserved. The file
is re-serialised with 2-space indentation, so the diff shows formatting changes only when
the original used a different style.
"""

from __future__ import annotations

import json
from typing import Any

from agent_forge.errors import ApplyError

SUPPORTED_KEYS = ("hooks", "mcpServers")


def _load(text: str | None, path_hint: str = "") -> dict[str, Any]:
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ApplyError(
            f"{path_hint or 'settings file'} is not valid JSON ({exc}); refusing to merge"
        ) from exc
    if not isinstance(data, dict):
        raise ApplyError(f"{path_hint or 'settings file'} must contain a JSON object at top level")
    return data


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def parse_fragment(text: str) -> dict[str, Any]:
    try:
        frag = json.loads(text)
    except ValueError as exc:
        raise ApplyError(f"fragment is not valid JSON: {exc}") from exc
    if not isinstance(frag, dict) or not frag:
        raise ApplyError("fragment must be a non-empty JSON object")
    bad = [k for k in frag if k not in SUPPORTED_KEYS]
    if bad:
        raise ApplyError(f"fragment has unsupported top-level key(s): {', '.join(bad)}")
    hooks = frag.get("hooks")
    if hooks is not None and (
        not isinstance(hooks, dict)
        or not all(
            isinstance(v, list) and all(isinstance(g, dict) for g in v) for v in hooks.values()
        )
    ):
        raise ApplyError("fragment 'hooks' must map event names to lists of matcher groups")
    servers = frag.get("mcpServers")
    if servers is not None and (
        not isinstance(servers, dict) or not all(isinstance(v, dict) for v in servers.values())
    ):
        raise ApplyError("fragment 'mcpServers' must map server names to objects")
    return frag


def contains_fragment(text: str | None, fragment: dict[str, Any]) -> bool:
    data = _load(text)
    for event, groups in (fragment.get("hooks") or {}).items():
        existing = (data.get("hooks") or {}).get(event) or []
        if not isinstance(existing, list) or any(g not in existing for g in groups):
            return False
    servers = data.get("mcpServers") or {}
    return all(servers.get(name) == cfg for name, cfg in (fragment.get("mcpServers") or {}).items())


def conflicts(text: str | None, fragment: dict[str, Any]) -> list[str]:
    """MCP servers that exist with a different configuration (hooks never conflict)."""
    data = _load(text)
    out = []
    for name, cfg in (fragment.get("mcpServers") or {}).items():
        cur = (data.get("mcpServers") or {}).get(name)
        if cur is not None and cur != cfg:
            out.append(name)
    return out


def upsert_fragment(text: str | None, fragment: dict[str, Any], *, path_hint: str = "") -> str:
    data = _load(text, path_hint)
    if "hooks" in fragment:
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ApplyError(f"{path_hint}: existing 'hooks' is not an object; refusing to merge")
        for event, groups in fragment["hooks"].items():
            lst = hooks.setdefault(event, [])
            if not isinstance(lst, list):
                raise ApplyError(f"{path_hint}: existing hooks.{event} is not a list; refusing")
            for g in groups:
                if g not in lst:
                    lst.append(g)
    if "mcpServers" in fragment:
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ApplyError(f"{path_hint}: existing 'mcpServers' is not an object; refusing")
        for name, cfg in fragment["mcpServers"].items():
            cur = servers.get(name)
            if cur is not None and cur != cfg:
                raise ApplyError(
                    f"{path_hint}: MCP server {name!r} already exists with a different "
                    "configuration; remove it or exclude the capability"
                )
            servers[name] = cfg
    return _dump(data)


def remove_fragment(text: str | None, fragment: dict[str, Any], *, path_hint: str = "") -> str:
    data = _load(text, path_hint)
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in (fragment.get("hooks") or {}).items():
            lst = hooks.get(event)
            if not isinstance(lst, list):
                continue
            hooks[event] = [g for g in lst if g not in groups]
            if not hooks[event]:
                del hooks[event]
        if not hooks:
            del data["hooks"]
    servers = data.get("mcpServers")
    if isinstance(servers, dict):
        for name, cfg in (fragment.get("mcpServers") or {}).items():
            if servers.get(name) == cfg:
                del servers[name]
        if not servers:
            del data["mcpServers"]
    return _dump(data) if data else ""


def replace_fragment(
    text: str | None, old: dict[str, Any] | None, new: dict[str, Any], *, path_hint: str = ""
) -> str:
    """Upgrade path: drop the previously merged fragment, then merge the new one."""
    base = remove_fragment(text, old, path_hint=path_hint) if old else text
    return upsert_fragment(base, new, path_hint=path_hint)
