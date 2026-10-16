"""Agent Forge command-line interface.

Lifecycle:  scan -> assign/upgrade -> diff -> approve -> apply -> validate -> (rollback)
Read-only commands never touch the target. Only `apply` and `rollback` write to it.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from agent_forge import __version__
from agent_forge.config import (
    DEFAULT_CONFIG,
    WORKSPACE_MARKER,
    WorkspaceConfig,
    load_workspace,
    require_workspace,
)
from agent_forge.errors import AgentForgeError, PlanError, UsageError, ValidationFailed
from agent_forge.models.capability import CapabilityStatus, Platform
from agent_forge.models.plan import PlanStatus
from agent_forge.util import dump_yaml, now_iso, write_json

app = typer.Typer(
    name="agent-forge",
    help="Local-first, approval-first AI-agent capability engineering. "
    "Workflow: scan -> assign -> diff -> approve -> apply -> validate.",
    no_args_is_help=True,
    invoke_without_command=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
sources_app = typer.Typer(
    help="Manage approved upstream sources (clone, status, sync). Never installs."
)
catalog_app = typer.Typer(
    help="Browse the curated capability registry.", invoke_without_command=True
)
app.add_typer(sources_app, name="sources")
app.add_typer(catalog_app, name="catalog")

console = Console()
err_console = Console(stderr=True)

WorkspaceOpt = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        "-w",
        help="Agent Forge workspace directory (default: auto-detect).",
        show_default=False,
    ),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable JSON output.")]


# ---- helpers ---------------------------------------------------------------------------


def _run(fn: Callable[[], int | None]) -> None:
    try:
        code = fn()
    except AgentForgeError as exc:
        err_console.print(f"[bold red]error:[/] {exc.message}")
        if exc.hint:
            err_console.print(f"[yellow]hint:[/] {exc.hint}")
        raise typer.Exit(exc.exit_code) from None
    except KeyboardInterrupt:
        err_console.print("[yellow]interrupted[/]")
        raise typer.Exit(130) from None
    if code:
        raise typer.Exit(code)


def _ws(workspace: Path | None) -> WorkspaceConfig:
    return require_workspace(workspace)


def _registry(ws: WorkspaceConfig):
    from agent_forge.registry.loader import load_registry

    return load_registry(ws.registry_dir)


def _store(ws: WorkspaceConfig):
    from agent_forge.storage.transactions import Store

    return Store(ws)


def _print_json(data: Any) -> None:
    # Plain stdout on purpose: Rich would wrap long lines and break machine consumers.
    sys.stdout.write(json.dumps(data, ensure_ascii=False, default=str, indent=2) + "\n")
    sys.stdout.flush()


def _platform_list(values: list[str] | None) -> tuple[Platform, ...] | None:
    if not values:
        return None
    out = []
    for v in values:
        try:
            out.append(Platform(v))
        except ValueError:
            raise UsageError(
                f"unknown platform {v!r}; choose from {', '.join(p.value for p in Platform)}"
            ) from None
    return tuple(out)


# ---- version -----------------------------------------------------------------------------


@app.callback()
def _main(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", "-V", help="Show version and exit.", is_eager=True)
    ] = False,
) -> None:
    if version:
        console.print(f"agent-forge {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


# ---- init --------------------------------------------------------------------------------


@app.command()
def init(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", "-w", help="Directory to initialize (default: current directory)."
        ),
    ] = None,
) -> None:
    """Initialize (or verify) an Agent Forge workspace. Safe to re-run; never overwrites your files."""

    def body() -> None:
        root = (workspace or Path.cwd()).expanduser().resolve()
        created: list[str] = []
        verified: list[str] = []
        root.mkdir(parents=True, exist_ok=True)
        marker = root / WORKSPACE_MARKER
        if marker.exists():
            verified.append(str(marker))
        else:
            cfg = {k: v for k, v in DEFAULT_CONFIG.items()}
            cfg["created_at"] = now_iso()
            marker.write_text(
                "# Agent Forge workspace configuration\n" + dump_yaml(cfg), encoding="utf-8"
            )
            created.append(str(marker))
        ws = load_workspace(root)
        for d in (
            ws.registry_dir,
            ws.capabilities_dir,
            ws.schema_dir,
            ws.policies_dir,
            ws.sources_dir,
            ws.checkouts_dir,
        ):
            if d.exists():
                verified.append(str(d))
            else:
                d.mkdir(parents=True)
                created.append(str(d))
        ws.ensure_state_dirs()
        verified.append(str(ws.state_dir))
        _seed(ws, created, verified)
        gi = root / ".gitignore"
        if not gi.exists():
            gi.write_text(
                "state/\nsources/checkouts/\n.venv/\n__pycache__/\n*.local.yaml\n.env\n",
                encoding="utf-8",
            )
            created.append(str(gi))
        reg = _registry(ws)
        from agent_forge.registry.validator import validate_registry

        rr = validate_registry(reg)
        _store(ws)  # creates the sqlite index
        table = Table(title=f"Workspace {root}", show_lines=False)
        table.add_column("status", style="bold")
        table.add_column("path")
        for p in created:
            table.add_row("[green]created[/]", p)
        for p in verified:
            table.add_row("[cyan]exists[/]", p)
        console.print(table)
        console.print(
            f"registry: {len(reg.items)} capabilities, {len(rr.errors)} error(s), {len(rr.warnings)} warning(s)"
        )
        for e in rr.errors:
            console.print(f"  [red]error[/] {e}")
        console.print(
            "[green]workspace ready[/]. Next: `agent-forge sources list`, `agent-forge catalog`, `agent-forge scan PATH`."
        )

    _run(body)


def _seed(ws: WorkspaceConfig, created: list[str], verified: list[str]) -> None:
    """Populate an empty workspace from the packaged seed (registry + sources.yaml)."""
    seed_root: Path | None = None
    try:
        pkg_seed = resources.files("agent_forge") / "_seed"
        if (pkg_seed / "registry").is_dir():  # type: ignore[union-attr]
            seed_root = Path(str(pkg_seed))
    except (ModuleNotFoundError, TypeError, FileNotFoundError):
        seed_root = None
    if seed_root is None:
        # development checkout: <repo>/registry and <repo>/sources/sources.yaml
        repo_root = Path(__file__).resolve().parents[2]
        if (repo_root / "registry" / "capabilities").is_dir():
            seed_root = repo_root
    if ws.sources_manifest.exists():
        verified.append(str(ws.sources_manifest))
    elif seed_root and (seed_root / "sources" / "sources.yaml").is_file():
        ws.sources_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_root / "sources" / "sources.yaml", ws.sources_manifest)
        created.append(str(ws.sources_manifest))
    if any(ws.capabilities_dir.iterdir()) if ws.capabilities_dir.exists() else False:
        return
    if seed_root and (seed_root / "registry").resolve() != ws.registry_dir.resolve():
        src = seed_root / "registry"
        for sub in ("capabilities", "schema", "policies", "bundles"):
            s = src / sub
            if s.is_dir():
                shutil.copytree(s, ws.registry_dir / sub, dirs_exist_ok=True)
        created.append(f"{ws.registry_dir} (seeded from {src})")


# ---- sources -----------------------------------------------------------------------------


@sources_app.command("list")
def sources_list(
    workspace: WorkspaceOpt = None,
    fetch: Annotated[
        bool, typer.Option("--fetch", help="git fetch to compare with upstream (network).")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """List registered sources, checkout revisions and sync state."""

    def body() -> None:
        from agent_forge.sources.manager import SourceManager

        mgr = SourceManager(_ws(workspace))
        rows = mgr.list_status(fetch=fetch)
        if as_json:
            _print_json([r.to_dict() for r in rows])
            return
        t = Table(title="Sources")
        for col in ("id", "license", "checkout", "head", "recorded", "upstream", "state"):
            t.add_column(col)
        for r in rows:
            state = "missing" if not r.present else ("dirty" if r.dirty else "clean")
            if r.behind:
                state += f", {r.behind} behind"
            if r.problems:
                state += " [red]! " + "; ".join(r.problems) + "[/]"
            t.add_row(
                r.spec.id,
                r.spec.license,
                str(r.checkout),
                (r.head or "-")[:12],
                (r.recorded_revision or "-")[:12],
                (r.upstream_head or "-")[:12],
                state,
            )
        console.print(t)
        console.print(
            "[dim]Cloning is not installing. Checkout content is untrusted until curated into the registry.[/]"
        )

    _run(body)


@sources_app.command("clone")
def sources_clone(
    source_id: Annotated[str | None, typer.Argument(help="Source id (default: all).")] = None,
    workspace: WorkspaceOpt = None,
) -> None:
    """Clone approved sources into the workspace checkouts directory (network). No scripts are executed."""

    def body() -> None:
        from agent_forge.sources.manager import SourceManager

        mgr = SourceManager(_ws(workspace))
        specs = [mgr.get(source_id)] if source_id else mgr.manifest.sources
        for spec in specs:
            st = mgr.clone(spec)
            console.print(f"[green]{spec.id}[/] -> {st.checkout} @ {(st.head or '-')[:12]}")

    _run(body)


@sources_app.command("sync")
def sources_sync(
    source_id: Annotated[str | None, typer.Argument(help="Source id (default: all).")] = None,
    update: Annotated[
        bool,
        typer.Option(
            "--update",
            help="Move the checkout to upstream HEAD (never touches registry or targets).",
        ),
    ] = False,
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Fetch upstream and report changed files. Only --update moves the checkout."""

    def body() -> None:
        from agent_forge.sources.manager import SourceManager

        mgr = SourceManager(_ws(workspace))
        specs = [mgr.get(source_id)] if source_id else mgr.manifest.sources
        out = []
        for spec in specs:
            st = mgr.sync(spec, update=update)
            out.append(st.to_dict())
            if as_json:
                continue
            console.print(
                Panel.fit(
                    f"[bold]{spec.id}[/]  head {(st.head or '-')[:12]}  "
                    f"upstream {(st.upstream_head or '-')[:12]}  "
                    f"behind {st.behind if st.behind is not None else '-'}",
                    title="sync",
                )
            )
            if st.changed_files:
                console.print(f"  {len(st.changed_files)} changed file(s) upstream; first 30:")
                for f in st.changed_files[:30]:
                    console.print(f"    {f}")
                console.print(
                    "  [yellow]Review before curating. Upstream changes never rewrite the registry automatically.[/]"
                )
        if as_json:
            _print_json(out)

    _run(body)


