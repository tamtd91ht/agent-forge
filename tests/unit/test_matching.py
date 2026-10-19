from __future__ import annotations

from pathlib import Path

from agent_forge.matching.rules import MatchContext, choose_platforms, evaluate
from agent_forge.models.capability import Platform
from agent_forge.policy.engine import Policy, PolicySet
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from tests.conftest import base_manifest, skill_assets, write_capability


def _ctx(*platforms: Platform, **kw) -> MatchContext:
    return MatchContext(platforms=platforms or (Platform.CLAUDE_CODE,), **kw)


def _result_ids(result):
    rec = {c.capability.id for c in result.recommended}
    opt = {c.capability.id for c in result.optional}
    rej = {r.capability.id: r.category for r in result.rejected}
    return rec, opt, rej


def test_applicability_and_status_rules(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("py"))
    rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx()))
    assert "t.always" in rec
    assert "t.python-only" in rec  # python project
    assert rej["t.tagged"] == "not_applicable"  # tag-only, not requested
    assert rej["t.under-review"] == "not_curated"
    assert rej["t.native"] == "not_applicable"  # tag-only: no runtime hint unless requested
    _rec2, _opt2, rej2 = _result_ids(
        evaluate(reg, profile, _ctx(wanted_tags=frozenset({"native"})))
    )
    assert rej2["t.native"] == "needs_runtime"
    assert rej["t.conflicts-always"] == "conflict"  # lower score loses


def test_tags_and_requests_pull_in_candidates(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("py"))
    rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx(wanted_tags=frozenset({"extra"}))))
    assert "t.tagged" in rec
    rec, _opt, rej = _result_ids(
        evaluate(reg, profile, _ctx(requested_ids=frozenset({"t.tagged"})))
    )
    assert "t.tagged" in rec
    rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx(excluded_ids=frozenset({"t.always"}))))
    assert rej["t.always"] == "user_excluded"
    # excluding t.always also removes t.needs-always (dependency missing)
    assert rej.get("t.needs-always") == "dependency_missing"


def test_language_condition_rejects_non_python(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    root = make_project("js", files={"package.json": '{"name":"x"}', "index.js": "1"})
    (root / "pyproject.toml").unlink()
    (root / "src" / "main.py").unlink()
    profile = scan_project(root)
    assert "python" not in profile.language_names
    _rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx()))
    assert rej["t.python-only"] == "not_applicable"


def test_equivalent_existing_skill_is_detected(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("cl", kind="claude"))
    _rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx()))
    assert rej["t.equiv"] == "equivalent_exists"
    # explicitly requested -> installed anyway, with the existing asset reported
    result = evaluate(reg, profile, _ctx(requested_ids=frozenset({"t.equiv"})))
    cand = next(c for c in result.recommended if c.capability.id == "t.equiv")
    assert cand.existing and "my-equiv" in cand.existing[0]


def test_destination_collision_with_user_file(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    root = make_project(
        "collide", kind="claude", files={".claude/skills/always/SKILL.md": "# user-owned\n"}
    )
    profile = scan_project(root)
    _rec, _opt, rej = _result_ids(evaluate(reg, profile, _ctx()))
    assert rej["t.always"] == "conflict"


def test_platform_support_is_enforced(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("cx", kind="codex"))
    result = evaluate(reg, profile, _ctx(Platform.CODEX))
    assert all(c.platform == Platform.CODEX for c in result.recommended)
    rec, _opt, _rej = _result_ids(result)
    assert "t.always" in rec and "t.notice" in rec


def test_choose_platforms_defaults_and_detects(make_project) -> None:
    plain = scan_project(make_project("p1"))
    platforms, notes = choose_platforms(plain, None)
    assert platforms == [Platform.CLAUDE_CODE] and notes
    both = scan_project(make_project("p2", kind="both"))
    platforms, _ = choose_platforms(both, None)
    assert set(platforms) == {Platform.CLAUDE_CODE, Platform.CODEX}
    platforms, _ = choose_platforms(both, (Platform.CODEX,))
    assert platforms == [Platform.CODEX]


def test_every_recommendation_is_explained(synthetic_registry: Path, make_project) -> None:
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("ex"))
    result = evaluate(reg, profile, _ctx(wanted_tags=frozenset({"extra"})))
    for cand in (*result.recommended, *result.optional):
        assert cand.reasons, cand.capability.id
        assert cand.score.explain()
    for rj in result.rejected:
        assert rj.reasons and rj.category


def test_pulled_in_dependency_still_honours_policy(synthetic_registry: Path, make_project) -> None:
    # t.tagged is tag-only, so it is "not_applicable" and would be pulled in as a dependency;
    # policy must still be evaluated for it.
    write_capability(
        synthetic_registry,
        base_manifest("t.needs-tagged", dependencies=["t.tagged"]),
        skill_assets("needs-tagged"),
    )
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("pd"))
    ps = PolicySet([("t", Policy(capabilities={"deny": ["t.tagged"]}))])
    rec, opt, rej = _result_ids(evaluate(reg, profile, _ctx(policy=ps)))
    assert "t.tagged" not in rec | opt
    assert rej["t.needs-tagged"] == "dependency_missing"


def test_optional_dependency_makes_dependant_optional(
    synthetic_registry: Path, make_project
) -> None:
    write_capability(
        synthetic_registry,
        base_manifest("t.shell", permissions=["runs_shell"]),
        skill_assets("shell"),
    )
    write_capability(
        synthetic_registry,
        base_manifest("t.tagged-shell", permissions=["runs_shell"], applicability={"tags": ["ts"]}),
        skill_assets("tagged-shell"),
    )
    write_capability(
        synthetic_registry,
        base_manifest("t.needs-shell", dependencies=["t.shell"]),
        skill_assets("needs-shell"),
    )
    write_capability(
        synthetic_registry,
        base_manifest("t.needs-tagged-shell", dependencies=["t.tagged-shell"]),
        skill_assets("needs-tagged-shell"),
    )
    reg = load_registry(synthetic_registry)
    profile = scan_project(make_project("od"))

    rec, opt, _rej = _result_ids(evaluate(reg, profile, _ctx()))
    # never recommend a capability whose dependency is left out of the plan
    assert {"t.shell", "t.needs-shell", "t.tagged-shell", "t.needs-tagged-shell"} <= opt
    assert not {"t.needs-shell", "t.needs-tagged-shell"} & rec

    requested = frozenset({"t.needs-shell", "t.needs-tagged-shell"})
    rec, _opt, _rej = _result_ids(evaluate(reg, profile, _ctx(requested_ids=requested)))
    # requesting the dependant pulls its dependency in, with the reason recorded
    assert {"t.shell", "t.needs-shell", "t.tagged-shell", "t.needs-tagged-shell"} <= rec
