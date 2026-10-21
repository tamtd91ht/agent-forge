"""Decision records (ADR-0007): model, verification, evidence drift, diff, usage log, policy
`required` / `forbidden`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_forge.decisions import diff_records, evidence_drift, latest_record_path, load_record
from agent_forge.decisions.usage import usage_summary
from agent_forge.decisions.verify import verify_record
from agent_forge.errors import PlanError, UsageError
from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import Platform
from agent_forge.models.decision import DecisionRecord, Verdict
from agent_forge.policy.engine import Decision as PolicyDecision
from agent_forge.policy.engine import Policy, PolicySet
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project

NOW = "2026-10-21T00:00:00+00:00"


def _record(*decisions: dict, plan_id: str = "plan-1") -> DecisionRecord:
    base = {"confidence": "high", "reason": "test"}
    return DecisionRecord.model_validate(
        {
            "plan_id": plan_id,
            "assessed_by": "pytest",
            "assessed_at": NOW,
            "decisions": [{**base, **d} for d in decisions],
        }
    )


def _write_record(root: Path, record: DecisionRecord, name: str | None = None) -> Path:
    d = root / ".agent-forge" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name or record.plan_id}.json"
    p.write_text(json.dumps(record.model_dump(mode="json"), indent=1), encoding="utf-8")
    return p


@pytest.fixture
def ctx(synthetic_registry, make_project):
    reg = load_registry(synthetic_registry, strict=True)
    root = make_project(
        "decided",
        kind="claude",
        files={".claude/rules/testing.md": "# Testing\n\nAlways write the failing test first.\n"},
    )
    profile = scan_project(root)
    return reg, root, profile


# ---- model ---------------------------------------------------------------------------------


def test_record_round_trip_and_digest(tmp_path: Path) -> None:
    rec = _record(
        {
            "capability_id": "t.always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": ["CLAUDE.md"],
        }
    )
    assert rec.decisions[0].covered_by[0].path == "CLAUDE.md"  # bare path -> citation
    assert rec.decisions[0].covered_by[0].quote is None
    p = _write_record(tmp_path, rec)
    again = load_record(p)
    assert again.digest() == rec.digest()
    assert latest_record_path(tmp_path) == p


def test_invalid_record_is_a_plan_error(tmp_path: Path) -> None:
    d = tmp_path / ".agent-forge" / "decisions"
    d.mkdir(parents=True)
    (d / "x.json").write_text(
        '{"plan_id": "x", "decisions": [{"verdict": "MAYBE"}]}', encoding="utf-8"
    )
    with pytest.raises(PlanError, match="invalid decision record"):
        load_record(d / "x.json")
    (d / "y.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(PlanError, match="not valid JSON"):
        load_record(d / "y.json")


# ---- verification --------------------------------------------------------------------------


def test_proven_skip_stays_skip_and_unprovable_skip_becomes_ask(ctx) -> None:
    reg, _root, profile = ctx
    rec = _record(
        {
            "capability_id": "t.always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": ".claude/rules/testing.md", "quote": "failing test first"}],
        },
        {
            "capability_id": "t.python-only",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": ".claude/rules/testing.md", "quote": "this line is invented"}],
        },
        {"capability_id": "t.tagged", "verdict": "SKIP", "grounds": ["covered"]},  # no citation
        {"capability_id": "t.equiv", "verdict": "SKIP"},  # no ground at all
        {
            "capability_id": "t.needs-always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": "../outside.md", "quote": "x"}],
        },
    )
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE)
    by = {i.decision.capability_id: i for i in rep.items}
    assert by["t.always"].verified and by["t.always"].effective == Verdict.SKIP
    assert by["t.python-only"].effective == Verdict.ASK
    assert any("quote not found" in f.message for f in by["t.python-only"].findings)
    assert by["t.tagged"].effective == Verdict.ASK
    assert by["t.equiv"].effective == Verdict.ASK
    assert any("without a ground" in f.message for f in by["t.equiv"].findings)
    assert by["t.needs-always"].effective == Verdict.ASK  # traversal refused, never read
    assert not rep.ok and len(rep.downgraded) == 4
    doc = rep.to_dict()
    assert doc["effective"]["ASK"] == ["t.python-only", "t.tagged", "t.equiv", "t.needs-always"]
    assert doc["downgraded"][0]["from"] == "SKIP" and doc["downgraded"][0]["to"] == "ASK"


def test_quote_matching_ignores_line_breaks_and_case(ctx) -> None:
    reg, root, profile = ctx
    (root / "CLAUDE.md").write_text(
        "# Project\n\nUse  the\nfailing test\n  FIRST.\n", encoding="utf-8"
    )
    rec = _record(
        {
            "capability_id": "t.always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": "CLAUDE.md", "quote": "use the failing test first"}],
        }
    )
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE)
    assert rep.ok


def test_catalog_numbers_and_grounds_are_checked(ctx) -> None:
    reg, _root, profile = ctx
    rec = _record(
        {"capability_id": "t.always", "verdict": "SKIP", "grounds": ["stack_mismatch"]},
        {
            "capability_id": "t.python-only",
            "verdict": "SKIP",
            "grounds": ["context_cost"],
            "context_chars": 9999,
        },
        {"capability_id": "t.tagged", "verdict": "SKIP", "grounds": ["evidence_worse"]},
        {"capability_id": "t.equiv", "verdict": "SKIP", "grounds": ["security"]},
        {"capability_id": "t.hook", "verdict": "SKIP", "grounds": ["security"], "risk": ["hook"]},
        {
            "capability_id": "t.needs-always",
            "verdict": "ADD",
            "gap": "none",
            "evidence": "improved",
        },
        {"capability_id": "t.nope", "verdict": "SKIP", "grounds": ["covered"]},
        {"capability_id": "t.conflicts-always", "verdict": "UPGRADE"},
    )
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE)
    by = {i.decision.capability_id: i for i in rep.items}
    assert any(f.check == "stack_mismatch" for f in by["t.always"].findings)  # it applies
    assert any("!= catalog" in f.message for f in by["t.python-only"].findings)
    assert any(f.check == "evidence_worse" for f in by["t.tagged"].findings)
    assert any("declares no permissions" in f.message for f in by["t.equiv"].findings)
    assert by["t.hook"].verified and by["t.hook"].effective == Verdict.SKIP  # a hook is risky
    assert any(f.check == "evidence" and f.level == "error" for f in by["t.needs-always"].findings)
    assert by["t.needs-always"].effective == Verdict.ADD  # an ADD is never silently changed
    assert any("not in the catalog" in f.message for f in by["t.nope"].findings)
    assert any("not installed" in f.message for f in by["t.conflicts-always"].findings)


def test_stack_mismatch_holds_when_the_capability_does_not_apply(ctx) -> None:
    reg, root, profile = ctx
    (root / "pyproject.toml").unlink()
    (root / "src" / "main.py").unlink()
    (root / "package.json").write_text(
        '{"name": "web", "dependencies": {"react": "18"}}', encoding="utf-8"
    )
    profile = scan_project(root)
    rec = _record(
        {"capability_id": "t.python-only", "verdict": "SKIP", "grounds": ["stack_mismatch"]}
    )
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE)
    assert rep.ok and rep.items[0].effective == Verdict.SKIP


def test_policy_required_and_denied_override_the_agent(ctx) -> None:
    reg, _root, profile = ctx
    ps = PolicySet(
        [
            (
                "project",
                Policy(capabilities={"required": ["t.always"], "forbidden": ["t.tagged"]}),
            )
        ]
    )
    rec = _record(
        {
            "capability_id": "t.always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": ".claude/rules/testing.md", "quote": "failing test first"}],
        },
        {"capability_id": "t.tagged", "verdict": "ADD", "gap": "a gap"},
    )
    rep = verify_record(rec, reg, profile, policy=ps, platform=Platform.CLAUDE_CODE)
    by = {i.decision.capability_id: i for i in rep.items}
    assert by["t.always"].effective == Verdict.ADD and any(
        "required by policy" in f.message for f in by["t.always"].findings
    )
    assert by["t.tagged"].effective == Verdict.SKIP and any(
        "denied by policy" in f.message for f in by["t.tagged"].findings
    )
    # required capabilities the agent did not even assess are named
    ps2 = PolicySet([("project", Policy(capabilities={"required": ["t.python-only"]}))])
    rep2 = verify_record(rec, reg, profile, policy=ps2, platform=Platform.CLAUDE_CODE)
    assert any("required by policy but not assessed: t.python-only" in n for n in rep2.notes)


# ---- usage log and the `unused` ground -----------------------------------------------------


def _install_by_hand(root: Path, cid: str, skill: str, days_ago: int) -> None:
    (root / ".claude" / "skills" / skill).mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "skills" / skill / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: d\n---\n# {skill}\n", encoding="utf-8"
    )
    installed_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    manifest = {
        "version": "1",
        "capabilities": [
            {
                "capability_id": cid,
                "version": "1.0.0",
                "transaction_id": "tx-1",
                "installed_at": installed_at,
                "files": {f".claude/skills/{skill}/SKILL.md": "0" * 64},
            }
        ],
    }
    (root / ".agent-forge").mkdir(exist_ok=True)
    (root / ".agent-forge" / "managed.json").write_text(json.dumps(manifest), encoding="utf-8")


def _log(root: Path, *entries: tuple[int, str, str]) -> None:
    lines = []
    for days_ago, kind, ident in entries:
        at = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(json.dumps({"at": at, "kind": kind, "id": ident, "session": "s1"}))
    lines.append("not json")
    (root / ".agent-forge").mkdir(exist_ok=True)
    (root / ".agent-forge" / "usage.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_usage_summary_maps_names_to_capabilities_and_flags_unused(make_project) -> None:
    root = make_project("used", kind="claude")
    _install_by_hand(root, "t.always", "always", days_ago=40)
    assert usage_summary(scan_project(root))["log_present"] is False
    _log(root, (20, "skill", "other"), (3, "agent", "reviewer"))
    data = usage_summary(scan_project(root))
    row = data["by_capability"][0]
    assert row["capability"] == "t.always" and row["invocations"] == 0 and row["unused"]
    assert data["unused"] == ["t.always"] and data["observed_days"] >= 14
    assert data["unmanaged"] == {"skill:other": 1, "agent:reviewer": 1}
    _log(root, (20, "skill", "other"), (2, "skill", "always"))
    data = usage_summary(scan_project(root))
    assert data["by_capability"][0]["invocations"] == 1 and data["unused"] == []
    # a log that only started yesterday proves nothing yet
    _log(root, (1, "skill", "other"))
    assert usage_summary(scan_project(root))["unused"] == []


def test_unused_ground_needs_the_log_and_zero_invocations(synthetic_registry, make_project) -> None:
    reg = load_registry(synthetic_registry, strict=True)
    root = make_project("unusedp", kind="claude")
    _install_by_hand(root, "t.always", "always", days_ago=40)
    rec = _record({"capability_id": "t.always", "verdict": "REMOVE", "grounds": ["unused"]})
    profile = scan_project(root)
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE)
    assert (
        rep.items[0].effective == Verdict.ASK and "no usage log" in rep.items[0].findings[0].message
    )
    _log(root, (20, "skill", "other"))
    usage = usage_summary(profile)
    rep = verify_record(rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE, usage=usage)
    assert rep.ok and rep.items[0].effective == Verdict.REMOVE
    _log(root, (20, "skill", "other"), (1, "skill", "always"))
    rep = verify_record(
        rec, reg, profile, policy=None, platform=Platform.CLAUDE_CODE, usage=usage_summary(profile)
    )
    assert rep.items[0].effective == Verdict.ASK


# ---- drift of the evidence and diff --------------------------------------------------------


def test_evidence_drift_reports_missing_files_and_quotes(ctx) -> None:
    _reg, root, _profile = ctx
    rec = _record(
        {
            "capability_id": "t.always",
            "verdict": "SKIP",
            "grounds": ["covered"],
            "covered_by": [{"path": ".claude/rules/testing.md", "quote": "failing test first"}],
        },
        {
            "capability_id": "t.tagged",
            "verdict": "SKIP",
            "grounds": ["conflicts"],
            "contradicts": ["CLAUDE.md"],
        },
    )
    assert evidence_drift(rec, root) == []
    (root / ".claude" / "rules" / "testing.md").write_text(
        "# Testing\n\nchanged\n", encoding="utf-8"
    )
    (root / "CLAUDE.md").unlink()
    items = evidence_drift(rec, root)
    states = {(i.capability_id, i.state) for i in items}
    assert states == {("t.always", "quote_missing"), ("t.tagged", "basis_missing")}


def test_diff_records_shows_only_changes() -> None:
    old = _record(
        {"capability_id": "a", "verdict": "SKIP", "grounds": ["covered"], "reason": "old"},
        {"capability_id": "b", "verdict": "ADD", "gap": "g"},
        {"capability_id": "c", "verdict": "ASK"},
    )
    new = _record(
        {"capability_id": "a", "verdict": "ADD", "gap": "now a gap", "reason": "new"},
        {"capability_id": "b", "verdict": "ADD", "gap": "g"},
        {"capability_id": "d", "verdict": "SKIP", "grounds": ["unused"]},
        plan_id="plan-2",
    )
    changes = {c["capability_id"]: c for c in diff_records(old, new)}
    assert set(changes) == {"a", "c", "d"}
    assert changes["a"]["change"] == "changed" and changes["a"]["old"]["reason"] == "old"
    assert changes["c"]["change"] == "dropped" and changes["d"]["change"] == "new"


# ---- policy required / forbidden -----------------------------------------------------------


def test_required_capability_is_planned_and_cannot_be_excluded(
    synthetic_registry, make_project
) -> None:
    reg = load_registry(synthetic_registry, strict=True)
    root = make_project("req", kind="claude", files={"package.json": '{"name": "web"}'})
    (root / "pyproject.toml").unlink()
    profile = scan_project(root)
    ps = PolicySet([("project", Policy(capabilities={"required": ["t.python-only"]}))])
    plain = evaluate(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,)))
    assert "t.python-only" in {r.capability.id for r in plain.rejected}  # not a python project
    required = evaluate(reg, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=ps))
    chosen = {c.capability.id: c for c in required.recommended}
    assert "t.python-only" in chosen and "required by policy" in chosen["t.python-only"].reasons
    with pytest.raises(UsageError, match=r"policy requires t.python-only"):
        evaluate(
            reg,
            profile,
            MatchContext(
                platforms=(Platform.CLAUDE_CODE,),
                policy=ps,
                excluded_ids=frozenset({"t.python-only"}),
            ),
        )


def test_forbidden_is_the_same_verdict_as_deny(synthetic_registry) -> None:
    reg = load_registry(synthetic_registry, strict=True)
    cap = reg.get("t.always").capability
    ps = PolicySet([("ws", Policy(capabilities={"forbidden": ["t.*"]}))])
    verdict, why = ps.evaluate(cap, Platform.CLAUDE_CODE)
    assert verdict == PolicyDecision.DENY and any("forbidden" in w for w in why)
    assert ps.is_required("t.always") is False and ps.required_patterns() == []
