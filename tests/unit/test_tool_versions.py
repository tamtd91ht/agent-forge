"""Tool version detection and the verified range (6-month plan, phase 2)."""

from __future__ import annotations

import subprocess

import pytest

from agent_forge.adapters import all_adapters
from agent_forge.adapters import tool_versions as tv
from agent_forge.errors import IncompatibleToolVersion
from agent_forge.models.capability import Platform


class _Run:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _fake(monkeypatch: pytest.MonkeyPatch, output: str | None) -> None:
    monkeypatch.setattr(tv.shutil, "which", lambda name: None if output is None else f"/bin/{name}")
    monkeypatch.setattr(tv.subprocess, "run", lambda *a, **k: _Run(output or ""))


def test_parse_version_reads_leading_numbers() -> None:
    assert tv.parse_version("2.1.304 (Claude Code)") == (2, 1, 304)
    assert tv.parse_version("codex-cli 0.163.0") == (0, 163, 0)
    assert tv.parse_version("v1.2") == (1, 2, 0)
    with pytest.raises(ValueError):
        tv.parse_version("no digits")


def test_every_adapter_range_is_well_formed() -> None:
    for a in all_adapters():
        info = a.info
        for v in (info.min_version, info.max_version):
            if v is not None:
                tv.parse_version(v)
        if info.min_version and info.max_version:
            assert tv.parse_version(info.min_version) <= tv.parse_version(info.max_version)
        if info.min_version or info.max_version:
            assert info.version_command, f"{a.platform.value}: a range needs a version_command"


def test_missing_tool_is_a_note_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, None)
    found = tv.detect_tool_version(Platform.CLAUDE_CODE)
    assert found.tool == "claude" and not found.found and found.compatible is None
    notes = tv.check_tool_compatibility([Platform.CLAUDE_CODE, Platform.CODEX])
    assert len(notes) == 2 and all("not on PATH" in n for n in notes)


def test_tool_in_range_is_silent_and_below_range_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake(monkeypatch, "2.1.304 (Claude Code)\n")
    assert tv.detect_tool_version(Platform.CLAUDE_CODE).compatible is True
    assert tv.check_tool_compatibility([Platform.CLAUDE_CODE]) == []

    _fake(monkeypatch, "1.0.99 (Claude Code)\n")
    with pytest.raises(IncompatibleToolVersion) as exc:
        tv.check_tool_compatibility([Platform.CLAUDE_CODE])
    assert exc.value.exit_code == 15
    assert "1.0.99" in exc.value.message and "2.0.0" in exc.value.message


def test_tool_without_version_output_is_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, "usage: claude [options]\n")
    notes = tv.check_tool_compatibility([Platform.CLAUDE_CODE])
    assert notes and "no version" in notes[0]


def test_subprocess_failure_is_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tv.shutil, "which", lambda name: f"/bin/{name}")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(tv.subprocess, "run", boom)
    assert tv.detect_tool_version(Platform.CLAUDE_CODE).version is None
