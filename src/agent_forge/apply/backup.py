"""Per-transaction backups of files Agent Forge is about to modify or remove."""

from __future__ import annotations

import re
from pathlib import Path

from agent_forge.errors import SafetyViolation
from agent_forge.util import atomic_write_bytes, sha256_bytes

# backup names are generated here (`<path with / as __>.<hash12>`); anything else in a
# transaction record is a tampered or foreign value and must not be read
_NAME_RE = re.compile(r"^[^/\\:]+\.[0-9a-f]{12}$")


def valid_backup_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


class BackupStore:
    def __init__(self, backup_dir: Path) -> None:
        self.dir = backup_dir

    def save(self, rel: str, data: bytes) -> tuple[str, str]:
        """Store `data` for `rel`. Returns (backup relative path, sha256)."""
        digest = sha256_bytes(data)
        safe = rel.replace("\\", "/").replace("/", "__")
        name = f"{safe}.{digest[:12]}"
        atomic_write_bytes(self.dir / name, data)
        return name, digest

    def _path(self, backup_rel: str) -> Path:
        if not valid_backup_name(backup_rel):
            raise SafetyViolation(f"invalid backup name in transaction record: {backup_rel!r}")
        return self.dir / backup_rel

    def load(self, backup_rel: str) -> bytes:
        return self._path(backup_rel).read_bytes()

    def exists(self, backup_rel: str) -> bool:
        return self._path(backup_rel).is_file()
