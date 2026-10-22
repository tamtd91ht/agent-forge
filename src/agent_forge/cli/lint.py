"""`agent-forge lint`: score a project's existing agent configuration (ADR-0007)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from agent_forge.cli._app import app
from agent_forge.cli._common import JsonOpt, _run, console
from agent_forge.cli._envelope import _print_json
from agent_forge.errors import ValidationFailed


@app.command()
def lint(
    path: Annotated[Path, typer.Argument(help="Project directory.")],
    max_context: Annotated[
        int | None,
        typer.Option(
            "--max-context",
            help="Fail (exit 12) when the always-loaded context exceeds this many characters.",
            min=0,
        ),
    ] = None,
    as_json: JsonOpt = False,
) -> int:
    """Score the agent configuration a project already has: always-loaded context per file,
    duplicate rules, credentials in agent files, hooks that run flagged commands, MCP servers
    defined but disabled, dead references, overclaimed counts, overlapping skill descriptions,
    missing frontmatter. Read-only, no workspace or catalog needed, proposes nothing."""

    def body() -> int:
        from agent_forge.lint import lint_project

        rep = lint_project(path, max_context=max_context)
        if as_json:
            _print_json(rep.to_dict())
            return 0 if rep.ok else ValidationFailed.exit_code
        console.print(
            f"[bold]{rep.target}[/]  platforms: {', '.join(rep.platforms) or 'none'}  "
            f"assets: {rep.counts.get('assets', 0)} ({rep.counts.get('managed', 0)} managed)  "
            f"hooks: {rep.counts.get('hooks', 0)}  mcp: {rep.counts.get('mcp_servers', 0)}"
        )
        t = Table(
            title=f"always-loaded context: {rep.always_on_total} chars (~{rep.always_on_total // 4} tokens)"
        )
        for col in ("chars", "file", "why"):
            t.add_column(col, overflow="fold")
        for f in rep.files:
            if f.chars:
                t.add_row(str(f.chars), f.path, f.reason)
        console.print(t)
        for f in rep.findings:
            color = {"error": "red", "warning": "yellow", "info": "dim"}[f.level]
            console.print(f"[{color}]{f.level:7}[/] [{f.check}] {f.path}: {f.message}")
        console.print(
            f"{len(rep.errors)} error(s), {len(rep.findings) - len(rep.errors)} warning(s): "
            + ("[green]OK[/]" if rep.ok else "[red]FAILED[/]")
        )
        return 0 if rep.ok else ValidationFailed.exit_code

    _run(body)
    return 0
