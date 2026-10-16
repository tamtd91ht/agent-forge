"""Equivalence and conflict detection against the target's existing agent assets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_forge.models.capability import Capability, Platform
from agent_forge.models.project import AgentAsset, ProjectProfile


@dataclass(frozen=True)
class EquivalenceHit:
    asset_path: str
    asset_kind: str
    matched_by: str
    description: str


def find_equivalents(
    cap: Capability, profile: ProjectProfile, platform: Platform
) -> list[EquivalenceHit]:
    """Existing assets that already provide (roughly) what `cap` provides."""
    hits: list[EquivalenceHit] = []
    for sig in cap.equivalents:
        if sig.platform is not None and sig.platform != platform:
            continue
        for asset in profile.assets:
            if asset.managed_by == cap.id:
                continue  # that's us, not an equivalent
            if asset.kind != sig.kind.value:
                continue
            if sig.platform is not None and asset.platform not in (sig.platform, None):
                continue
            for pat in sig.name_patterns:
                if re.search(pat, asset.name, re.IGNORECASE):
                    hits.append(
                        EquivalenceHit(asset.path, asset.kind, f"name ~ /{pat}/", sig.description)
                    )
                    break
            else:
                if sig.content_patterns and _content_matches(asset, sig.content_patterns):
                    hits.append(
                        EquivalenceHit(asset.path, asset.kind, "headings match", sig.description)
                    )
    return hits


def _content_matches(asset: AgentAsset, patterns: list[str]) -> bool:
    haystack = "\n".join(asset.headings)
    desc = asset.frontmatter.get("description")
    if isinstance(desc, str):
        haystack += "\n" + desc
    return any(re.search(p, haystack, re.IGNORECASE) for p in patterns)


def destination_collisions(
    cap: Capability, profile: ProjectProfile, platform: Platform
) -> list[str]:
    """Destination files/directories that already exist and are NOT managed by this capability."""
    out: list[str] = []
    for d in cap.destinations_for(platform):
        if d.merge.value != "create_only":
            continue
        dest = d.dest.rstrip("/")
        prefix = dest + "/"
        for a in profile.assets:
            if (a.path == dest or a.path.startswith(prefix)) and a.managed_by != cap.id:
                out.append(a.path)
    return sorted(set(out))


def declared_conflicts(cap: Capability, installed_or_selected: set[str]) -> list[str]:
    return sorted(c for c in cap.conflicts if c in installed_or_selected)
