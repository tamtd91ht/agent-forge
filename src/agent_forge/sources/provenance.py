"""Provenance checks: does a capability's recorded upstream revision exist in the checkout?"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from agent_forge.models.capability import Capability
from agent_forge.sources.manager import SourceManager


@dataclass
class ProvenanceResult:
    capability_id: str
    source_id: str
    revision: str | None
    checkout_present: bool
    revision_present: bool | None  # None = could not check
    paths_present: list[str]
    paths_missing: list[str]
    note: str = ""


def verify_capability_provenance(cap: Capability, manager: SourceManager) -> ProvenanceResult:
    src = cap.source
    if src.source_id == "workspace":
        return ProvenanceResult(
            cap.id, src.source_id, None, False, None, [], [], "workspace-authored"
        )
    try:
        spec = manager.get(src.source_id)
    except Exception as exc:  # SourceError
        return ProvenanceResult(cap.id, src.source_id, src.revision, False, None, [], [], str(exc))
    checkout = manager.checkout_dir(spec)
    present = (checkout / ".git").exists()
    if not present:
        return ProvenanceResult(
            cap.id, src.source_id, src.revision, False, None, [], [], "checkout missing"
        )
    rev_ok: bool | None = None
    if src.revision:
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"{src.revision}^{{commit}}"],
            cwd=str(checkout),
            capture_output=True,
            check=False,
        )
        rev_ok = proc.returncode == 0
    present_paths: list[str] = []
    missing_paths: list[str] = []
    for p in src.paths:
        if src.revision and rev_ok:
            proc = subprocess.run(
                ["git", "cat-file", "-e", f"{src.revision}:{p}"],
                cwd=str(checkout),
                capture_output=True,
                check=False,
            )
            (present_paths if proc.returncode == 0 else missing_paths).append(p)
        else:
            (present_paths if (checkout / p).exists() else missing_paths).append(p)
    return ProvenanceResult(
        cap.id, src.source_id, src.revision, True, rev_ok, present_paths, missing_paths
    )
