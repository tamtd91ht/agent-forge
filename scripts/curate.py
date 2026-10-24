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
import re
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

KARPATHY_NOTICE = """This directory contains content from andrej-karpathy-skills
https://github.com/multica-ai/andrej-karpathy-skills — MIT License, Copyright (c) forrestchang.
The upstream repository declares MIT in its README and SKILL.md frontmatter but ships no
LICENSE file; the standard MIT text is reproduced below.
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

MATTPOCOCK_NOTICE = """This directory contains content from Skills For Real Engineers
https://github.com/mattpocock/skills — MIT License, Copyright (c) 2026 Matt Pocock.
Installed and tracked by Agent Forge; see .agent-forge/managed.json in your project.

MIT License

Copyright (c) 2026 Matt Pocock

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

SUPERPOWERS_NOTICE = """This directory contains content from Superpowers
https://github.com/obra/superpowers — MIT License, Copyright (c) 2025 Jesse Vincent.
Installed and tracked by Agent Forge; see .agent-forge/managed.json in your project.

MIT License

Copyright (c) 2025 Jesse Vincent

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

PONYTAIL_NOTICE = """This directory contains content from Ponytail
https://github.com/dietrichgebert/ponytail — MIT License, Copyright (c) 2026 DietrichGebert.
Installed and tracked by Agent Forge; see .agent-forge/managed.json in your project.

MIT License

Copyright (c) 2026 DietrichGebert

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

MATTPOCOCK_FOOTER = (
    "\n\n---\n"
    "Adapted by Agent Forge from mattpocock/skills {path} (MIT License, "
    "Copyright (c) 2026 Matt Pocock).\n"
)

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
    # assets relative path -> exact (old, new) replacements; a missing `old` fails the run so an
    # upstream change to an adapted passage is reviewed instead of silently skipped
    replacements: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # rewrite relative markdown links to sibling skills / rule packs into plain names, because
    # a skill is installed on its own and its neighbours may not be (see _rewrite_links)
    rewrite_links: bool = False
    # hand-adapted assets (edits not expressible as replacements): the run checks that the
    # upstream files still exist at the recorded revision but never overwrites the copies
    frozen: bool = False
    # assets relative SKILL.md path -> sections moved verbatim into references/ (see Split)
    splits: dict[str, list[Split]] = field(default_factory=dict)


@dataclass(frozen=True)
class Split:
    """Move one section of a SKILL.md verbatim into `references/<file>`.

    The section runs from its exact heading line to the next heading of the same or a higher
    level (fenced code ignored). The heading stays, followed by a pointer saying when to read
    the file, so nothing is lost and the skill stays under the post-compaction cut (ADR-0012).
    A heading that no longer exists upstream fails the run.
    """

    heading: str
    file: str
    when: str


def _mp_skill(
    cid: str,
    upstream_dir: str,
    files: tuple[str, ...] = (),
    rename: str | None = None,
    replacements: list[tuple[str, str]] | None = None,
) -> Item:
    """A mattpocock/skills skill for both platforms; Codex also gets agents/openai.yaml.

    `rename` installs the skill under a different name; renaming or `replacements` make the
    item adapted, which adds an attribution footer to SKILL.md.
    """
    upstream_name = upstream_dir.rsplit("/", 1)[-1]
    name = rename or upstream_name
    up = f"skills/{upstream_dir}"
    edits = list(replacements or [])
    if rename:
        edits.insert(0, (f"name: {upstream_name}\n", f"name: {rename}\n"))
    item = Item(cid, "mattpocock", [])
    for plat in ("claude_code", "codex"):
        base = f"{plat}/{name}"
        item.files.append((f"{up}/SKILL.md", f"{base}/SKILL.md"))
        item.files.extend((f"{up}/{f}", f"{base}/{f}") for f in files)
        if plat == "codex":
            item.files.append((f"{up}/agents/openai.yaml", f"{base}/agents/openai.yaml"))
        item.notices.append((f"{base}/LICENSE-MATTPOCOCK.txt", MATTPOCOCK_NOTICE))
        if edits:
            item.replacements[f"{base}/SKILL.md"] = edits
            item.footers[f"{base}/SKILL.md"] = MATTPOCOCK_FOOTER.format(path=f"{up}/SKILL.md")
    return item


