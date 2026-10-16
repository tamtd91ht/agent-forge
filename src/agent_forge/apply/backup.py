"""Per-transaction backups of files Agent Forge is about to modify or remove."""

from __future__ import annotations

from pathlib import Path

from agent_forge.util import atomic_write_bytes, sha256_bytes


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

    def load(self, backup_rel: str) -> bytes:
        return (self.dir / backup_rel).read_bytes()

    def exists(self, backup_rel: str) -> bool:
        return (self.dir / backup_rel).is_file()
