"""Self-update (keep the installed engine + catalog current before `upgrade` / `forge`):
the release check is honest about why it did or did not act, and the engine never installs
over itself: it leaves the wanted tag for the launcher and exits with the update code."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_forge import selfupdate


def _version(home: Path, ref: str) -> None:
    (home / "VERSION").write_text(
        f"ref={ref}\nverified=sha256\ninstalled_at=2026-10-21T00:00:00Z\n", encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("installed", "latest", "available", "fragment"),
    [
        ("v0.4.0", "v0.4.1", True, "v0.4.1 is available"),
        ("v0.4.0", "v0.4.0", False, "is current"),
        ("v0.4.1", "v0.4.0", False, "is current"),  # never downgrade
        ("v0.4.0", "v0.10.0", True, "v0.10.0 is available"),  # numeric, not lexical
        ("v0.4.0", None, False, "could not reach"),
        ("main", "v0.4.1", False, "not a release"),
        ("source", "v0.4.1", False, "not a release"),
    ],
)
def test_check_compares_installed_release_with_the_latest(
    tmp_path: Path, monkeypatch, installed: str, latest: str | None, available: bool, fragment
) -> None:
    _version(tmp_path, installed)
    monkeypatch.setattr(selfupdate, "latest_release_tag", lambda timeout=5.0: latest)
    check = selfupdate.check_for_update(tmp_path)
    assert check.available is available and fragment in check.note, check
    assert check.installed == installed


def test_check_skips_non_installer_installs_and_opt_out(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        selfupdate, "latest_release_tag", lambda timeout=5.0: calls.append("net") or "v9.9.9"
    )
    check = selfupdate.check_for_update(tmp_path)  # no VERSION file: pipx / uvx / checkout
    assert not check.available and "no VERSION file" in check.note and calls == []
    _version(tmp_path, "v0.4.0")
    monkeypatch.setenv(selfupdate.ENV_OPT_OUT, "1")
    check = selfupdate.check_for_update(tmp_path)
    assert not check.available and selfupdate.ENV_OPT_OUT in check.note and calls == []


def test_update_request_is_a_release_tag_for_the_launcher(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(selfupdate.ENV_LAUNCHER, raising=False)
    assert not selfupdate.launcher_can_update()
    monkeypatch.setenv(selfupdate.ENV_LAUNCHER, selfupdate.LAUNCHER_PROTOCOL)
    assert selfupdate.launcher_can_update()
    path = selfupdate.request_update(tmp_path, "v0.4.1")
    assert path == tmp_path / selfupdate.UPDATE_FILE
    assert path.read_text(encoding="utf-8") == "v0.4.1"  # no newline: `set /p` reads it whole
    with pytest.raises(ValueError):
        selfupdate.request_update(tmp_path, "main; rm -rf /")
