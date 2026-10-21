"""Local usage log: which installed skills and subagents were actually invoked.

`forge.hook.usage-log` (opt-in, Claude Code `PostToolUse`) appends one line per Skill /
Agent call to `<project>/.agent-forge/usage.jsonl`: `{"at", "kind", "id", "session"}`. Nothing
leaves the machine. This module reads that file and maps names back to the managed
capabilities, so `usage`, `status` and the `unused` ground of a decision record can say
"installed 42 days, 0 invocations in 30".

Rules and CLAUDE.md sections are never "invoked"; they are always-on and never appear here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_forge.models.project import ProjectProfile

USAGE_LOG = ".agent-forge/usage.jsonl"
MAX_LOG_BYTES = 8_000_000
DEFAULT_WINDOW_DAYS = 30
MIN_OBSERVED_DAYS = 14  # a capability is `unused` only after this much observation

_SKILL_PATHS = (
    re.compile(r"^\.claude/skills/([^/]+)/SKILL\.md$"),
    re.compile(r"^\.agents/skills/([^/]+)/SKILL\.md$"),
    re.compile(r"^\.github/skills/([^/]+)/SKILL\.md$"),
    re.compile(r"^\.gemini/skills/([^/]+)/SKILL\.md$"),
)
_AGENT_PATHS = (
    re.compile(r"^\.claude/agents/([^/]+)\.md$"),
    re.compile(r"^\.codex/agents/([^/]+)\.md$"),
)


@dataclass(frozen=True)
class UsageEntry:
    at: datetime
    kind: str  # skill | agent
    id: str
    session: str | None


def _parse_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def read_usage(root: Path) -> tuple[bool, list[UsageEntry]]:
    """(log present, entries). Malformed lines are skipped; the read is bounded."""
    path = root / USAGE_LOG
    if path.is_symlink() or not path.is_file():
        return False, []
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_LOG_BYTES)
    except OSError:
        return False, []
    entries: list[UsageEntry] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        at = _parse_at(rec.get("at"))
        kind = rec.get("kind")
        ident = rec.get("id")
        if at is None or kind not in ("skill", "agent") or not isinstance(ident, str) or not ident:
            continue
        session = rec.get("session")
        entries.append(UsageEntry(at, kind, ident, session if isinstance(session, str) else None))
    return True, entries


def managed_names(profile: ProjectProfile) -> dict[tuple[str, str], str]:
    """(kind, name) -> capability id, from the managed manifest's file list."""
    out: dict[tuple[str, str], str] = {}
    for rec in profile.managed:
        for rel in rec.files:
            for pat in _SKILL_PATHS:
                m = pat.match(rel)
                if m:
                    out[("skill", m.group(1))] = rec.capability_id
            for pat in _AGENT_PATHS:
                m = pat.match(rel)
                if m:
                    out[("agent", m.group(1))] = rec.capability_id
    return out


def usage_summary(
    profile: ProjectProfile,
    *,
    since_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = Path(profile.canonical_path)
    now = now or datetime.now(UTC)
    present, entries = read_usage(root)
    cutoff = now - timedelta(days=since_days)
    window = [e for e in entries if e.at >= cutoff]
    first_seen = min((e.at for e in entries), default=None)
    observed_days = (now - first_seen).days if first_seen else 0
    names = managed_names(profile)
    counts: Counter[str] = Counter()
    last: dict[str, datetime] = {}
    sessions: dict[str, set[str]] = {}
    unmanaged: Counter[str] = Counter()
    for e in window:
        cid = names.get((e.kind, e.id))
        if cid is None:
            unmanaged[f"{e.kind}:{e.id}"] += 1
            continue
        counts[cid] += 1
        if cid not in last or e.at > last[cid]:
            last[cid] = e.at
        if e.session:
            sessions.setdefault(cid, set()).add(e.session)
    invocable = {cid for (_kind, _name), cid in names.items()}
    rows: list[dict[str, Any]] = []
    for rec in profile.managed:
        cid = rec.capability_id
        installed_at = _parse_at(rec.installed_at)
        days_installed = (now - installed_at).days if installed_at else None
        kinds = sorted({k for (k, _n), c in names.items() if c == cid})
        unused = (
            present
            and cid in invocable
            and counts[cid] == 0
            and observed_days >= MIN_OBSERVED_DAYS
            and (days_installed or 0) >= MIN_OBSERVED_DAYS
        )
        rows.append(
            {
                "capability": cid,
                "kinds": kinds,
                "invocable": cid in invocable,
                "invocations": counts[cid],
                "sessions": len(sessions.get(cid, ())),
                "last_used": last[cid].isoformat() if cid in last else None,
                "installed_at": rec.installed_at,
                "days_installed": days_installed,
                "unused": unused,
            }
        )
    rows.sort(key=lambda r: (-r["invocations"], r["capability"]))
    return {
        "target": profile.canonical_path,
        "log_present": present,
        "log_path": USAGE_LOG,
        "window_days": since_days,
        "observed_days": observed_days,
        "entries": len(entries),
        "entries_in_window": len(window),
        "min_observed_days": MIN_OBSERVED_DAYS,
        "by_capability": rows,
        "unmanaged": dict(unmanaged.most_common()),
        "unused": [r["capability"] for r in rows if r["unused"]],
    }
