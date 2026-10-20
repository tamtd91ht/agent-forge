"""JSON envelope v1: the one shape every `--json` command prints (6-month plan, phase 4).

    {
      "envelope": 1,
      "command": "agent-forge forge",
      "agent_forge": "0.2.0",
      "generated_at": "2026-10-20T10:00:00+00:00",
      "ok": true,
      "data": { ...the command's document... }
    }

`data` is what the command printed before the envelope existed (plans, transactions,
profiles, lists); documents that are also stored keep their own `schema_version`. `ok` is
false only for commands that report findings and exit non-zero (`validate`, `check`,
`doctor`); errors never produce JSON on stdout (they go to stderr with an exit code).
Automation reads `envelope` first and refuses an unknown value.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: Literal[1] = 1
    command: str = Field(description="Command path, e.g. 'agent-forge catalog show'")
    agent_forge: str = Field(description="Agent Forge version that produced the output")
    generated_at: str = Field(description="ISO-8601 timestamp (UTC)")
    ok: bool = Field(default=True, description="False when the command reports failures")
    data: Any = Field(description="The command's document (object or list)")
