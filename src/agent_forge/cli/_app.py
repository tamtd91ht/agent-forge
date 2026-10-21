"""The Typer application and its sub-applications; the root callback (--version, command path)."""

from __future__ import annotations

from typing import Annotated

import typer

from agent_forge import __version__
from agent_forge.cli._common import console
from agent_forge.cli._envelope import _COMMAND

app = typer.Typer(
    name="agent-forge",
    help="Local-first, approval-first AI-agent capability engineering. "
    "Workflow: scan -> assign -> diff -> approve -> apply -> validate.",
    no_args_is_help=True,
    invoke_without_command=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

sources_app = typer.Typer(
    help="Manage approved upstream sources (clone, status, sync). Never installs."
)

catalog_app = typer.Typer(
    help="Browse the curated capability registry.", invoke_without_command=True
)

decisions_app = typer.Typer(
    help="Read, verify and summarise the agent's decision records (ADR-0007). Read-only."
)

app.add_typer(sources_app, name="sources")

app.add_typer(catalog_app, name="catalog")

app.add_typer(decisions_app, name="decisions")


@app.callback()
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", "-V", help="Show version and exit.", is_eager=True)
    ] = False,
) -> None:
    if version:
        console.print(f"agent-forge {__version__}")
        raise typer.Exit()
    _COMMAND[:] = ["agent-forge", *([ctx.invoked_subcommand] if ctx.invoked_subcommand else [])]
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
