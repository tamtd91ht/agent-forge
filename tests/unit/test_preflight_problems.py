"""Pre-flight problems are data: the code, not the message, decides the error and exit code."""

from __future__ import annotations

from agent_forge.apply.engine import (
    APPROVAL_CODES,
    STALE_CODES,
    PreflightReport,
    Problem,
    ProblemCode,
    error_for,
)
from agent_forge.errors import ApplyError, ApprovalError, StalePlanError


def test_every_code_maps_to_exactly_one_error_class() -> None:
    assert not (STALE_CODES & APPROVAL_CODES)
    for code in ProblemCode:
        exc = error_for([Problem(code, "x")])
        if code in STALE_CODES:
            assert exc is StalePlanError and exc.exit_code == 7
        elif code in APPROVAL_CODES:
            assert exc is ApprovalError and exc.exit_code == 8
        else:
            assert exc is ApplyError and exc.exit_code == 10


def test_stale_wins_over_approval_wins_over_apply() -> None:
    both = [
        Problem(ProblemCode.NOT_APPROVED, "a"),
        Problem(ProblemCode.FILE_CHANGED, "b", "op-1", "x.md"),
    ]
    assert error_for(both) is StalePlanError
    assert (
        error_for([Problem(ProblemCode.NOT_APPROVED, "a"), Problem(ProblemCode.UNSAFE_PATH, "u")])
        is ApprovalError
    )
    assert error_for([]) is ApplyError


def test_problem_renders_with_its_operation_and_report_lists_codes() -> None:
    p = Problem(
        ProblemCode.FILE_CHANGED, "file changed since planning (stale)", "op-3", "CLAUDE.md"
    )
    assert str(p) == "op-3 CLAUDE.md: file changed since planning (stale)"
    assert str(Problem(ProblemCode.EXPIRED, "plan expired")) == "plan expired"
    assert p.to_dict() == {
        "code": "file_changed",
        "op_id": "op-3",
        "path": "CLAUDE.md",
        "message": "file changed since planning (stale)",
    }
    rep = PreflightReport(ok=False, problems=[p, Problem(ProblemCode.EXPIRED, "e")])
    assert rep.codes() == ["expired", "file_changed"]
    assert rep.messages[1] == "e"