def _sp_skill(cid: str, name: str) -> Item:
    """A self-contained obra/superpowers skill, verbatim, for both platforms."""
    item = Item(cid, "superpowers", [])
    for plat in ("claude_code", "codex"):
        item.files.append((f"skills/{name}/SKILL.md", f"{plat}/{name}/SKILL.md"))
        item.notices.append((f"{plat}/{name}/LICENSE-SUPERPOWERS.txt", SUPERPOWERS_NOTICE))
    return item


def _pt_skill(cid: str, name: str) -> Item:
    """A dietrichgebert/ponytail skill, verbatim, for both platforms."""
    item = Item(cid, "ponytail", [])
    for plat in ("claude_code", "codex"):
        item.files.append((f"skills/{name}/SKILL.md", f"{plat}/{name}/SKILL.md"))
        item.notices.append((f"{plat}/{name}/LICENSE-PONYTAIL.txt", PONYTAIL_NOTICE))
    return item


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
        # 1.1.0 removed ECC's agent roster, the links to excluded files and the mandatory
        # research step by hand (see the manifest notes); re-copying would undo that.
        frozen=True,
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
    # mattpocock/skills: self-contained skills only (nothing that needs
    # setup-matt-pocock-skills). Cross-skill calls are covered by manifest dependencies.
    _mp_skill(
        "mattpocock.diagnosing-bugs",
        "engineering/diagnosing-bugs",
        files=("scripts/hitl-loop.template.sh",),
    ),
    _mp_skill("mattpocock.grilling", "productivity/grilling"),
    _mp_skill(
        "mattpocock.domain-modeling",
        "engineering/domain-modeling",
        files=("ADR-FORMAT.md", "GLOSSARY-FORMAT.md"),
    ),
    _mp_skill(
        "mattpocock.codebase-design",
        "engineering/codebase-design",
        files=("DEEPENING.md", "DESIGN-IT-TWICE.md"),
    ),
    _mp_skill("mattpocock.grill-with-docs", "engineering/grill-with-docs"),
    _mp_skill(
        "mattpocock.writing-for-agents",
        "productivity/writing-for-agents",
        files=("SKILL-MECHANICS.md",),
    ),
    # Renamed: `code-review` collides with harness built-ins (Claude Code ships one).
    # The setup-matt-pocock-skills precondition is replaced by the project's own docs.
    _mp_skill(
        "mattpocock.two-axis-review",
        "engineering/code-review",
        rename="two-axis-review",
        replacements=[
            (
                "The issue tracker should have been provided to you. If "
                "`docs/agents/issue-tracker.md` is missing, tell the user to run "
                "`/setup-matt-pocock-skills`.",
                "If the project documents how to work with its issue tracker (for example "
                "`docs/agents/issue-tracker.md`, `CONTRIBUTING.md`, or `CLAUDE.md` / "
                "`AGENTS.md`), follow that workflow when fetching issues.",
            ),
            (
                "fetched via the workflow in `docs/agents/issue-tracker.md`.",
                "fetched with the project's issue tracker workflow (for example `gh issue view`"
                " or `glab issue view`).",
            ),
        ],
    ),
    _mp_skill(
        "mattpocock.tdd",
        "engineering/tdd",
        files=("tests.md", "mocking.md"),
        replacements=[
            (
                "(see the `code-review` skill)",
                "(see the `two-axis-review` skill when it is installed)",
            )
        ],
    ),
    # obra/superpowers: only skills that name no other skill and run nothing.
    _sp_skill("superpowers.verification-before-completion", "verification-before-completion"),
    _sp_skill("superpowers.receiving-code-review", "receiving-code-review"),
    # dietrichgebert/ponytail: the three skills that run nothing and need no plugin runtime.
    # gain, help and the hooks / band are rejected (docs/rejections/ponytail-hooks-and-runtime.md).
    _pt_skill("ponytail.lazy-senior-dev", "ponytail"),
    _pt_skill("ponytail.shortcut-debt", "ponytail-debt"),
    _pt_skill("ponytail.review", "ponytail-review"),
    # Karpathy guidelines: verbatim skill. The always-on CLAUDE.md/AGENTS.md section
    # (karpathy.principles) is adapted by hand from upstream CLAUDE.md, not copied here.
    Item(
        "karpathy.guidelines",
        "karpathy",
        [
            (
                "skills/karpathy-guidelines/SKILL.md",
                f"{plat}/karpathy-guidelines/SKILL.md",
            )
            for plat in ("claude_code", "codex")
        ],
        notices=[
            (f"{plat}/karpathy-guidelines/LICENSE-KARPATHY.txt", KARPATHY_NOTICE)
            for plat in ("claude_code", "codex")
        ],
    ),
]


