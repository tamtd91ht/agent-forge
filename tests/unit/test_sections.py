from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_forge.apply.sections import find_section, list_sections, remove_section, upsert_section
from agent_forge.errors import ApplyError

USER = "# Title\n\nUser text that must survive.\n\n- item\n"


def test_insert_into_missing_file() -> None:
    out = upsert_section(None, "s1", "cap.a", "1.0.0", "Body")
    assert out.startswith("<!-- agent-forge:begin id=s1 capability=cap.a version=1.0.0 -->\n")
    assert out.endswith("<!-- agent-forge:end id=s1 -->\n")


def test_append_preserves_user_content() -> None:
    out = upsert_section(USER, "s1", "cap.a", "1.0.0", "Body")
    assert out.startswith(USER)
    info = find_section(out, "s1")
    assert info is not None and info.body == "Body" and info.version == "1.0.0"


def test_replace_in_place_keeps_surroundings() -> None:
    first = upsert_section(USER, "s1", "cap.a", "1.0.0", "Body v1")
    trailing = first + "\nUser appended after the block.\n"
    second = upsert_section(trailing, "s1", "cap.a", "1.1.0", "Body v2")
    assert second.startswith(USER)
    assert second.endswith("\nUser appended after the block.\n")
    assert find_section(second, "s1").body == "Body v2"
    assert second.count("agent-forge:begin") == 1


def test_remove_restores_original() -> None:
    with_block = upsert_section(USER, "s1", "cap.a", "1.0.0", "Body")
    assert remove_section(with_block, "s1") == USER


def test_multiple_sections_independent() -> None:
    text = upsert_section(USER, "a", "cap.a", "1.0.0", "A")
    text = upsert_section(text, "b", "cap.b", "1.0.0", "B")
    assert [s.section_id for s in list_sections(text)] == ["a", "b"]
    text = remove_section(text, "a")
    assert find_section(text, "a") is None
    assert find_section(text, "b").body == "B"


def test_unterminated_block_is_refused() -> None:
    broken = USER + "<!-- agent-forge:begin id=s1 capability=c version=1.0.0 -->\nno end\n"
    with pytest.raises(ApplyError):
        find_section(broken, "s1")


@settings(max_examples=60, deadline=None)
@given(
    prefix=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200).filter(
        lambda s: "agent-forge:" not in s
    ),
    body=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=200
    ).filter(
        lambda s: (
            "agent-forge:" not in s and s.strip("\n") == s.strip("\n").strip("\n") and s.strip("\n")
        )
    ),
)
def test_upsert_then_remove_is_identity_modulo_trailing_newlines(prefix: str, body: str) -> None:
    text = prefix
    with_block = upsert_section(text, "sx", "cap.x", "1.0.0", body)
    assert find_section(with_block, "sx").body == body.strip("\n")
    back = remove_section(with_block, "sx")
    assert back.rstrip("\n") == text.rstrip("\n")
