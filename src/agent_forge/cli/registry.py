"""Workspace and registry commands: init, sources, catalog, validate, reindex."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from agent_forge.cli._app import app, catalog_app, sources_app
from agent_forge.cli._common import JsonOpt, WorkspaceOpt, _registry, _run, _store, _ws, console
from agent_forge.cli._envelope import _COMMAND, _print_json
from agent_forge.cli._tables import _status_markup
from agent_forge.config import (
    DEFAULT_CONFIG,
    WORKSPACE_MARKER,
    WorkspaceConfig,
    load_workspace,
)
from agent_forge.errors import ValidationFailed
from agent_forge.models.capability import CapabilityStatus, Platform
from agent_forge.util import dump_yaml, now_iso


@app.command()
def init(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", "-w", help="Directory to initialize (default: current directory)."
        ),
    ] = None,
    refresh_registry: Annotated[
        bool,
        typer.Option(
            "--refresh-registry",
            help="Re-copy the packaged registry into this workspace (after updating Agent Forge). "
            "Capabilities you added yourself are kept.",
        ),
    ] = False,
) -> None:
    """Initialize (or verify) an Agent Forge workspace. Safe to re-run; never overwrites your files."""

    def body() -> None:
        root = (workspace or Path.cwd()).expanduser().resolve()
        created: list[str] = []
        verified: list[str] = []
        refreshed: list[str] = []
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
        _seed(ws, created, verified, refreshed if refresh_registry else None)
        if refresh_registry and not refreshed:
            console.print(
                "[yellow]nothing to refresh:[/] this workspace's registry is the packaged seed itself; "
                "update it with `git pull` (or reinstall Agent Forge)"
            )
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
        for p in refreshed:
            table.add_row("[green]refreshed[/]", p)
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


def _seed(
    ws: WorkspaceConfig,
    created: list[str],
    verified: list[str],
    refreshed: list[str] | None = None,
) -> None:
    """Populate an empty workspace from the packaged seed (registry + sources.yaml).

    With `refreshed` given, an existing registry copy is updated instead of left alone: every
    seed capability replaces its workspace copy (stale files go away), schema and policies are
    re-copied, and capabilities that exist only in the workspace are kept.
    """
    seed_root: Path | None = None
    try:
        pkg_seed = resources.files("agent_forge") / "_seed"
        if (pkg_seed / "registry").is_dir():  # type: ignore[union-attr]
            seed_root = Path(str(pkg_seed))
    except (ModuleNotFoundError, TypeError, FileNotFoundError):
        seed_root = None
    if seed_root is None:
        # development checkout: <repo>/registry and <repo>/sources/sources.yaml
        repo_root = Path(__file__).resolve().parents[3]  # src/agent_forge/cli/registry.py -> repo
        if (repo_root / "registry" / "capabilities").is_dir():
            seed_root = repo_root
    if ws.sources_manifest.exists():
        verified.append(str(ws.sources_manifest))
    elif seed_root and (seed_root / "sources" / "sources.yaml").is_file():
        ws.sources_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_root / "sources" / "sources.yaml", ws.sources_manifest)
        created.append(str(ws.sources_manifest))
    populated = ws.capabilities_dir.exists() and any(ws.capabilities_dir.iterdir())
    if populated and refreshed is None:
        return
    if not seed_root or (seed_root / "registry").resolve() == ws.registry_dir.resolve():
        return
    src = seed_root / "registry"
    if populated:
        for cap_dir in (src / "capabilities").iterdir():
            stale = ws.capabilities_dir / cap_dir.name
            if cap_dir.is_dir() and stale.is_dir():
                shutil.rmtree(stale)
    # pip byte-compiles the hook scripts inside the installed seed; those caches are not assets
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for sub in ("capabilities", "schema", "policies", "bundles"):
        s = src / sub
        if s.is_dir():
            shutil.copytree(s, ws.registry_dir / sub, dirs_exist_ok=True, ignore=ignore)
    if populated:
        refreshed.append(f"{ws.registry_dir} (from {src})")  # type: ignore[union-attr]
    else:
        created.append(f"{ws.registry_dir} (seeded from {src})")


@sources_app.callback()
def _sources(ctx: typer.Context) -> None:
    """Manage approved upstream sources (clone, status, sync). Never installs."""
    if ctx.invoked_subcommand:
        _COMMAND.append(ctx.invoked_subcommand)


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
        _COMMAND.append(ctx.invoked_subcommand)
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
                    "registry": lc.registry,
                }
            )
            return
        console.print(
            Panel.fit(
                f"[bold]{c.name}[/]  [dim]{c.id} v{c.version}[/]\n{c.description}",
                title=c.kind.value,
            )
        )
        if c.review.evidence:
            ev = Table(title="evaluation evidence (baseline vs candidate)")
            for col in (
                "date",
                "fixture",
                "tool",
                "runs x tasks",
                "baseline",
                "candidate",
                "95% CI",
                "verdict",
                "report",
            ):
                ev.add_column(col, overflow="fold")
            for e in c.review.evidence:
                color = {"improved": "green", "worse": "red"}.get(e.verdict, "yellow")
                ev.add_row(
                    e.date,
                    e.fixture,
                    e.tool,
                    f"{e.runs} x {e.tasks}",
                    f"{e.baseline_pass_rate:.2f}",
                    f"{e.candidate_pass_rate:.2f}",
                    f"{e.candidate_ci95[0]:.2f}-{e.candidate_ci95[1]:.2f}",
                    f"[{color}]{e.verdict}[/]",
                    e.report,
                )
            console.print(ev)
        else:
            console.print(
                "[dim]evaluation evidence: none (value not measured; see docs/evaluation.md)[/]"
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
def reindex(workspace: WorkspaceOpt = None) -> None:
    """Rebuild the SQLite index from plan/transaction JSON documents."""

    def body() -> None:
        n_plans, n_tx = _store(_ws(workspace)).reindex()
        console.print(f"reindexed {n_plans} plan(s), {n_tx} transaction(s)")

    _run(body)
