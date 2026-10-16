"""Ranking of *valid* candidates. Scores never override hard rules."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_forge.models.capability import Capability, RiskLevel
from agent_forge.models.project import ProjectProfile

_RISK_PENALTY = {RiskLevel.LOW: 0.0, RiskLevel.MEDIUM: 1.0, RiskLevel.HIGH: 2.5}


@dataclass
class ScoreBreakdown:
    total: float = 0.0
    parts: list[tuple[str, float]] = field(default_factory=list)

    def add(self, label: str, value: float) -> None:
        self.parts.append((label, value))
        self.total += value

    def explain(self) -> list[str]:
        return [f"{label}: {value:+.1f}" for label, value in self.parts]


def score(
    cap: Capability, profile: ProjectProfile, *, wanted_tags: set[str], specificity: int
) -> ScoreBreakdown:
    sb = ScoreBreakdown()
    sb.add("benefit", float(cap.benefit_score))
    sb.add("maintenance cost", -float(cap.maintenance_cost) * 0.5)
    sb.add(f"risk {cap.risk.value}", -_RISK_PENALTY[cap.risk])
    if specificity:
        sb.add(f"matched {specificity} applicability condition(s)", 1.0 * specificity)
    if cap.applicability.always:
        sb.add("universal capability", 0.5)
    if wanted_tags & set(cap.applicability.tags):
        sb.add("requested via --want", 3.0)
    if cap.network.value != "none":
        sb.add(f"network {cap.network.value}", -0.5)
    if cap.permissions:
        sb.add(f"{len(cap.permissions)} permission(s)", -0.5 * len(cap.permissions))
    if cap.dependencies:
        sb.add(f"{len(cap.dependencies)} dependency(ies)", -0.25 * len(cap.dependencies))
    if not profile.test_commands and "verification" in cap.applicability.tags:
        sb.add(
            "project has no detected test command; verification guidance is less actionable", -1.0
        )
    return sb
