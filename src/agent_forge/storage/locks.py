"""Per-target exclusive lock around writes (apply, rollback).

One lock file per target project under `<workspace>/state/locks/`, created with O_EXCL so two
processes (or threads) can never write to the same project at once. The file records the
owning pid; a lock whose process is gone is stale and is taken over. A held lock also tells
`validate`/`doctor` that an `in_progress` transaction is really running, not interrupted.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

from agent_forge.config import WorkspaceConfig
from agent_forge.errors import ApplyError
from agent_forge.util import now_iso


def lock_path(ws: WorkspaceConfig, target: str) -> Path:
    key = hashlib.sha256(target.encode("utf-8")).hexdigest()[:24]
    return ws.state_dir / "locks" / f"{key}.lock"


def pid_alive(pid: int) -> bool:
    """True when a process with this pid exists (best effort, never signals it)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder(ws: WorkspaceConfig, target: str) -> dict | None:
    """The live holder of the target's lock, or None (no lock, or a stale one)."""
    path = lock_path(ws, target)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not pid_alive(int(data.get("pid", 0))):
        return None
    return data


def orphaned_locks(ws: WorkspaceConfig) -> list[Path]:
    """Lock files whose owning process no longer exists (read-only; nothing is deleted)."""
    lock_dir = ws.state_dir / "locks"
    if not lock_dir.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(lock_dir.glob("*.lock")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append(path)  # unreadable: no live holder can be proven
            continue
        if not isinstance(data, dict) or not pid_alive(int(data.get("pid", 0) or 0)):
            out.append(path)
    return out


@contextlib.contextmanager
def target_lock(ws: WorkspaceConfig, target: str, purpose: str) -> Iterator[None]:
    path = lock_path(ws, target)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps(
        {"pid": os.getpid(), "purpose": purpose, "since": now_iso(), "target": target}
    )
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            holder = lock_holder(ws, target)
            if holder is not None:
                raise ApplyError(
                    f"another Agent Forge process is writing to this project "
                    f"(pid {holder.get('pid')}, {holder.get('purpose')}, since {holder.get('since')})",
                    hint="Wait for it to finish. If no such process exists, delete " + str(path),
                ) from None
            path.unlink(missing_ok=True)  # stale: its process is gone
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(record)
        break
    else:  # pragma: no cover - lost a takeover race twice
        raise ApplyError(f"could not lock {target}; retry")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
