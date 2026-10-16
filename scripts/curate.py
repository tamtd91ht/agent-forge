"""Reproducible curation: copy reviewed upstream assets into registry/capabilities/<id>/assets/.

This script is the *mechanical* half of curation. The *judgement* half lives in each
capability.yaml (hand-written, reviewed). Re-running the script after `agent-forge sources
sync --update` shows, via `git diff registry/`, exactly what changed upstream so a reviewer
can decide whether to bump versions.

Rules enforced here:
  - only files listed explicitly are copied (never whole directories blindly)
  - the checkout must be at the revision recorded in the manifest's `source.revision`,
    unless --allow-revision-drift is given (then the drift is printed loudly)
  - a license notice file is written next to copied skill/rule assets
  - "adapted" items get an attribution footer; "upstream" items are byte-identical copies

Run:  python scripts/curate.py [--allow-revision-drift] [--only <capability-id>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKOUTS = ROOT / "sources" / "checkouts"
REGISTRY = ROOT / "registry" / "capabilities"

ECC_NOTICE = """This directory contains content from Everything Claude Code (ECC)
https://github.com/affaan-m/ECC — MIT License, Copyright (c) 2026 Affaan Mustafa.
Installed and tracked by Agent Forge; see .agent-forge/managed.json in your project.

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

UIUX_NOTICE = """This directory contains content adapted from UI UX Pro Max
https://github.com/nextlevelbuilder/ui-ux-pro-max-skill — MIT License,
Copyright (c) 2024 Next Level Builder. Adapted by Agent Forge (markdown guidance only;
the upstream search scripts and CSV data are not included).

MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

ECC_AGENT_FOOTER = (
    "\n\n---\n"
    "Source: Everything Claude Code (ECC) agents/{name}.md — MIT License, "
    "Copyright (c) 2026 Affaan Mustafa. Installed by Agent Forge.\n"
)


@dataclass
class Item:
    capability_id: str
    source_id: str
    files: list[tuple[str, str]]  # (upstream relative path, assets relative path)
    notices: list[tuple[str, str]] = field(default_factory=list)  # (assets relative path, text)
    footers: dict[str, str] = field(default_factory=dict)  # assets relative path -> text appended


def _skill(
    cid: str,
    name: str,
    extra: dict[str, str] | None = None,
    platforms: tuple[str, ...] = ("claude_code", "codex"),
) -> Item:
    files: list[tuple[str, str]] = []
    notices: list[tuple[str, str]] = []
    for plat in platforms:
        files.append((f"skills/{name}/SKILL.md", f"{plat}/{name}/SKILL.md"))
        for up, down in (extra or {}).items():
            files.append((up, f"{plat}/{name}/{down}"))
        notices.append((f"{plat}/{name}/LICENSE-ECC.txt", ECC_NOTICE))
    return Item(cid, "ecc", files, notices=notices)


ITEMS: list[Item] = [
    _skill("ecc.tdd-workflow", "tdd-workflow"),
    _skill("ecc.verification-loop", "verification-loop", platforms=("claude_code",)),
    _skill(
        "ecc.security-review",
        "security-review",
        extra={
            "skills/security-review/cloud-infrastructure-security.md": "cloud-infrastructure-security.md"
        },
    ),
    _skill("ecc.coding-standards", "coding-standards"),
    _skill("ecc.error-handling", "error-handling"),
    _skill("ecc.conventional-commit-review", "conventional-commit-review"),
    _skill("ecc.architecture-decision-records", "architecture-decision-records"),
    Item(
        "ecc.agent.planner",
        "ecc",
        [("agents/planner.md", "claude_code/planner.md")],
        footers={"claude_code/planner.md": ECC_AGENT_FOOTER.format(name="planner")},
    ),
    Item(
        "ecc.agent.code-reviewer",
        "ecc",
        [("agents/code-reviewer.md", "claude_code/code-reviewer.md")],
        footers={"claude_code/code-reviewer.md": ECC_AGENT_FOOTER.format(name="code-reviewer")},
    ),
    Item(
        "ecc.rules.common",
        "ecc",
        [
            (f"rules/common/{n}.md", f"claude_code/ecc-common/{n}.md")
            for n in (
                "coding-style",
                "testing",
                "security",
                "code-review",
                "patterns",
                "development-workflow",
            )
        ],
        notices=[("claude_code/ecc-common/LICENSE-ECC.txt", ECC_NOTICE)],
    ),
    # UI/UX guidelines: references are upstream copies; SKILL.md per platform is workspace-authored.
    Item(
        "uiux.guidelines",
        "ui-ux-pro-max",
        [
            (
                ".claude/skills/ui-ux-pro-max/references/quick-reference.md",
                f"{plat}/ui-ux-guidelines/references/quick-reference.md",
            )
            for plat in ("claude_code", "codex")
        ]
        + [
            (
                ".claude/skills/ui-ux-pro-max/references/pro-rules.md",
                f"{plat}/ui-ux-guidelines/references/pro-rules.md",
            )
            for plat in ("claude_code", "codex")
        ],
        notices=[
            (f"{plat}/ui-ux-guidelines/LICENSE-UI-UX-PRO-MAX.txt", UIUX_NOTICE)
            for plat in ("claude_code", "codex")
        ],
    ),
]


def git_head(checkout: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=True
    ).stdout.strip()


def recorded_revision(cid: str) -> str | None:
    manifest = REGISTRY / cid / "capability.yaml"
    if not manifest.is_file():
        return None
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return (data.get("source") or {}).get("revision")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-revision-drift", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()
    drift = 0
    copied = 0
    for item in ITEMS:
        if args.only and item.capability_id != args.only:
            continue
        checkout = CHECKOUTS / item.source_id
        if not (checkout / ".git").exists():
            print(f"!! {item.capability_id}: checkout missing: {checkout}", file=sys.stderr)
            return 2
        head = git_head(checkout)
        rec = recorded_revision(item.capability_id)
        if rec and rec != head:
            drift += 1
            print(
                f"!! {item.capability_id}: manifest records {rec[:12]} but checkout is at {head[:12]}"
            )
            if not args.allow_revision_drift:
                print(
                    "   refusing (use --allow-revision-drift to re-curate, then review `git diff registry/` and bump versions)"
                )
                continue
        assets = REGISTRY / item.capability_id / "assets"
        for up, down in item.files:
            src = checkout / up
            dst = assets / down
            if not src.is_file():
                print(f"!! {item.capability_id}: upstream file missing: {up}", file=sys.stderr)
                return 2
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            if down in item.footers:
                text = text.rstrip("\n") + item.footers[down]
            dst.write_text(text, encoding="utf-8", newline="\n")
            copied += 1
        for rel, text in item.notices:
            (assets / rel).parent.mkdir(parents=True, exist_ok=True)
            (assets / rel).write_text(text, encoding="utf-8", newline="\n")
        print(
            f"ok {item.capability_id}: {len(item.files)} file(s) from {item.source_id}@{head[:12]}"
        )
    print(f"{copied} file(s) copied, {drift} revision drift(s)")
    return 1 if drift and not args.allow_revision_drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
