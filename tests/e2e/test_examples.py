"""Reviewed example projects (examples/*/expected.json): scanner + resolver regression gate."""

from __future__ import annotations

import importlib.util

import pytest

from tests.conftest import REPO_ROOT, unwrap

pytestmark = pytest.mark.e2e

_spec = importlib.util.spec_from_file_location(
    "matching_report", REPO_ROOT / "scripts" / "matching_report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)  # type: ignore[union-attr]

# example *projects*; examples/policy/ holds policy templates, not a project
EXAMPLES = sorted(
    p.name for p in (REPO_ROOT / "examples").iterdir() if p.is_dir() and (p / "project").is_dir()
)


def test_every_example_has_reviewed_expectations() -> None:
    assert {"java-spring", "go-gin", "nextjs-ts", "python-fastapi", "mixed-monorepo"} <= set(
        EXAMPLES
    )
    assert all((REPO_ROOT / "examples" / e / "expected.json").is_file() for e in EXAMPLES)


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_projects_match_expected(name: str) -> None:

    example = REPO_ROOT / "examples" / name
    expected = unwrap((example / "expected.json").read_text(encoding="utf-8"))
    result = report.compare(expected, report.observe(example, REPO_ROOT / "registry"))
    assert result["profile_missing"] == {}, result
    assert result["unexpected"] == [] and result["missed"] == [], result
    assert result["optional_diff"] == [], result
