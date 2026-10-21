"""Evidence-based project profiling (languages, frameworks, project types, git, test commands)."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

# Manifests are searched this deep, so services/api/pyproject.toml or apps/web/package.json in
# a monorepo count as evidence, not only the root.
_MANIFEST_DEPTH = 3

_JVM_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "spring": ("spring-boot", "org.springframework"),
    "quarkus": ("io.quarkus",),
    "micronaut": ("io.micronaut",),
    "test:junit": ("junit",),
}
_GO_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "gin": ("github.com/gin-gonic/gin",),
    "echo": ("github.com/labstack/echo",),
    "fiber": ("github.com/gofiber/fiber",),
    "chi": ("github.com/go-chi/chi",),
    "grpc": ("google.golang.org/grpc",),
    "cobra": ("github.com/spf13/cobra",),
}
_RUST_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "axum": ("axum",),
    "actix-web": ("actix-web",),
    "rocket": ("rocket",),
    "clap": ("clap",),
}
# Integrations (data stores, brokers, build tools) recorded as frameworks so that stack-specific
# capabilities (redis-patterns, postgres-patterns, prisma-patterns, …) apply only when the
# dependency is really there. One table per ecosystem; the key is the framework name.
_NODE_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("ioredis", "redis", "@upstash/redis"),
    "kafka": ("kafkajs", "node-rdkafka", "@confluentinc/kafka-javascript"),
    "postgres": ("pg", "postgres", "pg-promise"),
    "mysql": ("mysql", "mysql2"),
    "mongodb": ("mongodb", "mongoose"),
    "prisma": ("prisma", "@prisma/client"),
    "vite": ("vite",),
}
_PY_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("redis", "aioredis"),
    "kafka": ("kafka-python", "confluent-kafka", "aiokafka", "faust-streaming"),
    "postgres": ("psycopg", "psycopg2", "psycopg2-binary", "asyncpg"),
    "mysql": ("mysqlclient", "pymysql", "mysql-connector-python", "aiomysql"),
    "mongodb": ("pymongo", "motor"),
    "celery": ("celery",),
}
_JVM_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("spring-boot-starter-data-redis", "redis.clients", "io.lettuce"),
    "kafka": ("spring-kafka", "org.apache.kafka", "kafka-clients"),
    "postgres": ("org.postgresql",),
    "mysql": ("mysql-connector", "com.mysql", "mariadb-java-client"),
    "mongodb": ("spring-boot-starter-data-mongodb", "mongodb-driver"),
    "ktor": ("io.ktor",),
    "exposed": ("org.jetbrains.exposed",),
}
_GO_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("github.com/redis/go-redis", "github.com/go-redis/redis"),
    "kafka": (
        "github.com/segmentio/kafka-go",
        "github.com/IBM/sarama",
        "github.com/Shopify/sarama",
        "github.com/confluentinc/confluent-kafka-go",
    ),
    "postgres": ("github.com/jackc/pgx", "github.com/lib/pq"),
    "mysql": ("github.com/go-sql-driver/mysql",),
    "mongodb": ("go.mongodb.org/mongo-driver",),
}
_RUST_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("redis",),
    "kafka": ("rdkafka",),
    "postgres": ("tokio-postgres", "postgres"),
    "mysql": ("mysql_async",),
}
_DOCKER_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yaml",
    "compose.yml",
)

_BACKEND_FRAMEWORKS = {
    "express", "fastify", "nestjs", "django", "fastapi", "flask", "spring", "quarkus",
    "micronaut", "gin", "echo", "fiber", "chi", "grpc", "aspnetcore", "axum", "actix-web",
    "rocket", "rails", "laravel", "symfony",
}  # fmt: skip

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
            for entry in walker.find_by_name(fname, max_depth=_MANIFEST_DEPTH):
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
    for entry in walker.find_by_name("package.json", max_depth=_MANIFEST_DEPTH):
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
        for fw, names in _NODE_INTEGRATIONS.items():
            if any(n in deps for n in names):
                _add(frameworks, fw, 0.85, entry.rel, "dependency")
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


def _cd(rel: str) -> str:
    """`cd <dir> && ` for a manifest below the root, '' at the root."""
    return f"cd {rel.rsplit('/', 1)[0]} && " if "/" in rel else ""


def _detect_python(
    walker: Walker, frameworks: dict[str, Detection], types: dict[str, Detection], tests: list[str]
) -> set[str]:
    agent_deps: set[str] = set()
    for entry in walker.find_by_name("pyproject.toml", max_depth=_MANIFEST_DEPTH):
        text = walker.read_text(entry.rel)
        if not text:
            continue
        try:
            data = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            continue
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        deps: list[str] = list(project.get("dependencies") or [])
        for group in (project.get("optional-dependencies") or {}).values():
            if isinstance(group, list):
                deps.extend(group)
        tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
        poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
        if isinstance(poetry.get("dependencies"), dict):
            deps.extend(poetry["dependencies"].keys())
        names = {
            re.split(r"[\s\[<>=!~;]", d, maxsplit=1)[0].lower() for d in deps if isinstance(d, str)
        }
        for fw, pkgs in _PY_FRAMEWORKS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.9, entry.rel, "dependency")
        for fw, pkgs in _PY_INTEGRATIONS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.85, entry.rel, "dependency")
        agent_deps |= {dep for dep in _AGENT_DEPS if dep in names}
        if "pytest" in names or isinstance(tool.get("pytest"), dict):
            _add(frameworks, "test:pytest", 0.8, entry.rel, "test tool")
            tests.append(f"{_cd(entry.rel)}pytest")
        if project.get("scripts"):
            _add(types, "cli", 0.7, entry.rel, "project.scripts")
        if "ruff" in names or isinstance(tool.get("ruff"), dict):
            tests.append(f"{_cd(entry.rel)}ruff check .")
    for entry in walker.find_by_name("requirements.txt", max_depth=_MANIFEST_DEPTH):
        req = walker.read_text(entry.rel) or ""
        names = {
            re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].lower()
            for line in req.splitlines()
            if line.strip() and not line.startswith("#")
        }
        for fw, pkgs in _PY_FRAMEWORKS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.8, entry.rel, "dependency")
        for fw, pkgs in _PY_INTEGRATIONS.items():
            if any(p in names for p in pkgs):
                _add(frameworks, fw, 0.8, entry.rel, "dependency")
        agent_deps |= {dep for dep in _AGENT_DEPS if dep in names}
        if "pytest" in names:
            tests.append(f"{_cd(entry.rel)}pytest")
    for entry in walker.find_by_name("manage.py", max_depth=_MANIFEST_DEPTH):
        _add(frameworks, "django", 0.9, entry.rel, "django entry point")
    return agent_deps


def _scan_markers(
    walker: Walker,
    rel: str,
    table: dict[str, tuple[str, ...]],
    frameworks: dict[str, Detection],
    detail: str,
) -> str:
    text = walker.read_text(rel) or ""
    for fw, markers in table.items():
        if any(m in text for m in markers):
            _add(frameworks, fw, 0.85, rel, detail)
    return text


def _detect_jvm_go_rust_dotnet(
    walker: Walker,
    languages: dict[str, Detection],
    frameworks: dict[str, Detection],
    tests: list[str],
) -> None:
    for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        for entry in walker.find_by_name(name, max_depth=_MANIFEST_DEPTH):
            _scan_markers(walker, entry.rel, _JVM_FRAMEWORKS, frameworks, "build dependency")
            _scan_markers(walker, entry.rel, _JVM_INTEGRATIONS, frameworks, "build dependency")
            here = entry.rel.rsplit("/", 1)[0] + "/" if "/" in entry.rel else ""
            if name == "pom.xml":
                runner = "./mvnw" if walker.exists(f"{here}mvnw") else "mvn"
            else:
                runner = "./gradlew" if walker.exists(f"{here}gradlew") else "gradle"
            tests.append(f"{_cd(entry.rel)}{runner} test")
    for entry in walker.find_by_name("go.mod", max_depth=_MANIFEST_DEPTH):
        _scan_markers(walker, entry.rel, _GO_FRAMEWORKS, frameworks, "go.mod require")
        _scan_markers(walker, entry.rel, _GO_INTEGRATIONS, frameworks, "go.mod require")
        tests.append(f"{_cd(entry.rel)}go test ./...")
    for entry in walker.find_by_name("Cargo.toml", max_depth=_MANIFEST_DEPTH):
        _scan_markers(walker, entry.rel, _RUST_FRAMEWORKS, frameworks, "Cargo dependency")
        _scan_markers(walker, entry.rel, _RUST_INTEGRATIONS, frameworks, "Cargo dependency")
        tests.append(f"{_cd(entry.rel)}cargo test")
    projects = [
        e
        for e in walker.find_by_suffix((".csproj", ".fsproj"))
        if e.rel.count("/") <= _MANIFEST_DEPTH
    ]
    for entry in projects:
        _add(languages, "csharp", 0.9, entry.rel, "project file")
        if 'Sdk="Microsoft.NET.Sdk.Web"' in (walker.read_text(entry.rel) or ""):
            _add(frameworks, "aspnetcore", 0.9, entry.rel, "web SDK")
    if projects:
        tests.append("dotnet test")
    gemfile = walker.read_text("Gemfile") or ""
    if re.search(r"""gem ['"]rails['"]""", gemfile):
        _add(frameworks, "rails", 0.9, "Gemfile", "dependency")
    for f in _DOCKER_FILES:
        if walker.exists(f):
            _add(frameworks, "docker", 0.9, f, "file present")
    composer = walker.read_text("composer.json") or ""
    if '"laravel/framework"' in composer:
        _add(frameworks, "laravel", 0.9, "composer.json", "dependency")
    if '"symfony/framework-bundle"' in composer:
        _add(frameworks, "symfony", 0.9, "composer.json", "dependency")


