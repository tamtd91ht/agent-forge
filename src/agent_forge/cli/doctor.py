"""`agent-forge doctor`: environment, workspace and installed-release health."""

from __future__ import annotations

import shutil
import sys
from typing import Annotated, Any

import typer

from agent_forge import selfupdate
from agent_forge.cli._app import app
from agent_forge.cli._common import (
    JsonOpt,
    WorkspaceOpt,
    _policies,
    _registry,
    _run,
    _store,
    _ws,
    console,
    err_console,
)
from agent_forge.cli._envelope import _print_json
from agent_forge.config import WorkspaceConfig
from agent_forge.errors import AgentForgeError, SourceError

NoSelfUpdateOpt = Annotated[
    bool,
    typer.Option(
        selfupdate.NO_SELF_UPDATE_FLAG,
        help="Plan with the installed Agent Forge even when a newer release exists "
        "(the check needs api.github.com; it is skipped silently offline).",
    ),
]


def _self_update_gate(
    ws: WorkspaceConfig, *, enabled: bool, act: bool, notes: list[str]
) -> int | None:
    """Before `upgrade` / `forge` plan against the packaged catalog, make sure that catalog
    is the latest release's. Returns `EXIT_UPDATE_REQUESTED` when a newer release exists and
    the launcher will install it and re-run the command (the tag is left in UPDATE_TO);
    None to carry on with the installed version (current, offline, opted out, dry run, not
    an installer install, or started without the launcher). The reason is appended to
    `notes` either way."""
    if not enabled:
        notes.append("self-update check skipped (--no-self-update)")
        return None
    check = selfupdate.check_for_update(ws.root)
    notes.append(check.note)
    if not check.available:
        return None
    if not act:
        err_console.print(
            f"[yellow]update available:[/] {check.note}. This dry run uses the installed "
            "version; a real run (or `agent-forge self-update`) installs the new one first."
        )
        return None
    if not selfupdate.launcher_can_update():
        err_console.print(
            f"[yellow]update available:[/] {check.note}; this engine was not started by the "
            "installer's launcher, so it cannot update itself. Re-run the install command "
            "from the project root, then this command."
        )
        return None
    assert check.latest is not None
    selfupdate.request_update(ws.root, check.latest)
    err_console.print(
        f"[bold]{check.note}:[/] installing it (verified) and re-running this command."
    )
    return selfupdate.EXIT_UPDATE_REQUESTED


@app.command("self-update")
def self_update(
    workspace: WorkspaceOpt = None,
    check: Annotated[
        bool, typer.Option("--check", help="Only compare installed and latest; install nothing.")
    ] = False,
    release: Annotated[
        str | None,
        typer.Option("--release", help="Install this release tag (vX.Y.Z) instead of the latest."),
    ] = None,
    no_self_update: Annotated[
        bool, typer.Option(selfupdate.NO_SELF_UPDATE_FLAG, hidden=True)
    ] = False,
    as_json: JsonOpt = False,
) -> int:
    """Update Agent Forge itself (engine + packaged catalog) to the latest release through the
    launcher and the same verified installer that put it here. Installs nothing when current.
    Development installs (a branch or a checkout) use the installer with AGENT_FORGE_REF /
    AGENT_FORGE_SOURCE instead."""

    def body() -> int:
        ws = _ws(workspace)
        result = selfupdate.check_for_update(ws.root)
        if no_self_update:  # the launcher's re-run after installing
            after = selfupdate.installed_release(ws.root) or {}
            if as_json:
                _print_json({"installed": after.get("ref")})
            else:
                console.print(f"[green]installed {after.get('ref', '?')}[/]")
            return 0
        if check or (not result.available and not release):
            if as_json:
                _print_json(result.as_dict())
            else:
                console.print(f"[{'yellow' if result.available else 'green'}]{result.note}[/]")
                if result.available and check:
                    console.print("run `agent-forge self-update` to install it")
            return 0
        tag = release or result.latest
        assert tag is not None
        if not selfupdate.launcher_can_update():
            raise SourceError(
                "this engine was not started by the installer's launcher, so it cannot "
                "update itself",
                hint="Run the install command from the project root (it updates in place), "
                "or run `~/.agent-forge/bin/agent-forge self-update`.",
            )
        selfupdate.request_update(ws.root, tag)
        if not as_json:
            console.print(f"[bold]installing {tag}[/] (was {result.installed}; verified installer)")
        return selfupdate.EXIT_UPDATE_REQUESTED

    _run(body)
    return 0


