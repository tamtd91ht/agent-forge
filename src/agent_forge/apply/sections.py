"""Marker-delimited managed sections inside shared files (CLAUDE.md, AGENTS.md).

Agent Forge never rewrites a shared file. It only inserts, replaces or removes a block
delimited by:

    <!-- agent-forge:begin id=<section_id> capability=<cap_id> version=<ver> -->
    ...managed content...
    <!-- agent-forge:end id=<section_id> -->

Everything outside the markers is preserved byte-for-byte (after newline normalisation of
the inserted block only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_forge.errors import ApplyError

_BEGIN_TMPL = "<!-- agent-forge:begin id={sid} capability={cid} version={ver} -->"
_END_TMPL = "<!-- agent-forge:end id={sid} -->"
_ID_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"


def _begin_re(sid: str) -> re.Pattern[str]:
    return re.compile(
        rf"^[ \t]*<!--\s*agent-forge:begin\s+id={re.escape(sid)}(?:\s+capability=({_ID_RE}))?(?:\s+version=(\S+))?\s*-->[ \t]*$",
        re.MULTILINE,
    )


def _end_re(sid: str) -> re.Pattern[str]:
    return re.compile(
        rf"^[ \t]*<!--\s*agent-forge:end\s+id={re.escape(sid)}\s*-->[ \t]*$", re.MULTILINE
    )


_ANY_BEGIN = re.compile(
    rf"^[ \t]*<!--\s*agent-forge:begin\s+id=({_ID_RE})(?:\s+capability=({_ID_RE}))?(?:\s+version=(\S+))?\s*-->[ \t]*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SectionInfo:
    section_id: str
    capability_id: str | None
    version: str | None
    start: int
    end: int
    body: str


def render_block(section_id: str, capability_id: str, version: str, body: str) -> str:
    body = body.strip("\n")
    return (
        _BEGIN_TMPL.format(sid=section_id, cid=capability_id, ver=version)
        + "\n"
        + body
        + "\n"
        + _END_TMPL.format(sid=section_id)
        + "\n"
    )


def find_section(text: str, section_id: str) -> SectionInfo | None:
    b = _begin_re(section_id).search(text)
    if not b:
        return None
    e = _end_re(section_id).search(text, b.end())
    if not e:
        raise ApplyError(
            f"section {section_id!r} has a begin marker but no end marker; refusing to touch the file"
        )
    body = text[b.end() : e.start()].strip("\n")
    return SectionInfo(section_id, b.group(1), b.group(2), b.start(), e.end(), body)


def list_sections(text: str) -> list[SectionInfo]:
    out: list[SectionInfo] = []
    for m in _ANY_BEGIN.finditer(text):
        info = find_section(text, m.group(1))
        if info:
            out.append(info)
    return out


def upsert_section(
    text: str | None, section_id: str, capability_id: str, version: str, body: str
) -> str:
    """Return the file content with the managed section inserted (at end) or replaced in place."""
    block = render_block(section_id, capability_id, version, body)
    if text is None or text == "":
        return block
    existing = find_section(text, section_id)
    if existing is None:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        return text + sep + block
    # replace in place; keep the trailing newline handling identical to the original end marker
    after = text[existing.end :]
    before = text[: existing.start]
    if after.startswith("\n"):
        after = after[1:]
    return before + block + after


def remove_section(text: str, section_id: str) -> str:
    existing = find_section(text, section_id)
    if existing is None:
        return text
    before = text[: existing.start]
    after = text[existing.end :]
    if after.startswith("\n"):
        after = after[1:]
    if before.endswith("\n\n") and (after == "" or after.startswith("\n")):
        before = before[:-1]
    result = before + after
    return result
