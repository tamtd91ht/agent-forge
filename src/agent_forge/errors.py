"""Structured error hierarchy. Every CLI failure maps to one of these and a stable exit code."""

from __future__ import annotations


class AgentForgeError(Exception):
    """Base class. `exit_code` is what the CLI returns; `hint` is a short remediation tip."""

    exit_code: int = 1
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint


class UsageError(AgentForgeError):
    """Bad arguments or invalid invocation."""

    exit_code = 2


class WorkspaceError(AgentForgeError):
    """Workspace missing, not initialized, or corrupted."""

    exit_code = 3


class RegistryError(AgentForgeError):
    """Capability manifest invalid, missing, or inconsistent."""

    exit_code = 4


class ScanError(AgentForgeError):
    """Target path cannot be scanned."""

    exit_code = 5


class PlanError(AgentForgeError):
    """Plan missing, invalid, or in the wrong state."""

    exit_code = 6


class StalePlanError(PlanError):
    """The target, registry, or plan file changed after the plan was created/approved."""

    exit_code = 7


class ApprovalError(PlanError):
    """Operation attempted without a valid, digest-bound approval."""

    exit_code = 8


class SafetyViolation(AgentForgeError):
    """Filesystem boundary violation: traversal, symlink escape, out-of-scope write."""

    exit_code = 9


class ApplyError(AgentForgeError):
    """Apply failed; the transaction record describes what was done."""

    exit_code = 10


class RollbackConflict(AgentForgeError):
    """Rollback refused because files changed independently after apply."""

    exit_code = 11


class ValidationFailed(AgentForgeError):
    """`validate` found problems (used by the CLI to map to an exit code)."""

    exit_code = 12


class SourceError(AgentForgeError):
    """Source manifest / git checkout problems."""

    exit_code = 13


class ApprovalFileMismatch(ApprovalError):
    """The plan goes beyond what a committed approval file covers (CI gate)."""

    exit_code = 14