# ---- ECC per-stack content (0.4.0) ---------------------------------------------------------
#
# Language rule packs: every file carries `paths:` frontmatter, so they load only for matching
# files and cost no always-loaded context (ADR-0003). `hooks.md` is excluded everywhere: it
# documents ECC's own hooks in ~/.claude/settings.json. The "extends common/x.md" link in each
# file points at a path that does not exist once installed; it is rewritten to name the
# capability that ships those files instead (adapted, see each manifest).
#
# (registry id suffix, upstream rules dir, files besides the four standard ones)
ECC_RULE_PACKS: list[tuple[str, str, tuple[str, ...]]] = [
    ("golang", "golang", ()),
    ("typescript", "typescript", ()),
    ("python", "python", ("fastapi",)),
    ("java", "java", ()),
    ("kotlin", "kotlin", ()),
    ("rust", "rust", ()),
    ("csharp", "csharp", ()),
    ("php", "php", ()),
    ("ruby", "ruby", ()),
    ("swift", "swift", ()),
    ("dart", "dart", ()),
    ("cpp", "cpp", ()),
    ("react", "react", ()),
    ("vue", "vue", ()),
    ("nuxt", "nuxt", ()),
    ("angular", "angular", ()),
    ("react-native", "react-native", ("accessibility", "performance", "production-readiness")),
    ("web", "web", ("design-quality", "performance")),
    ("fsharp", "fsharp", ()),
    ("perl", "perl", ()),
    ("arkts", "arkts", ()),
]
RULE_PACK_STANDARD_FILES = ("coding-style", "patterns", "security", "testing")

# Stack-specific skills: one SKILL.md each, verbatim (upstream), no scripts. Which project
# gets which one is decided by the manifest's applicability, not here.
ECC_STACK_SKILLS: list[str] = [
    # JVM
    "java-coding-standards", "springboot-patterns", "springboot-tdd", "springboot-security",
    "springboot-verification", "jpa-patterns", "quarkus-security", "hexagonal-architecture",
    "kotlin-patterns", "kotlin-testing", "kotlin-coroutines-flows", "kotlin-ktor-patterns",
    "kotlin-exposed-patterns", "android-clean-architecture", "compose-multiplatform-patterns",
    # Go
    "golang-patterns", "golang-testing",
    # Node / TypeScript
    "nestjs-patterns", "react-patterns", "react-testing", "react-performance",
    "frontend-patterns", "frontend-a11y", "nextjs-turbopack", "vue-patterns", "nuxt4-patterns",
    "vite-patterns", "prisma-patterns", "e2e-testing", "react-native-patterns",
    # Python
    "python-patterns", "python-testing", "fastapi-patterns", "django-patterns", "django-tdd",
    "django-security", "django-verification", "django-celery",
    # Rust, .NET, PHP, Ruby
    "rust-patterns", "rust-testing", "dotnet-patterns", "csharp-testing", "fsharp-testing",
    "laravel-patterns", "laravel-tdd", "laravel-security", "laravel-verification", "rails-patterns",
    # Swift, Dart, C++, Perl
    "swiftui-patterns", "swift-concurrency-6-2", "swift-protocol-di-testing",
    "swift-actor-persistence", "dart-flutter-patterns", "flutter-dart-code-review",
    "cpp-coding-standards", "cpp-testing", "perl-patterns", "perl-security", "perl-testing",
    # data, infrastructure, cross-cutting
    "redis-patterns", "postgres-patterns", "mysql-patterns", "database-migrations",
    "kubernetes-patterns", "deployment-patterns", "api-design", "backend-patterns", "accessibility",
]  # fmt: skip

