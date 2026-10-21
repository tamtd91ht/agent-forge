"""Organisation-wide decision report: capability x ground across many repositories.

Reads the latest decision record of every repository under the given directories (nothing
else is opened) and tabulates verdicts and grounds. The suggestions are thresholds, not
decisions: a capability skipped as `covered` in most repositories is a candidate to leave the
default catalog, one added almost everywhere on a stack is a candidate for `required`. The
quarterly catalog review (ADR-0008) takes this table as input.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agent_forge.decisions.verify import DECISIONS_DIR, latest_record_path, load_record
from agent_forge.errors import PlanError
from agent_forge.models.decision import DecisionRecord, Verdict

MAX_DEPTH = 4
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "target"}
DROP_THRESHOLD = 0.70  # SKIP covered in >= 70% of the repos that assessed it
REQUIRED_THRESHOLD = 0.90  # ADD / UPGRADE in >= 90% of the repos that assessed it
MIN_REPOS = 3


def find_repositories(dirs: list[Path]) -> list[Path]:
    """Repositories (directories holding `.agent-forge/decisions/`) under `dirs`, bounded."""
    found: list[Path] = []
    seen: set[Path] = set()

    def walk(d: Path, depth: int) -> None:
        if depth > MAX_DEPTH or d.is_symlink():
            return
        if (d / DECISIONS_DIR).is_dir():
            r = d.resolve()
            if r not in seen:
                seen.add(r)
                found.append(d)
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            return
        for c in children:
            if c.name in _SKIP_DIRS or (c.name.startswith(".") and c.name != ".agent-forge"):
                continue
            walk(c, depth + 1)

    for d in dirs:
        walk(d, 0)
    return found


def org_report(dirs: list[Path]) -> dict[str, Any]:
    repos = find_repositories(dirs)
    records: list[tuple[Path, DecisionRecord]] = []
    problems: list[str] = []
    for repo in repos:
        path = latest_record_path(repo)
        if path is None:
            continue
        try:
            records.append((repo, load_record(path)))
        except PlanError as exc:
            problems.append(exc.message)
    verdicts: dict[str, Counter[str]] = defaultdict(Counter)
    grounds: dict[str, Counter[str]] = defaultdict(Counter)
    assessed_in: dict[str, int] = Counter()
    for _repo, rec in records:
        for d in rec.decisions:
            assessed_in[d.capability_id] += 1
            verdicts[d.capability_id][d.verdict.value] += 1
            for g in d.grounds:
                grounds[d.capability_id][g.value] += 1
    rows: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    for cid in sorted(assessed_in):
        n = assessed_in[cid]
        v = verdicts[cid]
        g = grounds[cid]
        rows.append(
            {
                "capability": cid,
                "repos": n,
                "verdicts": dict(sorted(v.items())),
                "grounds": dict(sorted(g.items())),
            }
        )
        if n >= MIN_REPOS:
            covered = g["covered"] / n
            if v[Verdict.SKIP.value] / n >= DROP_THRESHOLD and covered >= DROP_THRESHOLD:
                suggestions.append(
                    {
                        "capability": cid,
                        "suggestion": "candidate to leave the default catalog",
                        "why": f"SKIP as covered in {g['covered']} of {n} repositories",
                    }
                )
            adds = (v[Verdict.ADD.value] + v[Verdict.UPGRADE.value]) / n
            if adds >= REQUIRED_THRESHOLD:
                suggestions.append(
                    {
                        "capability": cid,
                        "suggestion": "candidate for `capabilities.required`",
                        "why": f"ADD/UPGRADE in {v['ADD'] + v['UPGRADE']} of {n} repositories",
                    }
                )
    return {
        "directories": [str(d) for d in dirs],
        "repositories": [str(r) for r, _ in records],
        "records": len(records),
        "problems": problems,
        "thresholds": {
            "drop": DROP_THRESHOLD,
            "required": REQUIRED_THRESHOLD,
            "min_repos": MIN_REPOS,
        },
        "capabilities": rows,
        "suggestions": suggestions,
    }
