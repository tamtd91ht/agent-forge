"""`agent-forge lint`: score a project's existing agent configuration without installing anything."""

from agent_forge.lint.engine import LintReport, lint_project

__all__ = ["LintReport", "lint_project"]
