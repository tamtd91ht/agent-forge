"""Agent Forge hook (PreToolUse, Edit|Write|MultiEdit): refuse edits to secret-looking files.

Reads the hook payload from stdin, inspects `tool_input.file_path`, and exits with code 2
(which blocks the tool call and feeds stderr back to the agent) when the file looks like a
credential store. Never reads the file itself. Standard library only.
"""

from __future__ import annotations

import json
import sys

SECRET_NAMES = {".env", ".envrc", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa"}
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret")
SECRET_PREFIXES = (".env.", "credentials", "secrets")
ALLOWED = {".env.example", ".env.sample", ".env.template", ".env.dist"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # malformed payload: never block on our own bug
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    path = str((tool_input or {}).get("file_path") or "")
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not name or name in ALLOWED:
        return 0
    if name in SECRET_NAMES or name.startswith(SECRET_PREFIXES) or name.endswith(SECRET_SUFFIXES):
        sys.stderr.write(
            f"agent-forge guard: refusing to edit secret-looking file {path}. "
            "Ask the user to change credentials by hand.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