def _detect_project_types(
    walker: Walker,
    languages: dict[str, Detection],
    frameworks: dict[str, Detection],
    types: dict[str, Detection],
) -> None:
    fw = set(frameworks)
    if fw & {"react", "nextjs", "vue", "nuxt", "svelte", "angular", "astro", "remix"}:
        _add(types, "frontend", 0.9, "*", "frontend framework")
    if fw & _BACKEND_FRAMEWORKS:
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
    if "cobra" in fw or "clap" in fw:
        _add(types, "cli", 0.7, "*", "CLI framework")
    if (
        "go" in languages
        and walker.find_by_name("main.go", max_depth=2)
        and not fw & _BACKEND_FRAMEWORKS
    ):
        _add(types, "cli", 0.5, "main.go", "go main package")
    manifest_dirs = {
        e.rel.rsplit("/", 1)[0]
        for name in (
            "package.json",
            "pyproject.toml",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "Cargo.toml",
        )
        for e in walker.find_by_name(name, max_depth=_MANIFEST_DEPTH)
        if "/" in e.rel
    }
    if len(manifest_dirs) >= 2:
        _add(
            types,
            "monorepo",
            0.7,
            ", ".join(sorted(manifest_dirs)[:4]),
            f"{len(manifest_dirs)} project manifests in subdirectories",
        )
    if "rust" in languages and walker.exists("src/main.rs"):
        _add(types, "cli", 0.6, "src/main.rs", "rust binary crate")
    if "rust" in languages and walker.exists("src/lib.rs"):
        _add(types, "library", 0.6, "src/lib.rs", "rust library crate")
    if not types:
        if languages:
            _add(types, "generic", 0.5, "*", "no specific project type indicators")
        else:
            _add(types, "unknown", 0.3, "*", "no language indicators")


