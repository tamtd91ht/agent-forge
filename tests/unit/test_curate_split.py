from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def curate():
    spec = importlib.util.spec_from_file_location("curate", ROOT / "scripts" / "curate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["curate"] = mod
    spec.loader.exec_module(mod)
    return mod


DOC = """# Skill

See [Deep part](#deep-part) and [Intro](#intro).

## Intro

Core text.

## Patterns — Big

Lead.

### Deep part

```python
## not a heading
x = 1
```

Back to [Intro](#intro).

## Checklist

- keep
"""


def test_split_moves_section_verbatim_and_leaves_a_pointer(curate) -> None:
    split = curate.Split("## Patterns — Big", "patterns.md", "you need the big patterns")
    body, refs = curate._split_sections(DOC, [split])
    assert list(refs) == ["patterns.md"]
    moved = refs["patterns.md"]
    assert moved.startswith("## Patterns — Big\n\nLead.\n")
    assert "## not a heading" in moved  # fenced code is not a section boundary
    assert "Back to [Intro](../SKILL.md#intro)." in moved
    assert "## Checklist" not in moved
    assert (
        "## Patterns — Big\n\nRead [references/patterns.md](references/patterns.md) "
        "when you need the big patterns.\n\n## Checklist" in body
    )
    assert "[Deep part](references/patterns.md#deep-part)" in body
    assert "[Intro](#intro)" in body
    # nothing is lost: every original line is in the body or the reference
    for line in DOC.splitlines():
        assert line in body or line in moved or "](#" in line


def test_split_nested_heading_stops_at_same_level(curate) -> None:
    body, refs = curate._split_sections(DOC, [curate.Split("### Deep part", "deep.md", "deep")])
    assert refs["deep.md"].rstrip().endswith("Back to [Intro](../SKILL.md#intro).")
    assert "## Checklist" in body


def test_split_missing_heading_fails(curate) -> None:
    with pytest.raises(ValueError, match="heading not found"):
        curate._split_sections(DOC, [curate.Split("## Gone", "gone.md", "never")])
