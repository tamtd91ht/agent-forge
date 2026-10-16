"""Agent Forge hook (PostToolUse, Edit|Write|MultiEdit): format the edited Python file with ruff.

No-op (exit 0) when the file is not .py/.pyi or when ruff is not installed, so the hook never
blocks work. Runs `ruff format` on the single edited file only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    path = str((tool_input or {}).get("file_path") or "")
    if not path.lower().endswith((".py", ".pyi")):
        return 0
    ruff = shutil.which("ruff")
    if ruff is None:
        return 0
    subprocess.run([ruff, "format", "--quiet", "--", path], check=False, timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main())
