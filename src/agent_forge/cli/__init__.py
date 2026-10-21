"""Agent Forge command line (Typer). The package registers one module per command group;
`app` and `main` are what the entry point and the tests use.

Layout: `_app` (Typer apps and root callback) · `_common` (consoles, option types, runner,
accessors) · `_envelope` (JSON envelope) · `_tables` (Rich renderers) · `registry`, `plans`,
`forge`, `ops`, `doctor`, `team`, `decisions`, `lint` (commands).
"""

from __future__ import annotations

import contextlib
import sys
from importlib import resources  # noqa: F401  (tests patch `cli.resources.files` for the seed)

# Importing a command module registers its commands on `app`; order = `--help` order.
from agent_forge.cli import (  # noqa: F401
    decisions,
    doctor,
    forge,
    lint,
    ops,
    plans,
    registry,
    team,
)
from agent_forge.cli._app import app

__all__ = ["app", "main"]


def main() -> None:
    # Windows consoles default to a legacy code page; plans and skills contain Unicode.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # closed or exotic streams
                reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
