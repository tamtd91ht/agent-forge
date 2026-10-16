from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_forge.models.capability import Capability
from agent_forge.models.plan import (
    Approval,
    FileOperation,
    OperationKind,
    Plan,
    PlanStatus,
    TargetIdentity,
)
from agent_forge.models.transaction import Transaction
from tests.conftest import base_manifest


def test_capability_manifest_roundtrip() -> None:
    cap = Capability.model_validate(base_manifest("t.ok"))
    assert cap.installable
    assert cap.destinations_for(cap.platforms[0])


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"id": "Bad_ID"}, "invalid capability id"),
        ({"version": "1.0"}, "MAJOR.MINOR.PATCH"),
        ({"dependencies": ["t.ok"]}, "itself"),
        ({"install_strategy": "reference_only"}, "cannot declare destinations"),
        (
            {"license": {"spdx": "MIT", "attribution": "x", "redistribution_ok": False}},
            "redistribution_ok",
        ),
        ({"unknown_field": 1}, "extra"),
    ],
)
def test_capability_manifest_rejects_bad_input(override: dict, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc:
        Capability.model_validate(base_manifest("t.ok", **override))
    assert fragment.lower() in str(exc.value).lower()


def test_destination_rejects_traversal_and_absolute() -> None:
    for bad in ("../x", "/abs", "C:/abs", "a/../../b"):
        with pytest.raises(ValidationError):
            Capability.model_validate(
                base_manifest(
                    "t.ok",
                    destinations=[{"platform": "claude_code", "source": "s", "dest": bad}],
                )
            )


def test_section_merge_requires_section_id() -> None:
    with pytest.raises(ValidationError):
        Capability.model_validate(
            base_manifest(
                "t.ok",
                install_strategy="section_merge",
                destinations=[
                    {
                        "platform": "claude_code",
                        "source": "n.md",
                        "dest": "CLAUDE.md",
                        "merge": "append_section",
                    }
                ],
            )
        )


def _plan() -> Plan:
    return Plan(
        plan_id="plan-x",
        kind="assign",
        created_at="2026-01-01T00:00:00+00:00",
        forge_version="0",
        target=TargetIdentity(canonical_path="/t", profile_fingerprint="f"),
        target_path="/t",
        registry_digest="r",
        operations=[
            FileOperation(
                op_id="op001",
                kind=OperationKind.CREATE,
                path="a.md",
                content="x",
                content_sha256="h",
            )
        ],
    )


def test_plan_digest_binds_approval() -> None:
    plan = _plan()
    plan.approval = Approval(status="approved", plan_digest=plan.content_digest())
    plan.status = PlanStatus.APPROVED
    assert plan.is_approved
    plan.operations[0].path = "b.md"  # tamper
    assert not plan.is_approved


def test_transaction_integrity_seal() -> None:
    tx = Transaction(
        transaction_id="tx-1",
        plan_id="plan-1",
        plan_digest="d",
        forge_version="0",
        target_canonical_path="/t",
        started_at="now",
    )
    tx.seal()
    assert tx.integrity_ok()
    tx.notes.append("edited")
    assert not tx.integrity_ok()