_REL_LINK_RE = re.compile(r"\[([^\]]+)\]\((\.\.?/[^)#\s]+)\)")


def _rewrite_links(text: str) -> str:
    """Relative links to sibling ECC skills / rule packs become names, not paths.

    Installed alone, `../react-testing/SKILL.md` or `../../rules/react/` points nowhere. The
    link text is kept and the target is named as the capability that ships it, so the agent
    can still ask for it (`--request ecc.<name>`) and `validate`'s link check passes.
    """

    def sub(m: re.Match[str]) -> str:
        label, target = m.group(1), m.group(2)
        if sk := re.fullmatch(r"(?:\.\./)+(?:skills/)?([a-z0-9-]+)/SKILL\.md", target):
            return (
                f"{label} (ECC skill `{sk.group(1)}`; capability `ecc.{sk.group(1)}` when curated)"
            )
        if rp := re.fullmatch(r"(?:\.\./)+(?:rules/)?([a-z-]+)/(?:[a-z-]+\.md)?", target):
            return f"{label} (`ecc.rules.{rp.group(1)}`)"
        if re.fullmatch(r"\./hooks\.md", target):
            return f"{label} (hooks are not installed by this pack; see the project's own hooks)"
        return label

    return _REL_LINK_RE.sub(sub, text)


_HEADING_RE = re.compile(r"^(#{1,6}) +(.+?) *$")
_ANCHOR_LINK_RE = re.compile(r"\]\(#([^)\s]+)\)")


def _headings(lines: list[str]):
    """(line index, level, title) of every markdown heading outside fenced code."""
    fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and (m := _HEADING_RE.match(line)):
            yield i, len(m.group(1)), m.group(2)


def _slug(title: str) -> str:
    """GitHub-style heading anchor."""
    return re.sub(r"[^\w\- ]", "", title.strip().lower()).replace(" ", "-")


def _split_sections(text: str, splits: list[Split]) -> tuple[str, dict[str, str]]:
    """Apply `splits` to a SKILL.md; return the new body and {reference file: section}.

    In-document anchor links are re-pointed at whichever file now holds the heading.
    """
    refs: dict[str, str] = {}
    for sp in splits:
        lines = text.split("\n")
        heads = list(_headings(lines))
        start = next((h for h in heads if lines[h[0]] == sp.heading), None)
        if start is None:
            raise ValueError(f"heading not found: {sp.heading!r}")
        i, level, _ = start
        end = next((j for j, lv, _ in heads if j > i and lv <= level), len(lines))
        refs[sp.file] = "\n".join(lines[i:end]).rstrip("\n") + "\n"
        pointer = f"Read [references/{sp.file}](references/{sp.file}) when {sp.when}."
        text = "\n".join([*lines[:i], sp.heading, "", pointer, "", *lines[end:]])

    docs: dict[str | None, str] = {None: text, **refs}
    slugs = {k: {_slug(t) for _, _, t in _headings(v.split("\n"))} for k, v in docs.items()}

    def repoint(key: str | None, doc: str) -> str:
        def sub(m: re.Match[str]) -> str:
            anchor = m.group(1)
            if anchor in slugs[key]:
                return m.group(0)
            owner = next((k for k, s in slugs.items() if k != key and anchor in s), key)
            if owner == key:
                return m.group(0)
            if owner is None:
                path = "../SKILL.md"  # from a reference back to the skill
            elif key is None:
                path = f"references/{owner}"  # from the skill to a reference
            else:
                path = owner  # between two references in the same directory
            return f"]({path}#{anchor})"

        return _ANCHOR_LINK_RE.sub(sub, doc)

    return repoint(None, text), {k: repoint(k, v) for k, v in refs.items()}


