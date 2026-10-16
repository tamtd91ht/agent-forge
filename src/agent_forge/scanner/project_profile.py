"""Evidence-based project profiling (languages, frameworks, project types, git, test commands)."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

from agent_forge import __version__
from agent_forge.config import DEFAULT_CONFIG
from agent_forge.errors import ScanError
from agent_forge.models.project import Detection, Evidence, GitState, ProjectProfile
from agent_forge.scanner.agent_detection import detect_agents
from agent_forge.scanner.filesystem import Walker
from agent_forge.util import now_iso

# ---- language indicators -------------------------------------------------------------------

_LANG_FILES: dict[str, list[tuple[str, float]]] = {
    "python": [("pyproject.toml", 0.9), ("setup.py", 0.8), ("requirements.txt", 0.7), ("Pipfile", 0.8), ("setup.cfg", 0.6)],
    "javascript": [("package.json", 0.6)],
    "typescript": [("tsconfig.json", 0.9)],
    "go": [("go.mod", 0.95)],
    "rust": [("Cargo.toml", 0.95)],
    "java": [("pom.xml", 0.9), ("build.gradle", 0.8)],
    "kotlin": [("build.gradle.kts", 0.7)],
    "ruby": [("Gemfile", 0.9)],
    "php": [("composer.json", 0.9)],
    "csharp": [("global.json", 0.5)],
    "dart": [("pubspec.yaml", 0.9)],
    "swift": [("Package.swift", 0.9)],
    "elixir": [("mix.exs", 0.95)],
    "terraform": [("main.tf", 0.8)],
}  # fmt: skip

_LANG_SUFFIXES: dict[str, tuple[str, ...]] = {
    "python": (".py",),
    "javascript": (".js", ".mjs", ".cjs", ".jsx"),
    "typescript": (".ts", ".tsx"),
    "go": (".go",),
    "rust": (".rs",),
    "java": (".java",),
    "kotlin": (".kt", ".kts"),
    "ruby": (".rb",),
    "php": (".php",),
    "csharp": (".cs",),
    "dart": (".dart",),
    "swift": (".swift",),
    "terraform": (".tf",),
    "shell": (".sh",),
}

_NODE_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "react": ("react",),
    "nextjs": ("next",),
    "vue": ("vue",),
    "nuxt": ("nuxt",),
    "svelte": ("svelte", "@sveltejs/kit"),
    "angular": ("@angular/core",),
    "express": ("express",),
    "fastify": ("fastify",),
    "nestjs": ("@nestjs/core",),
    "remix": ("@remix-run/react",),
    "astro": ("astro",),
    "react-native": ("react-native",),
    "electron": ("electron",),
    "tailwind": ("tailwindcss",),
}
_NODE_TEST_TOOLS = ("jest", "vitest", "mocha", "playwright", "@playwright/test", "cypress")

_PY_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "django": ("django",),
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "typer": ("typer",),
    "click": ("click",),
    "pytorch": ("torch",),
    "streamlit": ("streamlit",),
}

_AGENT_DEPS = (
    "@anthropic-ai/sdk",
    "anthropic",
    "openai",
    "@modelcontextprotocol/sdk",
    "mcp",
    "langchain",
    "@langchain/core",
)


def _add(detections: dict[str, Detection], name: str, conf: float, path: str, detail: str) -> None:
    d = detections.get(name)
    if d is None:
        detections[name] = Detection(
            name=name, confidence=conf, evidence=[Evidence(path=path, detail=detail)]
        )
    else:
        d.confidence = min(1.0, max(d.confidence, conf) + 0.05)
        if len(d.evidence) < 6:
            d.evidence.append(Evidence(path=path, detail=detail))


def _detect_languages(walker: Walker) -> dict[str, Detection]:
    det: dict[str, Detection] = {}
    for lang, files in _LANG_FILES.items():
        for fname, conf in files:
            for entry in walker.find_by_name(fname, max_depth=1):
                _add(det, lang, conf, entry.rel, "manifest file")
    counts: dict[str, int] = {}
    for lang, suffixes in _LANG_SUFFIXES.items():
        n = len(walker.find_by_suffix(suffixes, limit=400))
        if n:
            counts[lang] = n
    for lang, n in counts.items():
        conf = 0.3 if n < 3 else 0.5 if n < 20 else 0.7
        _add(det, lang, conf, "*", f"{n}+ source files")
    if (
        "typescript" in det
        and "javascript" in det
        and det["javascript"].confidence < det["typescript"].confidence
    ):
        det["javascript"].confidence = min(det["javascript"].confidence, 0.5)
    return det


def _read_package_json(walker: Walker, rel: str) -> dict | None:
    text = walker.read_text(rel)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _detect_node(
    walker: Walker,
    frameworks: dict[str, Detection],
    types: dict[str, Detection],
    tests: list[str],
    warnings: list[str],
) -> set[str]:
    agent_deps: set[str] = set()
    for entry in walker.find_by_name("package.json", max_depth=2):
        pkg = _read_package_json(walker, entry.rel)
        if pkg is None:
            continue
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            v = pkg.get(key)
            if isinstance(v, dict):
                deps.update(v)
        for fw, names in _NODE_FRAMEWORKS.items():
            if any(n in deps for n in names):
                _add(frameworks, fw, 0.9, entry.rel, "dependency")
        for tool in _NODE_TEST_TOOLS:
            if tool in deps:
                _add(frameworks, f"test:{tool}", 0.8, entry.rel, "test tool")
        for dep in _AGENT_DEPS:
            if dep in deps:
                agent_deps.add(dep)
        scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
        prefix = "" if entry.rel == "package.json" else f"(cd {entry.rel.rsplit('/', 1)[0]} && ) "
        for name in ("test", "lint", "typecheck", "build"):
            if name in scripts:
                tests.append(
                    f"{prefix}npm run {name}".replace("(cd ", "cd ").replace(" && ) ", " && ")
                )
        if pkg.get("bin"):
            _add(types, "cli", 0.7, entry.rel, "package.json bin")
        if pkg.get("workspaces"):
            _add(types, "monorepo", 0.9, entry.rel, "package.json workspaces")
        if (
            entry.rel == "package.json"
            and pkg.get("private") is not True
            and pkg.get("name")
            and not pkg.get("bin")
        ):
            _add(types, "library", 0.4, entry.rel, "publishable package")
    for f in ("pnpm-workspace.yaml", "lerna.json", "nx.json", "turbo.json"):
        if walker.exists(f):
            _add(types, "monorepo", 0.9, f, "workspace tool")
    return agent_deps


def _detect_python(
    walker: Walker, frameworks: dict[str, Detection], types: dict[str, Detection], tests: list[str]
) -> set[str]:
    agent_deps: set[str] = set()
    text = walker.read_text("pyproject.toml")
    if text:
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            data = {}
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        deps: list[str] = list(project.get("dependencies") or [])
        for group in (project.get("optional-dependencies") or {}).values():
            if isinstance(group, list):
                deps.extend(group)
        poetry = (
            ((data.get("tool") or {}).get("poetry") or {})
            if isinstance(data.get("tool"), dict)
            else {}
        )
        if isinstance(poetry.get("dependencies"), dict):
            deps.extend(poetry["dependencies"].keys())
        names = {
            re.split(r"[\s\[<>=!~;]", d, maxsplit=1)[0].lower() for d in deps if isinstance(d, str)
        }
        for fw, pkgs in _PY_FRAMEWORKS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.9, "pyproject.toml", "dependency")
        for dep in _AGENT_DEPS:
            if dep in names:
                agent_deps.add(dep)
        if "pytest" in names or isinstance((data.get("tool") or {}).get("pytest"), dict):
            _add(frameworks, "test:pytest", 0.8, "pyproject.toml", "test tool")
            tests.append("pytest")
        if project.get("scripts"):
            _add(types, "cli", 0.7, "pyproject.toml", "project.scripts")
        if "ruff" in names or isinstance((data.get("tool") or {}).get("ruff"), dict):
            tests.append("ruff check .")
    req = walker.read_text("requirements.txt")
    if req:
        names = {
            re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].lower()
            for line in req.splitlines()
            if line.strip() and not line.startswith("#")
        }
        for fw, pkgs in _PY_FRAMEWORKS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.8, "requirements.txt", "dependency")
        for dep in _AGENT_DEPS:
            if dep in names:
                agent_deps.add(dep)
        if "pytest" in names and "pytest" not in tests:
            tests.append("pytest")
    if walker.exists("manage.py"):
        _add(frameworks, "django", 0.9, "manage.py", "django entry point")
    return agent_deps


def _detect_project_types(
    walker: Walker,
    languages: dict[str, Detection],
    frameworks: dict[str, Detection],
    types: dict[str, Detection],
) -> None:
    fw = set(frameworks)
    if fw & {"react", "nextjs", "vue", "nuxt", "svelte", "angular", "astro", "remix"}:
        _add(types, "frontend", 0.9, "*", "frontend framework")
    if fw & {"express", "fastify", "nestjs", "django", "fastapi", "flask"}:
        _add(types, "backend", 0.9, "*", "backend framework")
    if "nextjs" in fw or "nuxt" in fw or "remix" in fw:
        _add(types, "fullstack", 0.7, "*", "fullstack framework")
    if fw & {"react-native", "electron"} or "dart" in languages or "swift" in languages:
        _add(types, "mobile-or-desktop", 0.7, "*", "mobile/desktop stack")
    for f in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
        if walker.exists(f):
            _add(types, "service", 0.6, f, "container definition")
    if (
        "terraform" in languages
        or walker.under("helm")
        or walker.under("k8s")
        or walker.under(".github/workflows")
    ):
        _add(
            types,
            "infrastructure",
            0.6 if "terraform" in languages else 0.4,
            "*",
            "infra indicators",
        )
    if "go" in languages and walker.find_by_name("main.go", max_depth=2):
        _add(types, "cli", 0.5, "main.go", "go main package")
    if "rust" in languages and walker.exists("src/main.rs"):
        _add(types, "cli", 0.6, "src/main.rs", "rust binary crate")
    if "rust" in languages and walker.exists("src/lib.rs"):
        _add(types, "library", 0.6, "src/lib.rs", "rust library crate")
    if not types:
        if languages:
            _add(types, "generic", 0.5, "*", "no specific project type indicators")
        else:
            _add(types, "unknown", 0.3, "*", "no language indicators")


def _git_state(root: Path) -> GitState:
    gs = GitState()
    if not (root / ".git").exists():
        # may still be inside a repo (subdirectory target)
        pass
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return gs
    if proc.returncode != 0:
        return gs
    gs.is_repo = True
    gs.root = proc.stdout.strip()

    def q(*args: str) -> str | None:
        p = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False, timeout=30
        )
        return p.stdout.strip() if p.returncode == 0 else None

    gs.head = q("rev-parse", "HEAD")
    gs.branch = q("rev-parse", "--abbrev-ref", "HEAD")
    status = q("status", "--porcelain")
    if status is not None:
        lines = [line for line in status.splitlines() if line.strip()]
        gs.dirty = bool(lines)
        gs.dirty_count = len(lines)
    gs.remote = q("remote", "get-url", "origin")
    return gs


def scan_project(target: Path, *, limits: dict[str, int] | None = None) -> ProjectProfile:
    """Scan `target` read-only and return a ProjectProfile."""
    limits = {**DEFAULT_CONFIG["scan"], **(limits or {})}
    if not target.exists():
        raise ScanError(f"target does not exist: {target}")
    if not target.is_dir():
        raise ScanError(f"target is not a directory: {target}")
    canonical = target.resolve()
    walker = Walker(
        root=canonical,
        max_files=limits["max_files"],
        max_depth=limits["max_depth"],
        max_file_bytes=limits["max_file_bytes"],
    )
    walker.ensure_walked()
    warnings: list[str] = []
    languages = _detect_languages(walker)
    frameworks: dict[str, Detection] = {}
    types: dict[str, Detection] = {}
    tests: list[str] = []
    agent_deps: set[str] = set()
    agent_deps |= _detect_node(walker, frameworks, types, tests, warnings)
    agent_deps |= _detect_python(walker, frameworks, types, tests)
    if walker.exists("go.mod"):
        tests.append("go test ./...")
    if walker.exists("Cargo.toml"):
        tests.append("cargo test")
    if walker.exists("Makefile"):
        mk = walker.read_text("Makefile") or ""
        if re.search(r"^test:", mk, re.MULTILINE):
            tests.append("make test")
    _detect_project_types(walker, languages, frameworks, types)
    if agent_deps:
        _add(
            frameworks,
            "ai-sdk",
            0.8,
            "*",
            "agent-related dependencies: " + ", ".join(sorted(agent_deps)),
        )
    inv = detect_agents(walker)
    warnings.extend(inv.warnings)
    if walker.stats.truncated:
        warnings.append(
            "scan truncated by limits (max_files/max_depth); detection may be incomplete"
        )
    if walker.stats.skipped_symlinks:
        warnings.append(f"{walker.stats.skipped_symlinks} symlink(s) skipped (never followed)")
    git = _git_state(canonical)
    if git.is_repo and git.dirty:
        warnings.append(f"git working tree has {git.dirty_count} uncommitted change(s)")
    # de-duplicate test commands while keeping order
    seen: set[str] = set()
    tests = [t for t in tests if not (t in seen or seen.add(t))]
    return ProjectProfile(
        scanned_at=now_iso(),
        forge_version=__version__,
        target_path=str(target),
        canonical_path=str(canonical),
        git=git,
        languages=sorted(languages.values(), key=lambda d: -d.confidence),
        frameworks=sorted(frameworks.values(), key=lambda d: -d.confidence),
        project_types=sorted(types.values(), key=lambda d: -d.confidence),
        platforms=inv.platforms,
        assets=inv.assets,
        managed=inv.managed,
        managed_manifest_valid=inv.managed_manifest_valid,
        test_commands=tests,
        sensitive_files=sorted(walker.sensitive),
        warnings=warnings,
        stats=walker.stats,
    )
