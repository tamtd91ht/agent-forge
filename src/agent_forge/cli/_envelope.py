"""JSON envelope v1 output and the command path it carries (models/envelope.py)."""

from __future__ import annotations

import json
import sys
from typing import Any

from agent_forge import __version__
from agent_forge.util import now_iso

_COMMAND: list[str] = []


def _print_json(data: Any, *, ok: bool | None = None) -> None:
    """Print the JSON envelope v1 (models/envelope.py) around a command's document.

    Plain stdout on purpose: Rich would wrap long lines and break machine consumers. `ok`
    defaults to the document's own `ok` field when it has one.
    """
    from agent_forge.models.envelope import Envelope

    if ok is None:
        ok = bool(data.get("ok", True)) if isinstance(data, dict) else True
    command = " ".join(_COMMAND) or "agent-forge"
    env = Envelope(
        command=command, agent_forge=__version__, generated_at=now_iso(), ok=ok, data=data
    )
    sys.stdout.write(
        json.dumps(env.model_dump(mode="json"), ensure_ascii=False, default=str, indent=2) + "\n"
    )
    sys.stdout.flush()
