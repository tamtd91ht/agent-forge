"""Cross-manifest registry validation (beyond per-manifest schema checks)."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_forge.models.capability import (
    CapabilityStatus,
    InstallStrategy,
    MergeStrategy,
    RiskLevel,
)
from agent_forge.registry.content_safety import scan_assets
from agent_forge.registry.loader import Registry
from agent_forge.util import parse_frontmatter


@dataclass
class RegistryReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_registry(reg: Registry) -> RegistryReport:
    rep = RegistryReport()
    rep.errors.extend(reg.problems)
    ids = set(reg.items)
    for cid, lc in sorted(reg.items.items()):
        cap = lc.capability
        for dep in cap.dependency_ids:
            if dep in reg.items:
                why = cap.unsatisfied_dependency(dep, reg.items[dep].capability.version)
                if why:
                    rep.errors.append(why)
            if dep not in ids:
                rep.errors.append(f"{cid}: dependency {dep!r} does not exist in the registry")
            elif (
                reg.items[dep].capability.status != CapabilityStatus.CURATED
                and cap.status == CapabilityStatus.CURATED
            ):
                rep.errors.append(f"{cid}: curated capability depends on non-curated {dep!r}")
        for conf in cap.conflicts:
            if conf not in ids:
                rep.warnings.append(f"{cid}: conflict target {conf!r} does not exist (ignored)")
            elif cid not in reg.items[conf].capability.conflicts:
                rep.warnings.append(f"{cid}: conflict with {conf!r} is not declared symmetrically")
        if cap.install_strategy in (InstallStrategy.FILE_COPY, InstallStrategy.SECTION_MERGE):
            if not lc.assets_dir.is_dir():
                rep.errors.append(f"{cid}: assets directory missing: {lc.assets_dir}")
            else:
                _check_markdown_links(cid, lc.assets_dir, rep)
                _check_license_notice(cid, cap, lc.assets_dir, rep)
            for dest in cap.destinations:
                src = lc.assets_dir / dest.source
                if not src.exists():
                    rep.errors.append(f"{cid}: destination source missing: assets/{dest.source}")
                elif dest.merge == MergeStrategy.APPEND_SECTION and not src.is_file():
                    rep.errors.append(
                        f"{cid}: append_section source must be a file: assets/{dest.source}"
                    )
                elif src.is_symlink():
                    rep.errors.append(
                        f"{cid}: asset is a symlink (not allowed): assets/{dest.source}"
                    )
        if cap.integrity is not None and cap.integrity.assets_sha256 != lc.assets_digest:
            rep.errors.append(
                f"{cid}: assets digest {lc.assets_digest[:12]} does not match pinned integrity "
                f"{cap.integrity.assets_sha256[:12]} (assets edited? re-pin with scripts/pin_integrity.py)"
            )
        elif cap.integrity is None and cap.status == CapabilityStatus.CURATED:
            rep.warnings.append(f"{cid}: no pinned integrity digest (run scripts/pin_integrity.py)")
        if cap.license.notice_file:
            nf = lc.assets_dir / cap.license.notice_file
            if not nf.is_file():
                rep.errors.append(
                    f"{cid}: license.notice_file not found: assets/{cap.license.notice_file}"
                )
        if cap.status == CapabilityStatus.CURATED and not cap.review.rationale.strip():
            rep.errors.append(f"{cid}: curated capability needs a review rationale")
        if (
            cap.status == CapabilityStatus.CURATED
            and cap.risk != RiskLevel.LOW
            and not (cap.review.risk_rationale or "").strip()
        ):
            rep.errors.append(
                f"{cid}: risk {cap.risk.value} needs review.risk_rationale (why, and what limits it)"
            )
        if cap.replaced_by is not None and cap.replaced_by not in ids:
            rep.errors.append(f"{cid}: replaced_by {cap.replaced_by!r} does not exist")
        if cap.status == CapabilityStatus.CURATED:
            _check_content_safety(cid, lc.assets_dir, cap.review.acknowledged_findings, rep)
        if (
            cap.status == CapabilityStatus.CURATED
            and cap.source.source_id != "workspace"
            and not cap.source.revision
        ):
            rep.errors.append(
                f"{cid}: upstream-derived curated capability must record source.revision"
            )
    _check_dependency_cycles(reg, rep)
    _check_skill_calls(reg, rep)
    return rep


_CODE_RE = re.compile(r"^(```|~~~).*?^\1|`[^`\n]*`", re.MULTILINE | re.DOTALL)
_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")


def _check_license_notice(cid: str, cap, assets_dir: Path, rep: RegistryReport) -> None:
    nf = cap.license.notice_file
    if nf and not (assets_dir / nf).is_file():
        rep.errors.append(f"{cid}: license.notice_file {nf!r} is missing from assets/")


def _check_markdown_links(cid: str, assets_dir: Path, rep: RegistryReport) -> None:
    """Relative links in curated markdown must point at files shipped alongside them.

    Curating a subset of upstream files easily leaves links to the files that were left out.
    """
    for md in sorted(assets_dir.rglob("*.md")):
        text = _CODE_RE.sub("", md.read_text(encoding="utf-8", errors="replace"))
        for target in _LINK_RE.findall(text):
            path = target.split("#", 1)[0]
            if not path or ":" in path or path.startswith("/"):
                continue  # anchor, URL / mailto, or absolute
            if not (md.parent / path).exists():
                rel = md.relative_to(assets_dir).as_posix()
                rep.errors.append(f"{cid}: broken link in assets/{rel}: {target}")


def _check_content_safety(cid: str, assets_dir: Path, acks: list, rep: RegistryReport) -> None:
    """Unacknowledged content-safety findings are errors; acknowledgements that no longer match
    anything are warnings (stale review notes hide the next real finding)."""
    used: set[int] = set()
    for f in scan_assets(assets_dir):
        match = next(
            (
                i
                for i, a in enumerate(acks)
                if a.rule == f.rule and fnmatch.fnmatchcase(f.path, a.path)
            ),
            None,
        )
        if match is None:
            rep.errors.append(f"{cid}: unsafe content not acknowledged in review: {f.message}")
        else:
            used.add(match)
    for i, a in enumerate(acks):
        if i not in used:
            rep.warnings.append(f"{cid}: acknowledged finding {a.rule} @ {a.path} no longer occurs")


_FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
# `Call the Skill tool with "grilling"` / `Call the Skill tool twice, for "a" and "b"`.
_SKILL_CALL_RE = re.compile(
    r"Skill tool(?:\s+\w+)?,?\s+(?:with|for)\s+"
    r"((?:[\"`][\w.-]+[\"`](?:,?\s+(?:and|or)\s+|,\s*)?)+)"
)
_QUOTED_RE = re.compile(r"[\"`]([\w.-]+)[\"`]")


def _shipped_skills(assets_dir: Path) -> dict[str, bool]:
    """Skill names shipped in `assets_dir` -> whether the skill is user-invoked only."""
    out: dict[str, bool] = {}
    if not assets_dir.is_dir():
        return out
    for md in assets_dir.rglob("SKILL.md"):
        fm, _ = parse_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        name = str(fm.get("name") or md.parent.name)
        out[name] = fm.get("disable-model-invocation") is True
    return out


def _check_skill_calls(reg: Registry, rep: RegistryReport) -> None:
    """A skill that tells the agent to call another skill must ship with it.

    The called skill has to come from the same capability or one of its (transitive)
    dependencies, and it must be model-invoked: a user-invoked skill cannot be reached
    through the Skill tool, only by the human typing its name.
    """
    shipped = {cid: _shipped_skills(lc.assets_dir) for cid, lc in reg.items.items()}
    for cid, lc in sorted(reg.items.items()):
        if not shipped[cid]:
            continue
        provided: dict[str, bool] = {}
        stack, seen = [cid], set()
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in reg.items:
                continue
            seen.add(cur)
            provided.update(shipped[cur])
            stack.extend(reg.items[cur].capability.dependency_ids)
        for md in sorted(lc.assets_dir.rglob("SKILL.md")):
            text = _FENCE_RE.sub("", md.read_text(encoding="utf-8", errors="replace"))
            rel = md.relative_to(lc.assets_dir).as_posix()
            for group in _SKILL_CALL_RE.findall(text):
                for name in _QUOTED_RE.findall(group):
                    if name not in provided:
                        rep.errors.append(
                            f"{cid}: assets/{rel} calls skill {name!r}, which neither this "
                            "capability nor its dependencies ship"
                        )
                    elif provided[name]:
                        rep.errors.append(
                            f"{cid}: assets/{rel} calls skill {name!r}, which is user-invoked "
                            "(disable-model-invocation) and cannot be called by another skill"
                        )


def _check_dependency_cycles(reg: Registry, rep: RegistryReport) -> None:
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        st = state.get(node, 0)
        if st == 1:
            cycle = " -> ".join([*stack[stack.index(node) :], node])
            rep.errors.append(f"dependency cycle: {cycle}")
            return
        if st == 2 or node not in reg.items:
            return
        state[node] = 1
        for dep in reg.items[node].capability.dependency_ids:
            visit(dep, [*stack, node])
        state[node] = 2

    for cid in reg.items:
        visit(cid, [])


def resolve_dependencies(reg: Registry, selected: list[str]) -> list[str]:
    """Topologically order `selected` plus their transitive dependencies (deps first)."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(cid: str) -> None:
        if cid in seen:
            return
        seen.add(cid)
        for dep in reg.get(cid).capability.dependency_ids:
            visit(dep)
        order.append(cid)

    for cid in selected:
        visit(cid)
    return order