def _rule_pack(suffix: str, upstream_dir: str, extra: tuple[str, ...]) -> Item:
    cid = f"ecc.rules.{suffix}"
    dest_dir = f"claude_code/ecc-{suffix}"
    item = Item(cid, "ecc", [], notices=[(f"{dest_dir}/LICENSE-ECC.txt", ECC_NOTICE)])
    for name in (*RULE_PACK_STANDARD_FILES, *extra):
        item.files.append((f"rules/{upstream_dir}/{name}.md", f"{dest_dir}/{name}.md"))
    item.rewrite_links = True
    return item


def _stack_skill(name: str) -> Item:
    item = _skill(f"ecc.{name}", name)
    item.rewrite_links = True
    return item


ITEMS.extend(_rule_pack(s, d, extra) for s, d, extra in ECC_RULE_PACKS)
ITEMS.extend(_stack_skill(n) for n in ECC_STACK_SKILLS)

ECC_SPLIT_FOOTER = (
    "\n\n---\n"
    "Adapted by Agent Forge from ECC skills/{name}/SKILL.md (MIT License, Copyright (c) 2026 "
    'Affaan Mustafa): the sections that say "Read references/..." were moved there verbatim, '
    "so the skill stays under Claude Code's post-compaction limit.\n"
)

# SKILL.md files at or above 20,000 bytes (ADR-0012): situational sections - topic-specific
# examples, cheat sheets, sources - move to references/; workflow, core rules and checklists
# stay. Target: under 17,500 bytes.
ECC_SPLITS: dict[str, list[Split]] = {
    "cpp-coding-standards": [
        Split("## Error Handling (E.*)", "error-handling.md",
              "the code throws, catches or defines exceptions"),
        Split("## Concurrency & Parallelism (CP.*)", "concurrency.md",
              "the code shares data between threads or uses locks, atomics or async tasks"),
        Split("## Templates & Generic Programming (T.*)", "templates.md",
              "writing templates, concepts or other generic code"),
        Split("## Performance (Per.*)", "performance.md",
              "optimising code or reviewing a performance-sensitive path"),
    ],
    "django-patterns": [
        Split("## Django REST Framework Patterns", "drf-patterns.md",
              "the project uses Django REST Framework (serializers, viewsets, custom actions)"),
    ],
    "django-tdd": [
        Split("## DRF API Testing", "drf-api-testing.md",
              "testing Django REST Framework serializers or viewsets"),
    ],
    "flutter-dart-code-review": [
        Split("## 4. State Management (Library-Agnostic)", "state-management.md",
              "reviewing state management (BLoC, Riverpod, Provider, MobX, GetX, Signals, setState)"),
        Split("## State Management Quick Reference", "state-management-quick-reference.md",
              "you need the per-library state management cheat sheet"),
        Split("## Sources", "sources.md",
              "you need the upstream documentation behind a review point"),
    ],
    "kotlin-exposed-patterns": [
        Split("## DSL Queries", "dsl-queries.md",
              "writing Exposed DSL queries (CRUD, joins, aggregates, pagination, batch operations)"),
        Split("## Repository Pattern", "repository-pattern.md",
              "implementing a repository on top of Exposed"),
    ],
    "kotlin-testing": [
        Split("### Kotest Spec Styles", "kotest-spec-styles.md",
              "choosing or writing a Kotest spec style (StringSpec, FunSpec, BehaviorSpec, DescribeSpec)"),
        Split("### Coroutine Testing", "coroutine-testing.md",
              "testing suspend functions, Flows or coroutine dispatchers"),
        Split("### Property-Based Testing", "property-based-testing.md",
              "writing property-based tests with Kotest"),
    ],
    "kubernetes-patterns": [
        Split("## RBAC — Roles and ServiceAccounts", "rbac.md",
              "setting up Roles, RoleBindings or ServiceAccounts"),
        Split("## Jobs and CronJobs", "jobs-and-cronjobs.md", "writing a Job or CronJob"),
        Split("## kubectl Debugging Cheatsheet", "kubectl-debugging.md",
              "diagnosing a failing pod or deployment (CrashLoopBackOff, ImagePullBackOff, Pending, OOMKilled)"),
    ],
    "laravel-security": [
        Split("## Authentication", "authentication.md",
              "working on login, Sanctum tokens, password handling or sessions"),
        Split("## API Security", "api-security.md",
              "building or securing an API (rate limiting, Sanctum vs Passport, CORS)"),
        Split("## CSRF Protection", "csrf.md",
              "handling CSRF for forms, excluded routes or JavaScript requests"),
        Split("## File Upload Security", "file-uploads.md", "accepting or storing uploaded files"),
        Split("## Queue Security", "queues.md", "dispatching or handling queued jobs"),
        Split("## Logging Security Events", "security-logging.md",
              "adding audit or security-event logging"),
    ],
    "tdd-workflow": [
        Split("## Testing Patterns", "testing-patterns.md",
              "writing a unit, Bun, API integration or Playwright E2E test and want the reference pattern"),
        Split("## Mocking External Services", "mocking.md",
              "mocking Supabase, Redis or OpenAI in tests"),
    ],
}  # fmt: skip

