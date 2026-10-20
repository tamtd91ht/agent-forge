"""Summaries with uncertainty: pass rates carry a Wilson 95% interval, never a bare mean."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from agent_forge_eval.harness import RunRecord

Z95 = 1.959963984540054


def wilson(passed: int, total: int, z: float = Z95) -> tuple[float, float, float]:
    """(rate, low, high) Wilson score interval; (0, 0, 0) for an empty sample."""
    if total == 0:
        return 0.0, 0.0, 0.0
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarise(records: list[RunRecord]) -> dict[str, Any]:
    """Per arm and per (arm, category): pass rate + CI, regression rate, wall, tokens, cost."""
    by_arm: dict[str, list[RunRecord]] = defaultdict(list)
    by_arm_cat: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for r in records:
        by_arm[r.arm].append(r)
        by_arm_cat[(r.arm, r.category)].append(r)

    def block(rs: list[RunRecord]) -> dict[str, Any]:
        passed = sum(1 for r in rs if r.passed)
        rate, lo, hi = wilson(passed, len(rs))
        regs = [r for r in rs if r.regression_passed is not None]
        reg_fail = sum(1 for r in regs if not r.regression_passed)
        return {
            "runs": len(rs),
            "passed": passed,
            "pass_rate": round(rate, 3),
            "ci95": [round(lo, 3), round(hi, 3)],
            "regressions": reg_fail if regs else None,
            "timeouts": sum(1 for r in rs if r.tool.timed_out),
            "mean_wall_seconds": _round(_mean([r.tool.wall_seconds for r in rs])),
            "mean_tokens_out": _round(
                _mean([r.tool.tokens_out for r in rs if r.tool.tokens_out is not None])
            ),
            "mean_cost_usd": _round(
                _mean([r.tool.cost_usd for r in rs if r.tool.cost_usd is not None]), 4
            ),
            "mean_changed_files": _round(_mean([float(r.changed_files) for r in rs])),
        }

    arms = {arm: block(rs) for arm, rs in sorted(by_arm.items())}
    categories: dict[str, dict[str, Any]] = defaultdict(dict)
    for (arm, cat), rs in sorted(by_arm_cat.items()):
        categories[cat][arm] = block(rs)
    verdict = compare(arms.get("baseline"), arms.get("candidate"))
    return {"arms": arms, "categories": dict(categories), "verdict": verdict}


def compare(base: dict[str, Any] | None, cand: dict[str, Any] | None) -> dict[str, Any]:
    """A plain statement: improved / no_evidence / worse. 'improved' needs the candidate's
    lower bound above the baseline's point estimate; anything overlapping is no evidence."""
    if not base or not cand:
        return {"status": "incomplete", "reason": "both arms are needed"}
    delta = cand["pass_rate"] - base["pass_rate"]
    if cand["ci95"][0] > base["pass_rate"] and delta > 0:
        status = "improved"
    elif cand["ci95"][1] < base["pass_rate"] and delta < 0:
        status = "worse"
    else:
        status = "no_evidence"
    return {
        "status": status,
        "delta_pass_rate": round(delta, 3),
        "baseline": base["pass_rate"],
        "candidate": cand["pass_rate"],
        "note": "confidence intervals are Wilson 95%; with few runs they are wide by design",
    }


def _round(v: float | None, nd: int = 1) -> float | None:
    return None if v is None else round(v, nd)


def to_markdown(meta: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation: {meta.get('capability')} on {meta.get('fixture')}",
        "",
        f"- tool: `{meta.get('tool')}` · runs per task and arm: {meta.get('runs')} · tasks: {meta.get('tasks')}",
        f"- agent-forge: {meta.get('agent_forge_version')} · registry digest: {str(meta.get('registry_digest', ''))[:16]}",
        f"- date: {meta.get('date')} · verdict: **{summary['verdict']['status']}** "
        f"(Δ pass rate {summary['verdict'].get('delta_pass_rate')})",
        "",
        "| arm | runs | pass rate | 95% CI | regressions | timeouts | mean wall s | mean tokens out | mean cost $ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, b in summary["arms"].items():
        lines.append(
            f"| {arm} | {b['runs']} | {b['pass_rate']} | {b['ci95'][0]}-{b['ci95'][1]} | "
            f"{_na(b['regressions'])} | {b['timeouts']} | {_na(b['mean_wall_seconds'])} | "
            f"{_na(b['mean_tokens_out'])} | {_na(b['mean_cost_usd'])} |"
        )
    if summary["categories"]:
        lines += [
            "",
            "## By task category",
            "",
            "| category | arm | runs | pass rate | 95% CI |",
            "|---|---|---|---|---|",
        ]
        for cat, arms in summary["categories"].items():
            for arm, b in arms.items():
                lines.append(
                    f"| {cat} | {arm} | {b['runs']} | {b['pass_rate']} | {b['ci95'][0]}-{b['ci95'][1]} |"
                )
    lines += [
        "",
        "Unavailable metrics are shown as n/a, not estimated. Subjective code-quality review, if",
        "any, is recorded separately and never by the agent that produced the change.",
        "",
    ]
    return "\n".join(lines)


def _na(v: Any) -> str:
    return "n/a" if v is None else str(v)
