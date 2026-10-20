"""Detect the installed coding tool's version and compare it with the adapter's verified range.

Adapters record the version range their file conventions were verified for
(`AdapterInfo.min_version` / `max_version`) and how to ask the tool (`version_command`).
`doctor` reports what it finds; planning refuses a tool outside the range with a message that
names both versions (exit 15) and only warns when the tool is absent or silent, because a
project can be prepared on a machine that does not run the tool at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from agent_forge.adapters import get_adapter
from agent_forge.errors import IncompatibleToolVersion
from agent_forge.models.capability import Platform

_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class ToolVersion:
    platform: Platform
    tool: str | None  # executable name, None when the adapter cannot detect anything
    found: bool
    version: str | None
    min_version: str | None
    max_version: str | None

    @property
    def compatible(self) -> bool | None:
        """True / False when a version was detected and a range exists; None = unknown."""
        if self.version is None or (self.min_version is None and self.max_version is None):
            return None
        v = parse_version(self.version)
        if self.min_version and v < parse_version(self.min_version):
            return False
        return not (self.max_version and v > parse_version(self.max_version))


def parse_version(text: str) -> tuple[int, int, int]:
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f"no version number in {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def detect_tool_version(platform: Platform, *, timeout: float = 5.0) -> ToolVersion:
    info = get_adapter(platform).info
    base = ToolVersion(platform, None, False, None, info.min_version, info.max_version)
    if not info.version_command:
        return base
    tool = info.version_command[0]
    exe = shutil.which(tool)
    if exe is None:
        return ToolVersion(platform, tool, False, None, info.min_version, info.max_version)
    try:
        run = subprocess.run(
            [exe, *info.version_command[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (run.stdout or "") + (run.stderr or "")
        version = _VERSION_RE.search(out)
    except (OSError, subprocess.SubprocessError):
        version = None
    return ToolVersion(
        platform,
        tool,
        True,
        version.group(0) if version else None,
        info.min_version,
        info.max_version,
    )


def check_tool_compatibility(platforms: list[Platform]) -> list[str]:
    """Warnings for undetectable tools; raises IncompatibleToolVersion for a tool outside
    its adapter's verified range."""
    notes: list[str] = []
    for platform in platforms:
        tv = detect_tool_version(platform)
        display = get_adapter(platform).info.display_name
        if tv.tool is None:
            continue
        if not tv.found:
            notes.append(
                f"{display}: `{tv.tool}` not on PATH; tool version not checked "
                f"(conventions verified for {_range(tv)})"
            )
            continue
        if tv.version is None:
            notes.append(f"{display}: `{tv.tool} --version` gave no version; not checked")
            continue
        if tv.compatible is False:
            raise IncompatibleToolVersion(
                f"{display} {tv.version} is outside the range this Agent Forge release was "
                f"verified for ({_range(tv)})",
                hint="Update the tool, or install an Agent Forge release whose adapter was "
                "verified for your version (`agent-forge doctor` shows both).",
            )
    return notes


def _range(tv: ToolVersion) -> str:
    lo = tv.min_version or "any"
    hi = tv.max_version or "any"
    return f"{lo} .. {hi}"