# ---- catalog -----------------------------------------------------------------------------


@catalog_app.callback()
def catalog(
    ctx: typer.Context,
    workspace: WorkspaceOpt = None,
    category: Annotated[str | None, typer.Option(help="Filter by category.")] = None,
    platform: Annotated[str | None, typer.Option(help="claude_code | codex")] = None,
    project_type: Annotated[
        str | None, typer.Option(help="e.g. frontend, backend, cli, library")
    ] = None,
    status: Annotated[
        str | None, typer.Option(help="discovered | under_review | curated | deprecated | rejected")
    ] = None,
    source: Annotated[str | None, typer.Option(help="Source id, e.g. ecc")] = None,
    kind: Annotated[
        str | None, typer.Option(help="skill | rule | agent | instruction | reference")
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """List curated capabilities (filters optional)."""
    if ctx.invoked_subcommand is not None:
        return

    def body() -> None:
        from agent_forge.registry.catalog import CatalogFilter, query

        reg = _registry(_ws(workspace))
        flt = CatalogFilter(
            category=category,
            platform=Platform(platform) if platform else None,
            project_type=project_type,
            status=CapabilityStatus(status) if status else None,
            source=source,
            kind=kind,
        )
        caps = query(reg, flt)
        if as_json:
            _print_json([c.model_dump(mode="json") for c in caps])
            return
        t = Table(title=f"Catalog ({len(caps)} of {len(reg.items)})")
        for col in ("id", "ver", "kind", "status", "platforms", "source", "risk", "description"):
            t.add_column(col, overflow="fold")
        for c in caps:
            t.add_row(
                c.id,
                c.version,
                c.kind.value,
                _status_markup(c.status),
                ",".join(p.value for p in c.platforms),
                c.source.source_id,
                c.risk.value,
                c.description,
            )
        console.print(t)

    _run(body)


def _status_markup(status: CapabilityStatus) -> str:
    color = {
        "curated": "green",
        "under_review": "yellow",
        "discovered": "cyan",
        "deprecated": "magenta",
        "rejected": "red",
    }[status.value]
    return f"[{color}]{status.value}[/]"


@catalog_app.command("show")
def catalog_show(
    capability_id: str, workspace: WorkspaceOpt = None, as_json: JsonOpt = False
) -> None:
    """Show one capability's metadata, provenance, dependencies, conflicts and compatibility."""

    def body() -> None:
        reg = _registry(_ws(workspace))
        lc = reg.get(capability_id)
        c = lc.capability
        if as_json:
            _print_json(
                {
                    **c.model_dump(mode="json"),
                    "directory": str(lc.directory),
                    "content_digest": lc.content_digest,
                }
            )
            return
        console.print(
            Panel.fit(
                f"[bold]{c.name}[/]  [dim]{c.id} v{c.version}[/]\n{c.description}",
                title=c.kind.value,
            )
        )
        rows = [
            ("status", _status_markup(c.status)),
            ("provenance", c.provenance.value),
            ("category", c.category),
            ("purpose", c.purpose),
            (
                "source",
                f"{c.source.source_id} {c.source.repository or ''} @ {(c.source.revision or '-')[:12]}",
            ),
            ("upstream paths", "\n".join(c.source.paths) or "-"),
            ("license", f"{c.license.spdx} — {c.license.attribution}"),
            ("platforms", ", ".join(p.value for p in c.platforms)),
            ("install", c.install_strategy.value),
            (
                "destinations",
                "\n".join(
                    f"{d.platform.value}: assets/{d.source} -> {d.dest} [{d.merge.value}]"
                    for d in c.destinations
                )
                or "-",
            ),
            (
                "applicability",
                dump_yaml(c.applicability.model_dump(mode="json", exclude_defaults=True)).strip()
                or "-",
            ),
            ("dependencies", ", ".join(c.dependencies) or "-"),
            ("conflicts", ", ".join(c.conflicts) or "-"),
            (
                "equivalents",
                "\n".join(f"{e.kind.value}: {e.description}" for e in c.equivalents) or "-",
            ),
            ("permissions", ", ".join(c.permissions) or "-"),
            ("network", c.network.value),
            ("risk", c.risk.value),
            (
                "runtime",
                "\n".join(f"{r.name}: {r.description}" for r in c.runtime_requirements) or "-",
            ),
            ("review", f"{c.review.reviewed_at} by {c.review.reviewer}\n{c.review.rationale}"),
            ("content digest", lc.content_digest[:16]),
        ]
        t = Table(show_header=False, box=None)
        t.add_column("k", style="bold cyan")
        t.add_column("v", overflow="fold")
        for k, v in rows:
            t.add_row(k, v)
        console.print(t)

    _run(body)


# ---- scan --------------------------------------------------------------------------------


@app.command()
def scan(
    path: Annotated[Path, typer.Argument(help="Target project directory (read-only).")],
    workspace: WorkspaceOpt = None,
    report: Annotated[
        Path | None,
        typer.Option(
            "--report", help="Write the JSON profile here (outside the target by default)."
        ),
    ] = None,
    as_json: JsonOpt = False,
) -> None:
    """Scan a project read-only: languages, frameworks, agent platforms, existing assets, managed state."""

    def body() -> None:
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        profile = scan_project(path, limits=ws.scan_limits)
        data = profile.model_dump(mode="json")
        dest = report
        if dest is None:
            safe = (
                profile.canonical_path.replace(":", "")
                .replace("\\", "_")
                .replace("/", "_")
                .strip("_")
            )
            dest = ws.reports_dir / f"scan-{safe[-80:]}.json"
        if Path(profile.canonical_path) in dest.resolve().parents:
            raise UsageError(
                "refusing to write the report inside the target project; choose --report outside it"
            )
        write_json(dest, data)
        if as_json:
            _print_json(data)
            return
        _print_profile(profile)
        console.print(f"[dim]report written to {dest}[/]")

    _run(body)


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


# ---- assign / upgrade --------------------------------------------------------------------


def _ctx(platforms, want, request, exclude, include_optional):
    from agent_forge.matching.rules import MatchContext

    return MatchContext(
        platforms=platforms,
        wanted_tags=frozenset(want or []),
        requested_ids=frozenset(request or []),
        excluded_ids=frozenset(exclude or []),
        include_optional=include_optional,
    )


@app.command()
def assign(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    platform: Annotated[
        list[str] | None,
        typer.Option(
            "--platform", "-p", help="Target platform(s): claude_code, codex. Default: detected."
        ),
    ] = None,
    want: Annotated[
        list[str] | None,
        typer.Option("--want", help="Request capabilities carrying this tag (e.g. ui, security)."),
    ] = None,
    request: Annotated[
        list[str] | None, typer.Option("--request", help="Force-consider a capability id.")
    ] = None,
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="Never select this capability id.")
    ] = None,
    include_optional: Annotated[
        bool, typer.Option("--include-optional", help="Promote optional candidates into the plan.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Recommend capabilities for a project and write a reviewable plan. Never modifies the target."""

    def body() -> None:
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.planner import build_assign_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        ctx = _ctx(tuple(platforms), want, request, exclude, include_optional)
        plan, _match = build_assign_plan(reg, profile, ctx)
        plan.notes = [*notes, *plan.notes]
        store = _store(ws)
        p = store.save_plan(plan)
        if as_json:
            _print_json(plan.model_dump(mode="json"))
            return
        _print_plan_summary(plan)
        console.print(f"[dim]plan saved: {p}[/]")
        console.print(
            f"next: [bold]agent-forge diff {plan.plan_id}[/]  then  [bold]agent-forge approve {plan.plan_id}[/]"
        )

    _run(body)


@app.command()
def upgrade(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    platform: Annotated[list[str] | None, typer.Option("--platform", "-p")] = None,
    as_json: JsonOpt = False,
) -> None:
    """Compare managed capabilities with the registry and write an upgrade plan. Never modifies the target."""

    def body() -> None:
        from agent_forge.matching.rules import choose_platforms
        from agent_forge.planner import build_upgrade_plan
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        platforms, notes = choose_platforms(profile, _platform_list(platform))
        plan = build_upgrade_plan(reg, profile, _ctx(tuple(platforms), None, None, None, False))
        plan.notes = [*notes, *plan.notes]
        store = _store(ws)
        p = store.save_plan(plan)
        if as_json:
            _print_json(plan.model_dump(mode="json"))
            return
        _print_plan_summary(plan)
        if not plan.operations:
            console.print("[green]nothing to upgrade[/]")
        console.print(f"[dim]plan saved: {p}[/]")

    _run(body)


def _print_plan_summary(plan) -> None:
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
        for col in ("capability", "ver", "platform", "score", "risk", "why", "adds"):
            t.add_column(col, overflow="fold")
        for s in plan.selected:
            why = "\n".join(s.reasons[:4])
            if s.existing:
                why += "\n[yellow]existing: " + "; ".join(s.existing) + "[/]"
            t.add_row(
                s.capability_id,
                s.version,
                s.platform.value,
                f"{s.score:.1f}",
                s.risk.value,
                why,
                "\n".join(s.adds),
            )
        console.print(t)
    if plan.rejected:
        t = Table(title=f"not selected ({len(plan.rejected)})")
        for col in ("capability", "category", "reason"):
            t.add_column(col, overflow="fold")
        for r in plan.rejected:
            t.add_row(r.capability_id, r.category, "\n".join(r.reasons[:3]))
        console.print(t)
    if plan.user_decisions:
        console.print("[bold yellow]decisions needed:[/]")
        for d in plan.user_decisions:
            console.print(f"  - {d}")
    extra = plan.operations_needing_extra_approval()
    if extra:
        console.print(
            f"[yellow]{len(extra)} shared-file operation(s) need `approve --shared-files`: "
            + ", ".join(o.path for o in extra)
            + "[/]"
        )
    console.print(f"operations: {len(plan.operations)}")


# ---- plans / diff / approve / apply ------------------------------------------------------


@app.command()
def plans(
    workspace: WorkspaceOpt = None,
    target: Annotated[Path | None, typer.Option(help="Only plans for this target.")] = None,
    as_json: JsonOpt = False,
) -> None:
    """List saved plans."""

    def body() -> None:
        store = _store(_ws(workspace))
        rows = store.list_plans(str(target.resolve()) if target else None)
        if as_json:
            _print_json(rows)
            return
        t = Table(title="plans")
        for col in ("plan", "kind", "status", "created", "target"):
            t.add_column(col, overflow="fold")
        for r in rows:
            t.add_row(r["plan_id"], r["kind"], r["status"], r["created_at"], r["target"])
        console.print(t)

    _run(body)


@app.command()
def diff(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    full: Annotated[
        bool, typer.Option("--full", help="Show complete diffs for new files too.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Show exact proposed additions, modifications and removals for a plan."""

    def body() -> None:
        from agent_forge.planner import render_plan_diff

        ws = _ws(workspace)
        store = _store(ws)
        plan = store.load_plan(plan_id)
        diffs = render_plan_diff(plan, Path(plan.target.canonical_path))
        if as_json:
            _print_json(
                [
                    {
                        "op_id": d.op.op_id,
                        "kind": d.op.kind.value,
                        "path": d.op.path,
                        "stale": d.stale,
                        "extra_approval": d.op.requires_extra_approval,
                        "summary": d.summary,
                        "diff": d.unified,
                        "warnings": d.warnings,
                    }
                    for d in diffs
                ]
            )
            return
        _print_plan_summary(plan)
        for d in diffs:
            flag = " [red]STALE[/]" if d.stale else ""
            extra = (
                " [yellow](shared file: extra approval)[/]" if d.op.requires_extra_approval else ""
            )
            console.rule(f"{d.op.op_id} {d.summary}{flag}{extra}")
            for w in d.warnings:
                console.print(f"[yellow]warning:[/] {w}")
            text = d.unified
            if not full and d.op.before_sha256 is None and text.count("\n") > 60:
                lines = text.splitlines()
                text = "\n".join(lines[:60]) + f"\n... ({len(lines) - 60} more lines; use --full)"
            console.print(
                Syntax(text or "(no textual change)", "diff", theme="ansi_dark", word_wrap=True)
            )
        if any(d.stale for d in diffs):
            console.print("[red]plan is stale for at least one file; re-run assign/upgrade[/]")

    _run(body)


@app.command()
def approve(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    shared_files: Annotated[
        bool,
        typer.Option(
            "--shared-files",
            help="Also approve operations that modify shared files (CLAUDE.md, AGENTS.md, settings).",
        ),
    ] = False,
    by: Annotated[
        str | None, typer.Option("--by", help="Approver name recorded in the plan.")
    ] = None,
    revoke: Annotated[bool, typer.Option("--revoke", help="Revoke a previous approval.")] = False,
) -> None:
    """Approve a plan. The approval is bound to the plan's content digest; any change invalidates it."""

    def body() -> None:
        from agent_forge.planner import render_plan_diff

        ws = _ws(workspace)
        store = _store(ws)
        plan = store.load_plan(plan_id)
        if revoke:
            plan.approval.status = "revoked"
            plan.approval.plan_digest = None
            plan.approval.extra_approvals = []
            plan.status = PlanStatus.REVOKED
            store.save_plan(plan)
            console.print(f"[yellow]approval revoked for {plan_id}[/]")
            return
        if plan.status not in (PlanStatus.DRAFT, PlanStatus.APPROVED, PlanStatus.REVOKED):
            raise PlanError(f"plan is {plan.status.value}; create a new plan")
        if not plan.operations:
            raise PlanError("plan has no operations; nothing to approve")
        diffs = render_plan_diff(plan, Path(plan.target.canonical_path))
        stale = [d.op.path for d in diffs if d.stale]
        if stale:
            from agent_forge.errors import StalePlanError

            plan.status = PlanStatus.STALE
            store.save_plan(plan)
            raise StalePlanError(
                "plan is stale; target files changed since planning: " + ", ".join(stale),
                hint="Re-run `assign`/`upgrade`.",
            )
        reg = _registry(ws)
        if reg.digest != plan.registry_digest:
            from agent_forge.errors import StalePlanError

            plan.status = PlanStatus.STALE
            store.save_plan(plan)
            raise StalePlanError(
                "registry changed since planning", hint="Re-run `assign`/`upgrade`."
            )
        extra = plan.operations_needing_extra_approval()
        if extra and not shared_files:
            raise PlanError(
                "plan modifies shared files: " + ", ".join(o.path for o in extra),
                hint="Review `diff`, then re-run with --shared-files to approve those operations explicitly.",
            )
        plan.approval.status = "approved"
        plan.approval.approved_at = now_iso()
        plan.approval.approved_by = by
        plan.approval.plan_digest = plan.content_digest()
        plan.approval.extra_approvals = [o.op_id for o in extra] if shared_files else []
        plan.status = PlanStatus.APPROVED
        store.save_plan(plan)
        console.print(
            f"[green]approved[/] {plan_id} (digest {plan.approval.plan_digest[:16]}, {len(plan.operations)} operations"
            + (f", {len(extra)} shared-file" if extra else "")
            + ")"
        )
        console.print(f"next: [bold]agent-forge apply {plan_id}[/]")

    _run(body)


@app.command()
def apply(
    plan_id: str,
    workspace: WorkspaceOpt = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Skip the interactive confirmation (approval, hashes and scope are still enforced).",
        ),
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Apply an approved, non-stale plan inside a recoverable transaction."""

    def body() -> None:
        from agent_forge.apply.engine import apply_plan

        ws = _ws(workspace)
        store = _store(ws)
        reg = _registry(ws)
        plan = store.load_plan(plan_id)

        def confirm(rep) -> bool:
            out = err_console if as_json else console
            out.print(
                Panel.fit(
                    "\n".join(rep.summary), title=f"apply {plan_id} -> {plan.target.canonical_path}"
                )
            )
            for w in rep.warnings:
                out.print(f"[yellow]warning:[/] {w}")
            if yes:
                return True
            if not sys.stdin.isatty():
                raise PlanError(
                    "interactive confirmation required (no TTY)",
                    hint="Re-run with --yes after reviewing `diff`.",
                )
            return typer.confirm("Write these changes to the target?", default=False)

        tx = apply_plan(ws, store, reg, plan, confirm=confirm)
        if as_json:
            _print_json(tx.model_dump(mode="json"))
            return
        console.print(
            f"[green]applied[/] {len([o for o in tx.operations if o.applied])} operation(s); transaction {tx.transaction_id}"
        )
        console.print(
            f"next: [bold]agent-forge validate {plan.target.canonical_path}[/]   "
            f"rollback: [bold]agent-forge rollback {tx.transaction_id}[/]"
        )

    _run(body)


# ---- validate / status / rollback --------------------------------------------------------


@app.command()
def validate(
    path: Annotated[
        Path | None,
        typer.Argument(help="Target project to validate (omit for registry/workspace only)."),
    ] = None,
    workspace: WorkspaceOpt = None,
    no_provenance: Annotated[
        bool, typer.Option("--no-provenance", help="Skip git-based provenance checks.")
    ] = False,
    as_json: JsonOpt = False,
) -> int:
    """Validate registry integrity, provenance, managed installs, config syntax and transaction records."""

    def body() -> int:
        from agent_forge.validation.engine import validate_target, validate_workspace

        ws = _ws(workspace)
        reg = _registry(ws)
        rep = validate_workspace(ws, reg, provenance=not no_provenance)
        if path is not None:
            from agent_forge.scanner.project_profile import scan_project

            profile = scan_project(path, limits=ws.scan_limits)
            trep = validate_target(ws, reg, _store(ws), profile)
            rep.findings.extend(trep.findings)
            rep.checks_run += trep.checks_run
        if as_json:
            _print_json(
                {
                    "ok": rep.ok,
                    "checks_run": rep.checks_run,
                    "findings": [f.__dict__ for f in rep.findings],
                }
            )
        else:
            for f in rep.findings:
                color = {"error": "red", "warning": "yellow", "info": "dim"}[f.level]
                console.print(f"[{color}]{f.level:7}[/] [{f.scope}] {f.message}")
            console.print(
                f"{rep.checks_run} checks, {len(rep.errors)} error(s), {len(rep.warnings)} warning(s): "
                + ("[green]OK[/]" if rep.ok else "[red]FAILED[/]")
            )
        return 0 if rep.ok else ValidationFailed.exit_code

    _run(body)
    return 0


@app.command()
def status(
    path: Annotated[Path, typer.Argument(help="Target project directory.")],
    workspace: WorkspaceOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Report managed capabilities, drift, outdated versions, conflicts and recent transactions."""

    def body() -> None:
        from agent_forge.scanner.project_profile import scan_project

        ws = _ws(workspace)
        reg = _registry(ws)
        store = _store(ws)
        profile = scan_project(path, limits=ws.scan_limits)
        installed = {m.capability_id for m in profile.managed}
        rows = []
        for m in profile.managed:
            cap = reg.items.get(m.capability_id)
            reg_ver = cap.capability.version if cap else None
            conflicts = sorted(set(cap.capability.conflicts) & installed) if cap else []
            rows.append(
                {
                    "capability": m.capability_id,
                    "installed": m.version,
                    "registry": reg_ver,
                    "status": cap.capability.status.value if cap else "missing",
                    "drift": m.drift,
                    "conflicts": conflicts,
                    "files": len(m.files),
                    "transaction": m.transaction_id,
                    "installed_at": m.installed_at,
                }
            )
        txs = store.list_transactions(profile.canonical_path, limit=10)
        plans_ = [p for p in store.list_plans(profile.canonical_path)][:10]
        if as_json:
            _print_json(
                {
                    "target": profile.canonical_path,
                    "managed_manifest_valid": profile.managed_manifest_valid,
                    "capabilities": rows,
                    "transactions": txs,
                    "plans": plans_,
                    "platforms": [p.platform.value for p in profile.platforms],
                }
            )
            return
        console.print(
            Panel.fit(
                f"[bold]{profile.canonical_path}[/]\nplatforms: "
                f"{', '.join(p.platform.value for p in profile.platforms) or 'none'}  "
                f"managed manifest: {profile.managed_manifest_valid}",
                title="status",
            )
        )
        if rows:
            t = Table(title="managed capabilities")
            for col in (
                "capability",
                "installed",
                "registry",
                "status",
                "drift",
                "conflicts",
                "files",
                "transaction",
            ):
                t.add_column(col, overflow="fold")
            for r in rows:
                outdated = r["registry"] and r["registry"] != r["installed"]
                t.add_row(
                    r["capability"],
                    r["installed"],
                    ("[yellow]" + str(r["registry"]) + " (outdated)[/]")
                    if outdated
                    else str(r["registry"]),
                    r["status"],
                    "[yellow]" + ", ".join(r["drift"]) + "[/]" if r["drift"] else "-",
                    "[red]" + ", ".join(r["conflicts"]) + "[/]" if r["conflicts"] else "-",
                    str(r["files"]),
                    r["transaction"],
                )
            console.print(t)
        else:
            console.print("no managed capabilities")
        if txs:
            t = Table(title="recent transactions")
            for col in ("transaction", "plan", "status", "started", "finished"):
                t.add_column(col, overflow="fold")
            for x in txs:
                t.add_row(
                    x["transaction_id"],
                    x["plan_id"],
                    x["status"],
                    x["started_at"],
                    x["finished_at"] or "-",
                )
            console.print(t)
        if plans_:
            console.print("plans: " + ", ".join(f"{p['plan_id']} ({p['status']})" for p in plans_))

    _run(body)


@app.command()
def rollback(
    transaction_id: str,
    workspace: WorkspaceOpt = None,
    partial: Annotated[
        bool,
        typer.Option(
            "--partial", help="Roll back untouched files even if others were modified after apply."
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the interactive confirmation.")
    ] = False,
    as_json: JsonOpt = False,
) -> None:
    """Reverse a transaction. Files modified after apply are never overwritten."""

    def body() -> None:
        from agent_forge.rollback.engine import execute_rollback, plan_rollback

        ws = _ws(workspace)
        store = _store(ws)
        tx = store.load_transaction(transaction_id)
        rp = plan_rollback(store, tx)
        if not as_json:
            t = Table(title=f"rollback {transaction_id}")
            for col in ("action", "path", "detail"):
                t.add_column(col, overflow="fold")
            for c in rp.checks:
                color = {
                    "restore": "green",
                    "delete": "green",
                    "remove_section": "green",
                    "skip": "dim",
                    "conflict": "red",
                }[c.action]
                t.add_row(f"[{color}]{c.action}[/]", c.op.path, c.detail)
            console.print(t)
        if rp.conflicts and not partial:
            from agent_forge.errors import RollbackConflict

            raise RollbackConflict(
                "files changed independently after apply: "
                + ", ".join(c.op.path for c in rp.conflicts),
                hint="Inspect them, then re-run with --partial to roll back only the untouched files.",
            )
        if not rp.actionable:
            console.print("nothing to roll back")
            return
        if not yes and not as_json:
            if not sys.stdin.isatty():
                raise PlanError(
                    "interactive confirmation required (no TTY)", hint="Re-run with --yes."
                )
            if not typer.confirm(f"Roll back {len(rp.actionable)} file(s)?", default=False):
                raise PlanError("rollback cancelled by user")
        rb = execute_rollback(store, rp, partial=partial)
        if as_json:
            _print_json(rb.model_dump(mode="json"))
            return
        console.print(
            f"[green]rolled back[/] {len([o for o in rb.operations if o.applied])} file(s); record {rb.transaction_id}"
        )
        for n in rb.notes:
            console.print(f"[yellow]{n}[/]")

    _run(body)


@app.command()
def reindex(workspace: WorkspaceOpt = None) -> None:
    """Rebuild the SQLite index from plan/transaction JSON documents."""

    def body() -> None:
        n_plans, n_tx = _store(_ws(workspace)).reindex()
        console.print(f"reindexed {n_plans} plan(s), {n_tx} transaction(s)")

    _run(body)


def main() -> None:
    # Windows consoles default to a legacy code page; plans and skills contain Unicode.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # closed or exotic streams
                reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