PROFILE_OVERRIDE = ".agent-forge/profile.yaml"


class ProfileOverride(BaseModel):
    """`.agent-forge/profile.yaml`: what the team confirms or rules out about its project."""

    model_config = ConfigDict(extra="forbid")
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    ignore: list[str] = Field(
        default_factory=list, description="detections to drop (language/framework/type names)"
    )


def _apply_overrides(
    walker: Walker,
    languages: dict[str, Detection],
    frameworks: dict[str, Detection],
    warnings: list[str],
    types: dict[str, Detection],
    *,
    project_types_only: bool = False,
) -> None:
    text = walker.read_text(PROFILE_OVERRIDE)
    if text is None:
        return
    try:
        raw = yaml.safe_load(text) or {}
        ov = ProfileOverride.model_validate(raw)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        if not project_types_only:
            warnings.append(f"{PROFILE_OVERRIDE} ignored: invalid ({str(exc).splitlines()[0]})")
        return
    targets = [(types, ov.project_types)] if project_types_only else [
        (languages, ov.languages), (frameworks, ov.frameworks)
    ]  # fmt: skip
    for dets, names in targets:
        for name in names:
            dets.pop(name, None)
            _add(dets, name, 1.0, PROFILE_OVERRIDE, "confirmed by the project")
    for dets in (types,) if project_types_only else (languages, frameworks):
        for name in ov.ignore:
            dets.pop(name, None)


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
    _detect_jvm_go_rust_dotnet(walker, languages, frameworks, tests)
    if walker.exists("Makefile"):
        mk = walker.read_text("Makefile") or ""
        for target in ("test", "lint", "format", "build"):
            if re.search(rf"^{target}:", mk, re.MULTILINE):
                tests.append(f"make {target}")
    _apply_overrides(walker, languages, frameworks, warnings, types)
    _detect_project_types(walker, languages, frameworks, types)
    _apply_overrides(walker, languages, frameworks, warnings, types, project_types_only=True)
    if agent_deps:
        _add(
            frameworks,
            "ai-sdk",
            0.8,
            "*",
            "agent-related dependencies: " + ", ".join(sorted(agent_deps)),
        )
    for kind, dets in (("language", languages), ("framework", frameworks), ("project type", types)):
        for d in dets.values():
            if 0.3 <= d.confidence < 0.5:
                warnings.append(
                    f"low-confidence {kind} '{d.name}' ({d.confidence:.2f}, {d.evidence[0].detail}) "
                    "is not used for recommendations; confirm it in .agent-forge/profile.yaml"
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
