"""Catalog queries over the loaded registry."""

from __future__ import annotations

from dataclasses import dataclass

from agent_forge.models.capability import Capability, CapabilityStatus, Platform
from agent_forge.registry.loader import Registry


@dataclass(frozen=True)
class CatalogFilter:
    category: str | None = None
    platform: Platform | None = None
    project_type: str | None = None
    status: CapabilityStatus | None = None
    source: str | None = None
    kind: str | None = None
    language: str | None = None

    def matches(self, cap: Capability) -> bool:
        if self.category and cap.category != self.category:
            return False
        if self.platform and self.platform not in cap.platforms:
            return False
        if self.status and cap.status != self.status:
            return False
        if self.source and cap.source.source_id != self.source:
            return False
        if self.kind and cap.kind.value != self.kind:
            return False
        if self.project_type:
            pts = cap.applicability.project_types
            if pts and self.project_type not in pts:
                return False
        if self.language:
            langs = cap.applicability.languages
            if langs and self.language not in langs:
                return False
        return True


def query(reg: Registry, flt: CatalogFilter | None = None) -> list[Capability]:
    flt = flt or CatalogFilter()
    return [c for c in reg.capabilities() if flt.matches(c)]


def categories(reg: Registry) -> list[str]:
    return sorted({c.category for c in reg.capabilities()})