for _item in ITEMS:
    _name = _item.capability_id.removeprefix("ecc.")
    if _item.source_id == "ecc" and _name in ECC_SPLITS:
        for _up, _down in _item.files:
            if _down.endswith("/SKILL.md"):
                _item.splits[_down] = ECC_SPLITS[_name]
                _item.footers[_down] = ECC_SPLIT_FOOTER.format(name=_name)


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
        if item.frozen:
            missing = [up for up, _ in item.files if not (checkout / up).is_file()]
            if missing:
                print(f"!! {item.capability_id}: upstream file missing: {missing}", file=sys.stderr)
                return 2
            print(f"kept {item.capability_id}: hand-adapted assets, upstream files present")
            continue
        for up, down in item.files:
            src = checkout / up
            dst = assets / down
            if not src.is_file():
                print(f"!! {item.capability_id}: upstream file missing: {up}", file=sys.stderr)
                return 2
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            for old, new in item.replacements.get(down, []):
                if old not in text:
                    print(
                        f"!! {item.capability_id}: adapted passage not found in {up}: {old[:60]!r}",
                        file=sys.stderr,
                    )
                    return 2
                text = text.replace(old, new, 1)
            if item.rewrite_links and down.endswith(".md"):
                text = _rewrite_links(text)
            if down in item.splits:
                try:
                    text, refs = _split_sections(text, item.splits[down])
                except ValueError as e:
                    print(f"!! {item.capability_id}: {e} in {up}", file=sys.stderr)
                    return 2
                for ref_name, ref_text in refs.items():
                    ref = dst.parent / "references" / ref_name
                    ref.parent.mkdir(parents=True, exist_ok=True)
                    ref.write_text(ref_text, encoding="utf-8", newline="\n")
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
