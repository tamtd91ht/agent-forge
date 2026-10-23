"""Keep the installed Agent Forge (engine + packaged catalog) current before an upgrade.

An install made by `install.sh` / `install.ps1` carries the catalog of the release it
installed; running `upgrade` or `forge` again in a project compares that project with
*that* catalog, never with a newer one. So before planning, `upgrade` and `forge` ask
api.github.com for the latest release and compare it with the `VERSION` file the installer
wrote. When a newer release exists they do not install it themselves: on Windows the running
engine's own files are locked, and a `pip install` over them breaks the venv. Instead the
engine writes the wanted tag to `UPDATE_TO` next to the workspace and exits with
`EXIT_UPDATE_REQUESTED`; the launcher the installer generated (`bin/agent-forge[.cmd]`, a
shell script that locks nothing) runs the verified installer for that tag and re-runs the
command once with `--no-self-update`. The launcher announces this protocol with
`AGENT_FORGE_LAUNCHER=2`; without it the engine only reports the update.

Nothing is requested when the versions match, when the check cannot reach the network (a
note says so), when the install is not an installer install (pipx / uvx / a development
checkout: no `VERSION` file) or when the caller opts out (`--no-self-update`,
`AGENT_FORGE_NO_SELF_UPDATE=1`). The network is used for the release lookup only; nothing
about the project is sent.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

INSTALLER_REPO = "tamtd91ht/agent-forge"
RELEASES_API = f"https://api.github.com/repos/{INSTALLER_REPO}/releases/latest"
ENV_OPT_OUT = "AGENT_FORGE_NO_SELF_UPDATE"
ENV_LAUNCHER = "AGENT_FORGE_LAUNCHER"
LAUNCHER_PROTOCOL = "2"
NO_SELF_UPDATE_FLAG = "--no-self-update"
UPDATE_FILE = "UPDATE_TO"
EXIT_UPDATE_REQUESTED = 16
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def installed_release(home: Path) -> dict[str, str] | None:
    """The `VERSION` file the installer writes next to the workspace (ref, verified, date)."""
    try:
        text = (home / "VERSION").read_text(encoding="utf-8")
    except OSError:
        return None
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out or None


def latest_release_tag(timeout: float = 5.0) -> str | None:
    """Tag of the latest GitHub Release, or None when the API is unreachable."""
    try:
        with urllib.request.urlopen(RELEASES_API, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    return tag if isinstance(tag, str) and tag else None


def _version_key(tag: str) -> tuple[int, int, int] | None:
    m = _TAG.match(tag.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


@dataclass
class UpdateCheck:
    installed: str | None = None
    latest: str | None = None
    available: bool = False
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "installed": self.installed,
            "latest": self.latest,
            "available": self.available,
            "note": self.note,
        }


def check_for_update(home: Path, *, timeout: float = 5.0) -> UpdateCheck:
    """Compare the installed release with the latest one. Never raises; `note` explains."""
    if os.environ.get(ENV_OPT_OUT):
        return UpdateCheck(note=f"self-update check skipped ({ENV_OPT_OUT} is set)")
    rec = installed_release(home)
    if rec is None:
        return UpdateCheck(
            note="self-update check skipped: not an installer install (no VERSION file); "
            "update with pipx / uvx or `git pull` in the checkout"
        )
    installed = rec.get("ref") or ""
    current = _version_key(installed)
    if current is None:
        return UpdateCheck(
            installed=installed or None,
            note=f"self-update check skipped: installed from {installed or 'an unknown ref'}, "
            "not a release; re-run the installer to switch to a release",
        )
    latest = latest_release_tag(timeout=timeout)
    if latest is None:
        return UpdateCheck(
            installed=installed,
            note="self-update check skipped: could not reach api.github.com (offline?)",
        )
    newest = _version_key(latest)
    if newest is None or newest <= current:
        return UpdateCheck(installed=installed, latest=latest, note="Agent Forge is current")
    return UpdateCheck(
        installed=installed,
        latest=latest,
        available=True,
        note=f"Agent Forge {latest} is available (installed: {installed})",
    )


def launcher_can_update() -> bool:
    """True when this process was started by a launcher that installs on exit code 16."""
    return os.environ.get(ENV_LAUNCHER) == LAUNCHER_PROTOCOL


def request_update(home: Path, tag: str) -> Path:
    """Leave the wanted release tag for the launcher and return the file written."""
    if _version_key(tag) is None:
        raise ValueError(f"not a release tag: {tag!r}")
    path = home / UPDATE_FILE
    path.write_text(tag, encoding="utf-8")
    return path
