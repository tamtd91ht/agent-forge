"""Rich rendering helpers shared by several commands (profiles, plan summaries, verification tables)."""

from __future__ import annotations

import re
from typing import Any

from rich.panel import Panel
from rich.table import Table

from agent_forge.cli._common import APPROVAL_FLAGS, console
from agent_forge.models.capability import CapabilityStatus


def _status_markup(status: CapabilityStatus) -> str:
    color = {
        "curated": "green",
        "under_review": "yellow",
        "discovered": "cyan",
        "deprecated": "magenta",
        "rejected": "red",
    }[status.value]
    return f"[{color}]{status.value}[/]"


def _print_profile(profile) -> None:
    console.print(
        Panel.fit(
            f"[bold]{profile.canonical_path}[/]\nfingerprint {profile.fingerprint()[:16]}",
            title="scan",
        )
    )
    g = profile.git
    console.print(
        f"git: {'repo' if g.is_repo else 'not a repo'}"
        + (
            f", {g.branch} @ {(g.head or '')[:10]}, {'dirty (' + str(g.dirty_count) + ')' if g.dirty else 'clean'}"
            if g.is_repo
            else ""
        )
    )

    def fmt(dets):
        return ", ".join(f"{d.name} ({d.confidence:.2f})" for d in dets) or "-"

    console.print(f"languages:     {fmt(profile.languages)}")
    console.print(f"frameworks:    {fmt(profile.frameworks)}")
    console.print(f"project types: {fmt(profile.project_types)}")
    if profile.traits:
        console.print(f"traits:        {fmt(profile.traits)}")
    console.print(
        "platforms:     "
        + (
            ", ".join(
                f"{p.platform.value} ({p.confidence:.2f}: {', '.join(e.path for e in p.evidence)})"
                for p in profile.platforms
            )
            or "none detected"
        )
    )
    if profile.assets:
        t = Table(title="existing agent assets")
        for col in ("platform", "kind", "name", "path", "managed by"):
            t.add_column(col, overflow="fold")
        for a in profile.assets:
            t.add_row(
                a.platform.value if a.platform else "-", a.kind, a.name, a.path, a.managed_by or "-"
            )
        console.print(t)
    if profile.managed:
        for m in profile.managed:
            drift = f" [yellow]drift: {', '.join(m.drift)}[/]" if m.drift else ""
            console.print(f"managed: {m.capability_id} v{m.version} ({len(m.files)} files){drift}")
    if profile.test_commands:
        console.print("test commands: " + "; ".join(profile.test_commands))
    if profile.sensitive_files:
        console.print(
            f"[dim]{len(profile.sensitive_files)} secret-looking file(s) skipped (never read)[/]"
        )
    s = profile.stats
    console.print(
        f"[dim]{s.files_seen} files seen, {s.files_read} read, "
        f"{len(s.excluded_dirs)} dirs excluded, {s.skipped_symlinks} symlinks skipped[/]"
    )
    for w in profile.warnings:
        console.print(f"[yellow]warning:[/] {w}")


_SCORE_PART = re.compile(r": [+-]\d+\.\d$")  # lines produced by ScoreBreakdown.explain()


def _summarize_adds(adds: list[str]) -> list[str]:
    """Collapse 'create .claude/rules/x/a.md', 'create .claude/rules/x/b.md' into one line."""
    groups: dict[tuple[str, str], list[str]] = {}
    for entry in adds:
        verb, _, path = entry.partition(" ")
        groups.setdefault((verb, path.rpartition("/")[0]), []).append(path)
    out: list[str] = []
    for (verb, folder), paths in groups.items():
        if len(paths) == 1:
            out.append(f"{verb} {paths[0]}")
        else:
            out.append(f"{verb} {folder}/ ({len(paths)} files)")
    return out


def _print_plan_summary(plan, *, hide: tuple[str, ...] = ()) -> None:
    console.print(
        Panel.fit(
            f"[bold]{plan.plan_id}[/]  kind={plan.kind}  risk={plan.risk.value}  "
            f"status={plan.status.value}\ntarget {plan.target.canonical_path}\n"
            f"registry {plan.registry_digest[:16]}  profile {plan.target.profile_fingerprint[:16]}",
            title="plan",
        )
    )
    for n in plan.notes:
        console.print(f"[dim]note:[/] {n}")
    if plan.selected:
        t = Table(title=f"selected ({len(plan.selected)})")
        for col in ("capability", "ver", "platform", "score", "risk", "ctx", "why", "adds"):
            t.add_column(col, overflow="fold")
        for s in plan.selected:
            reasons = [r for r in s.reasons if not _SCORE_PART.search(r)]  # score: --json
            why = "\n".join(reasons[:3])
            if s.existing:
                why += "\n[yellow]existing: " + "; ".join(s.existing) + "[/]"
            t.add_row(
                s.capability_id,
                s.version,
                s.platform.value,
                f"{s.score:.1f}",
                s.risk.value,
                str(s.context_chars),
                why,
                "\n".join(_summarize_adds(s.adds)),
            )
        console.print(t)
        ctx_total = sum(s.context_chars for s in plan.selected)
        console.print(
            f"always-loaded context added: {ctx_total} chars (~{ctx_total // 4} tokens) "
            "[dim](ctx: skill/agent descriptions, unscoped rules, CLAUDE.md/AGENTS.md sections)[/]"
        )
    rejected = [r for r in plan.rejected if r.category not in hide]
    if rejected:
        t = Table(title=f"not selected ({len(rejected)})")
        for col in ("capability", "category", "reason"):
            t.add_column(col, overflow="fold")
        for r in rejected:
            t.add_row(r.capability_id, r.category, "\n".join(r.reasons[:3]))
        console.print(t)
    if plan.user_decisions:
        console.print("[bold yellow]decisions needed:[/]")
        for d in plan.user_decisions:
            console.print(f"  - {d}")
    extra = plan.operations_needing_extra_approval()
    by_class: dict[str, list[str]] = {}
    for o in extra:
        by_class.setdefault(o.approval_class, []).append(o.path)
    for klass, paths in by_class.items():
        console.print(
            f"[yellow]{len(paths)} {klass} operation(s) need `approve {APPROVAL_FLAGS.get(klass, klass)}`: "
            + ", ".join(sorted(set(paths)))
            + "[/]"
        )
    console.print(f"operations: {len(plan.operations)}")


def _print_verify_report(vrep, out) -> None:
    t = Table(title=f"decision record {vrep.record.plan_id} ({vrep.record.assessed_by})")
    for col in ("capability", "verdict", "effective", "grounds", "conf", "findings"):
        t.add_column(col, overflow="fold")
    for item in vrep.items:
        d = item.decision
        color = "red" if item.downgraded else ("yellow" if not item.verified else "green")
        t.add_row(
            d.capability_id,
            d.verdict.value,
            f"[{color}]{item.effective.value}[/]",
            ", ".join(g.value for g in d.grounds) or "-",
            d.confidence.value,
            "\n".join(f"{f.level}: {f.message}" for f in item.findings) or "-",
        )
    out.print(t)
    for item in vrep.downgraded:
        out.print(
            f"[yellow]{item.decision.capability_id}[/]: the agent wanted {item.decision.verdict.value} "
            f"but could not prove it -> {item.effective.value}"
        )
    for note in vrep.notes:
        out.print(f"[dim]note:[/] {note}")


def _brief_decision(d: dict[str, Any] | None) -> str:
    if d is None:
        return "-"
    grounds = ", ".join(d["grounds"]) or "-"
    return f"{d['verdict']} [{grounds}] {d['reason']}".strip()
