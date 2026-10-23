"""Shared CLI plumbing: consoles, option types, the error-to-exit-code runner, and the
workspace / registry / store accessors every command uses."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from agent_forge import selfupdate
from agent_forge.config import (
    WorkspaceConfig,
    require_workspace,
)
from agent_forge.errors import AgentForgeError, UsageError
from agent_forge.models.capability import Platform

console = Console()

err_console = Console(stderr=True)

WorkspaceOpt = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        help="Agent Forge workspace directory (default: auto-detect).",
        show_default=False,
    ),
]

JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")]


def _run(fn: Callable[[], int | None]) -> None:
    try:
        code = fn()
    except AgentForgeError as exc:
        err_console.print(f"[bold red]error:[/] {exc.message}")
        if exc.hint:
            err_console.print(f"[yellow]hint:[/] {exc.hint}")
        raise typer.Exit(exc.exit_code) from None
    except KeyboardInterrupt:
        err_console.print("[yellow]interrupted[/]")
        raise typer.Exit(130) from None
    if code:
        raise typer.Exit(code)


def _ws(workspace: Path | None) -> WorkspaceConfig:
    return require_workspace(workspace)


def _registry(ws: WorkspaceConfig):
    from agent_forge.registry.loader import load_registries

    return load_registries(ws.registry_layers)


def _store(ws: WorkspaceConfig):
    from agent_forge.storage.transactions import Store

    return Store(ws)


def _platform_list(values: list[str] | None) -> tuple[Platform, ...] | None:
    if not values:
        return None
    out = []
    for v in values:
        try:
            out.append(Platform(v))
        except ValueError:
            raise UsageError(
                f"unknown platform {v!r}; choose from {', '.join(p.value for p in Platform)}"
            ) from None
    return tuple(out)


def _policies(ws: WorkspaceConfig, target_root: Path | None):
    from agent_forge.policy import load_policies

    return load_policies(ws.registry_dir, ws.root, target_root)


def _tool_notes(platforms: list[Platform]) -> list[str]:
    """Refuse an incompatible coding tool (exit 15); note tools that cannot be checked."""
    from agent_forge.adapters.tool_versions import check_tool_compatibility

    return check_tool_compatibility(platforms)


def _ctx(ws, target_root, platforms, want, request, exclude, include_optional):
    from agent_forge.matching.rules import MatchContext

    return MatchContext(
        platforms=platforms,
        wanted_tags=frozenset(want or []),
        requested_ids=frozenset(request or []),
        excluded_ids=frozenset(exclude or []),
        include_optional=include_optional,
        policy=_policies(ws, target_root),
    )


def _audit(store, event: str, **fields) -> None:
    try:
        store.audit.emit(event, **fields)
    except OSError as exc:  # the audit log must never break a command
        err_console.print(f"[yellow]audit log unavailable:[/] {exc}")


APPROVAL_FLAGS = {"shared_file": "--shared-files", "hook": "--hooks", "mcp": "--mcp"}

ENTRY_CAPABILITY = "forge.skill.agent-forge-upgrade"

INSTALLER_REPO = selfupdate.INSTALLER_REPO
