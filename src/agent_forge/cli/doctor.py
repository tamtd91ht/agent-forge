"""`agent-forge doctor`: environment, workspace and installed-release health."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from agent_forge.cli._app import app
from agent_forge.cli._common import (
    INSTALLER_REPO,
    JsonOpt,
    WorkspaceOpt,
    _policies,
    _registry,
    _run,
    _store,
    _ws,
    console,
)
from agent_forge.cli._envelope import _print_json
from agent_forge.errors import AgentForgeError


def _installed_release(root: Path) -> dict[str, str] | None:
    """The `VERSION` file the installer writes next to the workspace (ref, verified, date)."""
    path = root / "VERSION"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out or None


def _latest_release_tag(timeout: float = 5.0) -> str | None:
    import urllib.error
    import urllib.request

    url = f"https://api.github.com/repos/{INSTALLER_REPO}/releases/latest"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    return tag if isinstance(tag, str) and tag else None


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
            installed = _installed_release(ws.root)
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
                latest = _latest_release_tag()
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
                            "re-run the install command to update)"
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