@app.command()
def doctor(
    workspace: WorkspaceOpt = None,
    check_latest: Annotated[
        bool,
        typer.Option(
            "--check-latest",
            help="Also ask api.github.com for the latest release and compare (network).",
        ),
    ] = False,
    as_json: JsonOpt = False,
) -> int:
    """Check the local environment and workspace: tools on PATH, registry, policy, state dirs,
    orphaned locks, and which release the installer put here."""

    def body() -> int:
        import subprocess

        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str, *, level: str = "error") -> None:
            checks.append(
                {"name": name, "ok": ok, "detail": detail, "level": level if not ok else "ok"}
            )

        add("python", True, sys.version.split()[0])
        for tool, needed in (
            ("git", "required for sources/provenance"),
            ("node", "needed by node hooks / MCP servers"),
            ("npx", "needed by MCP servers"),
            ("claude", "Claude Code CLI"),
            ("codex", "Codex CLI"),
        ):
            where = shutil.which(tool)
            add(tool, where is not None, where or f"not on PATH ({needed})", level="warning")
        if shutil.which("git"):
            v = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
            add("git version", v.returncode == 0, v.stdout.strip())
        from agent_forge.adapters import all_adapters
        from agent_forge.adapters.tool_versions import detect_tool_version

        for adapter in all_adapters():
            tv = detect_tool_version(adapter.platform)
            if tv.tool is None:
                continue
            verified = f"verified {tv.min_version or 'any'} .. {tv.max_version or 'any'}"
            if not tv.found:
                detail = f"not on PATH ({verified})"
            elif tv.version is None:
                detail = f"version not reported ({verified})"
            else:
                detail = f"{tv.version} ({verified})"
            add(
                f"{adapter.platform.value} version",
                tv.compatible is not False,
                detail,
                level="warning" if tv.compatible is None else "error",
            )
        try:
            ws = _ws(workspace)
            add("workspace", True, str(ws.root))
            ws.ensure_state_dirs()
            add("state dirs", ws.state_dir.is_dir(), str(ws.state_dir))
            reg = _registry(ws)
            from agent_forge.registry.validator import validate_registry

            rr = validate_registry(reg)
            add(
                "registry",
                rr.ok,
                f"{len(reg.items)} capabilities, {len(rr.errors)} error(s), {len(rr.warnings)} warning(s)",
            )
            add("registry layers", True, ", ".join(f"{n} ({d})" for n, d in reg.layers))
            add(
                "shadowed capabilities",
                not reg.shadowed,
                "; ".join(f"{cid}: {win} overrides {lose}" for cid, win, lose in reg.shadowed)
                or "none",
                level="warning",
            )
            pinned = sum(1 for lc in reg.items.values() if lc.capability.integrity)
            add(
                "integrity pins",
                pinned == len(reg.items),
                f"{pinned}/{len(reg.items)} pinned",
                level="warning",
            )
            signed = sum(1 for lc in reg.items.values() if lc.capability.review.signed_off_by)
            add(
                "human sign-off",
                signed == len(reg.items),
                f"{signed}/{len(reg.items)} signed off",
                level="warning",
            )
            ps = _policies(ws, None)
            add("policy layers", True, ", ".join(ps.names))
            add("sources manifest", ws.sources_manifest.is_file(), str(ws.sources_manifest))
            pending = _store(ws).transactions_needing_recovery()
            add(
                "unfinished transactions",
                not pending,
                "; ".join(f"{tx}: {why} (`agent-forge rollback {tx}`)" for tx, why in pending)
                or "none",
            )
            add(
                "audit log",
                True,
                str(ws.audit_path) + (" (present)" if ws.audit_path.exists() else " (empty)"),
            )
            # Orphaned locks: a lock file whose process is gone. Reported here (doctor is
            # read-only); apply/rollback take such a lock over themselves.
            from agent_forge.storage.locks import orphaned_locks

            orphans = orphaned_locks(ws)
            add(
                "orphaned locks",
                not orphans,
                "; ".join(str(p) for p in orphans) or "none",
                level="warning",
            )
            # What the installer put here (ref, how it was verified), compared with the latest
            # release only when asked: doctor never touches the network by default.
            installed = selfupdate.installed_release(ws.root)
            if installed is None:
                add("installed release", True, "not installed by install.sh / install.ps1")
            else:
                add(
                    "installed release",
                    installed.get("verified", "none") != "none" or installed.get("ref") == "source",
                    f"{installed.get('ref', '?')} (verified: {installed.get('verified', 'none')}, "
                    f"installed {installed.get('installed_at', '?')})",
                    level="warning",
                )
            if check_latest:
                latest = selfupdate.latest_release_tag()
                if latest is None:
                    add("latest release", False, "could not reach api.github.com", level="warning")
                else:
                    current = (installed or {}).get("ref")
                    add(
                        "latest release",
                        current == latest,
                        f"{latest}"
                        + (
                            ""
                            if current == latest
                            else f" (installed: {current or 'unknown'}; "
                            "run `agent-forge self-update`)"
                        ),
                        level="warning",
                    )
        except AgentForgeError as exc:
            add("workspace", False, exc.message)
        if as_json:
            _print_json(checks)
        else:
            for c in checks:
                color = {"ok": "green", "warning": "yellow", "error": "red"}[c["level"]]
                console.print(f"[{color}]{c['level']:7}[/] {c['name']:16} {c['detail']}")
        return 0 if all(c["ok"] or c["level"] == "warning" for c in checks) else 1

    _run(body)
    return 0
