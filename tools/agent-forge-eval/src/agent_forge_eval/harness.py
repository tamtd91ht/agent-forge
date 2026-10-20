"""Evaluation harness: tasks, arms, runners, execution.

Design (docs/evaluation.md §2): for each task and arm (baseline = fixture as is, candidate =
fixture after `agent-forge forge --request <capability>`), a fresh copy of the fixture is
prepared, the coding tool is run headless with the task prompt, then the task's acceptance
files are added and its acceptance command decides pass/fail. Every run records wall time
and, when the tool reports them, tokens and cost. Nothing here touches the registry or a
real project: every run happens in a temporary directory that is deleted afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---- tasks -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    id: str
    category: str  # bugfix | feature | refactor | review | docs
    prompt: str
    acceptance_command: str
    budget_seconds: int = 600
    setup_files: dict[str, str] = field(default_factory=dict)  # written before the run
    acceptance_files: dict[str, str] = field(default_factory=dict)  # written before judging
    regression_command: str | None = None  # the project's own suite, run after acceptance
    notes: str = ""


def load_tasks(fixture: Path) -> list[Task]:
    """Load `<fixture>/tasks/*.yaml` (one task per file), sorted by id."""
    tasks_dir = fixture / "tasks"
    out: list[Task] = []
    for p in sorted(tasks_dir.glob("*.yaml")):
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{p}: task must be a mapping")
        try:
            task = Task(
                id=str(raw["id"]),
                category=str(raw["category"]),
                prompt=str(raw["prompt"]).strip(),
                acceptance_command=str(raw["acceptance"]["command"]),
                budget_seconds=int(raw.get("budget_seconds", 600)),
                setup_files={
                    k: str(v) for k, v in (raw.get("setup", {}) or {}).get("files", {}).items()
                },
                acceptance_files={k: str(v) for k, v in raw["acceptance"].get("files", {}).items()},
                regression_command=raw.get("regression_command"),
                notes=str(raw.get("notes", "")),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{p}: missing or invalid field {exc}") from exc
        if task.category not in ("bugfix", "feature", "refactor", "review", "docs"):
            raise ValueError(f"{p}: unknown category {task.category!r}")
        if task.id != p.stem:
            raise ValueError(f"{p}: id {task.id!r} must equal the file name")
        for rel in (*task.setup_files, *task.acceptance_files):
            if rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
                raise ValueError(f"{p}: unsafe path {rel!r}")
        out.append(task)
    if not out:
        raise ValueError(f"no tasks under {tasks_dir}")
    return out


# ---- runners ---------------------------------------------------------------------------------


@dataclass
class ToolResult:
    exit_code: int
    wall_seconds: float
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    timed_out: bool = False
    raw_tail: str = ""


Runner = Callable[[Path, str, int], ToolResult]


def _run_tool(argv: list[str], cwd: Path, budget: int, *, stdin: str | None = None) -> ToolResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=budget,
            check=False,
            env={**os.environ, "CI": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        tail = out.decode(errors="replace") if isinstance(out, bytes) else out
        return ToolResult(-1, time.monotonic() - start, timed_out=True, raw_tail=tail[-2000:])
    wall = time.monotonic() - start
    res = ToolResult(proc.returncode, wall, raw_tail=(proc.stdout or "")[-2000:])
    _parse_usage(proc.stdout or "", res)
    return res


def _parse_usage(stdout: str, res: ToolResult) -> None:
    """Best effort: Claude Code `--output-format json` reports usage and total_cost_usd;
    codex `--json` emits JSON lines with a usage object. Unknown formats leave None."""
    candidates: list[dict[str, Any]] = []
    try:
        doc = json.loads(stdout)
        if isinstance(doc, dict):
            candidates.append(doc)
    except ValueError:
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    candidates.append(d)
    for d in candidates:
        usage = d.get("usage") if isinstance(d.get("usage"), dict) else None
        if usage:
            res.tokens_in = usage.get("input_tokens", res.tokens_in)
            res.tokens_out = usage.get("output_tokens", res.tokens_out)
        if isinstance(d.get("total_cost_usd"), int | float):
            res.cost_usd = float(d["total_cost_usd"])


def claude_runner(extra_args: list[str]) -> Runner:
    def run(project: Path, prompt: str, budget: int) -> ToolResult:
        argv = ["claude", "-p", prompt, "--output-format", "json", *extra_args]
        return _run_tool(argv, project, budget)

    return run


def codex_runner(extra_args: list[str]) -> Runner:
    def run(project: Path, prompt: str, budget: int) -> ToolResult:
        argv = ["codex", "exec", "--json", *extra_args, prompt]
        return _run_tool(argv, project, budget)

    return run


def scripted_runner(script: Callable[[Path, str], int]) -> Runner:
    """For tests and dry runs: `script(project, prompt)` edits the project and returns an
    exit code. No tool is launched."""

    def run(project: Path, prompt: str, budget: int) -> ToolResult:
        start = time.monotonic()
        code = script(project, prompt)
        return ToolResult(code, time.monotonic() - start)

    return run


# ---- arms ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Arm:
    name: str  # baseline | candidate
    capability: str | None  # installed into the copy before the run (candidate only)


def prepare_project(
    fixture: Path, dest: Path, arm: Arm, *, agent_forge: list[str], workspace: Path | None
) -> None:
    """Copy `<fixture>/project` to `dest`; for the candidate arm install the capability with
    the real engine (`forge --request`), so the agent sees exactly what a user would."""
    shutil.copytree(fixture / "project", dest, dirs_exist_ok=True)
    _git(dest, "init", "-q")
    _git(dest, "add", "-A")
    _git(
        dest, "-c", "user.email=eval@local", "-c", "user.name=eval", "commit", "-q", "-m", "fixture"
    )
    if arm.capability:
        argv = [
            *agent_forge,
            "forge",
            str(dest),
            "--request",
            arm.capability,
            "--yes",
            "--shared-files",
            "--hooks",
            "--json",
        ]
        if workspace is not None:
            argv += ["--workspace", str(workspace)]
        proc = subprocess.run(argv, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"agent-forge forge failed for {arm.capability}: {proc.stderr[-800:]}"
            )
        report = json.loads(proc.stdout)
        if isinstance(report, dict) and report.get("envelope") == 1:
            report = report["data"]  # JSON envelope v1
        selected = {cid for step in report.get("steps", []) for cid in step.get("selected", [])}
        managed = set(report.get("profile", {}).get("managed", []))
        if arm.capability not in selected | managed:
            raise RuntimeError(
                f"{arm.capability} was not installed into the candidate copy "
                f"(rejected: {[s.get('rejected') for s in report.get('steps', [])]})"
            )
        _git(dest, "add", "-A")
        _git(
            dest,
            "-c",
            "user.email=eval@local",
            "-c",
            "user.name=eval",
            "commit",
            "-q",
            "-m",
            "candidate",
        )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# ---- execution -------------------------------------------------------------------------------


@dataclass
class RunRecord:
    task_id: str
    category: str
    arm: str
    run: int
    passed: bool
    acceptance_exit: int
    regression_passed: bool | None
    tool: ToolResult
    changed_files: int


def _write_files(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")


def _shell(command: str, cwd: Path, timeout: int) -> int:
    try:
        return subprocess.run(  # noqa: S602 - task acceptance commands are reviewed fixtures
            command, cwd=cwd, shell=True, capture_output=True, timeout=timeout, check=False
        ).returncode
    except subprocess.TimeoutExpired:
        return -1


def _changed_files(root: Path) -> int:
    proc = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
    )
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def run_matrix(
    fixture: Path,
    tasks: list[Task],
    arms: list[Arm],
    runner: Runner,
    *,
    runs: int,
    agent_forge: list[str],
    workspace: Path | None,
    keep: bool = False,
    on_record: Callable[[RunRecord], None] | None = None,
) -> list[RunRecord]:
    records: list[RunRecord] = []
    for task in tasks:
        for arm in arms:
            for i in range(1, runs + 1):
                tmp = Path(tempfile.mkdtemp(prefix=f"afe-{task.id}-{arm.name}-{i}-"))
                try:
                    project = tmp / "project"
                    prepare_project(
                        fixture, project, arm, agent_forge=agent_forge, workspace=workspace
                    )
                    _write_files(project, task.setup_files)
                    tool = runner(project, task.prompt, task.budget_seconds)
                    changed = _changed_files(project)
                    _write_files(project, task.acceptance_files)
                    acc = _shell(task.acceptance_command, project, task.budget_seconds)
                    reg = None
                    if task.regression_command:
                        reg = _shell(task.regression_command, project, task.budget_seconds) == 0
                    rec = RunRecord(
                        task.id, task.category, arm.name, i, acc == 0, acc, reg, tool, changed
                    )
                    records.append(rec)
                    if on_record:
                        on_record(rec)
                finally:
                    if not keep:
                        shutil.rmtree(tmp, ignore_errors=True)
    return records


def records_to_json(records: list[RunRecord]) -> list[dict[str, Any]]:
    return [asdict(r) for r in records]
