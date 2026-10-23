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
from agent_forge.scanner.filesystem import WalkEntry, Walker
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
    "vertx": ("io.vertx",),
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
    "rabbitmq": ("amqplib", "amqp-connection-manager", "rascal"),
    "postgres": ("pg", "postgres", "pg-promise"),
    "mysql": ("mysql", "mysql2"),
    "mongodb": ("mongodb", "mongoose"),
    "elasticsearch": ("@elastic/elasticsearch", "@opensearch-project/opensearch"),
    "prisma": ("prisma", "@prisma/client"),
    "vite": ("vite",),
}
_PY_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("redis", "aioredis"),
    "kafka": ("kafka-python", "confluent-kafka", "aiokafka", "faust-streaming"),
    "rabbitmq": ("pika", "aio-pika", "kombu"),
    "postgres": ("psycopg", "psycopg2", "psycopg2-binary", "asyncpg"),
    "mysql": ("mysqlclient", "pymysql", "mysql-connector-python", "aiomysql"),
    "mongodb": ("pymongo", "motor"),
    "elasticsearch": ("elasticsearch", "elasticsearch-dsl", "opensearch-py"),
    "celery": ("celery",),
}
# JVM markers are substrings of the build file. `jpa` deliberately omits `org.hibernate`: the
# Bean Validation implementation lives at org.hibernate.validator and says nothing about ORM.
_JVM_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("spring-boot-starter-data-redis", "redis.clients", "io.lettuce"),
    "kafka": ("spring-kafka", "org.apache.kafka", "kafka-clients"),
    "rabbitmq": ("spring-boot-starter-amqp", "spring-rabbit", "com.rabbitmq"),
    "postgres": ("org.postgresql",),
    "mysql": ("mysql-connector", "com.mysql", "mariadb-java-client"),
    "mongodb": ("spring-boot-starter-data-mongodb", "mongodb-driver", "quarkus-mongodb"),
    "elasticsearch": (
        "co.elastic.clients",
        "elasticsearch-java",
        "spring-boot-starter-data-elasticsearch",
        "spring-data-elasticsearch",
        "org.elasticsearch.client",
        "org.opensearch.client",
    ),
    "jpa": (
        "spring-boot-starter-data-jpa",
        "spring-data-jpa",
        "hibernate-core",
        "hibernate-orm",
        "jakarta.persistence",
        "javax.persistence",
        "plugin.jpa",
    ),
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
    "rabbitmq": ("github.com/rabbitmq/amqp091-go", "github.com/streadway/amqp"),
    "postgres": ("github.com/jackc/pgx", "github.com/lib/pq"),
    "mysql": ("github.com/go-sql-driver/mysql",),
    "mongodb": ("go.mongodb.org/mongo-driver",),
    "elasticsearch": ("github.com/elastic/go-elasticsearch", "github.com/olivere/elastic"),
}
_RUST_INTEGRATIONS: dict[str, tuple[str, ...]] = {
    "redis": ("redis",),
    "kafka": ("rdkafka",),
    "rabbitmq": ("lapin",),
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
    "micronaut", "vertx", "gin", "echo", "fiber", "chi", "grpc", "aspnetcore", "axum",
    "actix-web", "rocket", "rails", "laravel", "symfony",
}  # fmt: skip

# Kubernetes is recorded as a framework when a manifest is found anywhere in the tree (k8s/,
# deploy/, manifests/, a service's own directory ...): a YAML document with `apiVersion:` and
# one of these workload / networking kinds, a Helm chart, or a kustomization. Pipeline YAML
# (.github/workflows) and compose files have neither, so a bare directory is never evidence.
_K8S_KINDS = (
    "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Service", "Ingress",
    "ConfigMap", "Secret", "Namespace", "HorizontalPodAutoscaler", "ServiceAccount",
    "PersistentVolumeClaim", "NetworkPolicy", "Pod",
)  # fmt: skip
_K8S_DOC = re.compile(r"^apiVersion:\s*\S+", re.MULTILINE)
_K8S_KIND = re.compile(r"^kind:\s*(" + "|".join(_K8S_KINDS) + r")\s*$", re.MULTILINE)
# Directories whose YAML is read first, so the 300-file bound is spent where manifests live.
_K8S_DIRS = frozenset(
    {"k8s", "kubernetes", "kube", "deploy", "deployment", "deployments", "manifests", "helm",
     "charts", "infra", "ops", "overlays", "base"}
)  # fmt: skip
_K8S_MAX_YAML = 300


def _detect_kubernetes(walker: Walker, frameworks: dict[str, Detection]) -> None:
    for entry in walker.find_by_name("Chart.yaml"):
        text = walker.read_text(entry.rel) or ""
        if re.search(r"^apiVersion:\s*v[12]\s*$", text, re.MULTILINE) and "name:" in text:
            _add(frameworks, "kubernetes", 0.9, entry.rel, "Helm chart")
    for name in ("kustomization.yaml", "kustomization.yml"):
        for entry in walker.find_by_name(name):
            _add(frameworks, "kubernetes", 0.9, entry.rel, "kustomization")
    skip_names = (*_DOCKER_FILES, "Chart.yaml", "kustomization.yaml", "kustomization.yml")
    candidates = [
        e
        for e in walker.find_by_suffix((".yaml", ".yml"))
        if not e.rel.startswith((".github/", ".gitlab/"))
        and e.rel.rsplit("/", 1)[-1] not in skip_names
    ]
    candidates.sort(key=lambda e: (not (set(e.rel.lower().split("/")[:-1]) & _K8S_DIRS), e.rel))
    for entry in candidates[:_K8S_MAX_YAML]:
        text = walker.read_text(entry.rel)
        if text is None or not _K8S_DOC.search(text):
            continue
        m = _K8S_KIND.search(text)
        if m:
            _add(frameworks, "kubernetes", 0.9, entry.rel, f"manifest kind {m.group(1)}")


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
        or "kubernetes" in fw
        or walker.under("helm")
        or walker.under("k8s")
        or walker.under(".github/workflows")
    ):
        _add(
            types,
            "infrastructure",
            0.6 if "terraform" in languages or "kubernetes" in fw else 0.4,
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


# ---- traits (ADR-0010) ---------------------------------------------------------------------
# Domain characteristics that manifests cannot show: the identifiers a codebase uses when it
# has the characteristic. Confidence comes from the share of sampled source files that mention
# one of them, so a stray word in one file is never a trait. Below 0.5 the trait is reported as
# a warning for the team to confirm in profile.yaml and is not used for recommendations.
_TRAIT_TOKENS: dict[str, re.Pattern[str]] = {
    "multi_tenant": re.compile(
        r"\b(tenant_?id|tenantId|TenantId|tenant_uuid|organization_?id|organizationId"
        r"|workspace_?id|workspaceId)\b"
    ),
    "money": re.compile(
        r"\b(wallet|ledger|invoice|refund|payout|chargeback|settlement|billing"
        r"|balance_?minor|amount_?minor|MinorUnits)\b",
        re.I,
    ),
    "pii": re.compile(
        r"\b(nationalId|national_id|dateOfBirth|date_of_birth|passport_?number|passportNumber"
        r"|ssn|social_security|gdpr|pii|personal_?data|personalData)\b",
        re.I,
    ),
    "telephony": re.compile(
        r"\b(SIP|dialplan|FreeSWITCH|FusionPBX|Asterisk|CDRs?|IVR|ring_?group|ringGroup"
        r"|caller_?id|callerId)\b"
    ),
}
# (share for 0.8, share for 0.6, share for 0.4) of sampled source files per trait.
_TRAIT_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "multi_tenant": (0.15, 0.06, 0.02),
    "money": (0.08, 0.03, 0.01),
    "pii": (0.06, 0.02, 0.005),
    "telephony": (0.05, 0.02, 0.005),
}
# A trait implied by a detected integration rather than by source tokens.
_TRAIT_FROM_FRAMEWORKS: dict[str, tuple[str, ...]] = {
    "event_driven": ("kafka", "rabbitmq", "celery"),
}
TRAIT_NAMES: tuple[str, ...] = (*_TRAIT_TOKENS, *_TRAIT_FROM_FRAMEWORKS)
_TRAIT_SAMPLE_FILES = 300
_SOURCE_SUFFIXES = tuple(sorted({s for suffixes in _LANG_SUFFIXES.values() for s in suffixes}))


def _sample_source_files(walker: Walker, limit: int = _TRAIT_SAMPLE_FILES) -> list[WalkEntry]:
    """Up to `limit` source files spread across top-level directories (round-robin), so a
    repository whose first directory alone holds more files than the limit still shows its
    other parts; the walk order within a directory is kept."""
    buckets: dict[str, list[WalkEntry]] = {}
    for entry in walker.find_by_suffix(_SOURCE_SUFFIXES):
        top = entry.rel.split("/", 1)[0] if "/" in entry.rel else ""
        buckets.setdefault(top, []).append(entry)
    out: list[WalkEntry] = []
    queues = [buckets[k] for k in sorted(buckets)]
    while len(out) < limit and queues:
        queues = [q for q in queues if q]
        for q in queues:
            if len(out) >= limit:
                break
            out.append(q.pop(0))
    return out


def _detect_traits(walker: Walker, frameworks: dict[str, Detection]) -> dict[str, Detection]:
    traits: dict[str, Detection] = {}
    for trait, names in _TRAIT_FROM_FRAMEWORKS.items():
        for fw in names:
            det = frameworks.get(fw)
            if det is not None and det.confidence >= 0.5:
                _add(traits, trait, 0.85, det.evidence[0].path, f"{fw} integration")
    sample = _sample_source_files(walker)
    hits: dict[str, list[tuple[str, str]]] = {t: [] for t in _TRAIT_TOKENS}
    sampled = 0
    for entry in sample:
        text = walker.read_text(entry.rel)
        if text is None:
            continue
        sampled += 1
        for trait, pattern in _TRAIT_TOKENS.items():
            m = pattern.search(text)
            if m:
                hits[trait].append((entry.rel, m.group(0)))
    for trait, found in hits.items():
        if not found or not sampled:
            continue
        share = len(found) / sampled
        hi, mid, low = _TRAIT_THRESHOLDS[trait]
        conf = 0.8 if share >= hi else 0.6 if share >= mid else 0.4 if share >= low else 0.0
        if not conf:
            continue
        if len(found) < 2:
            conf = 0.4  # one file is a hint for the team to confirm, never a trait on its own
        summary = f"{len(found)} of {sampled} sampled source files mention {found[0][1]!r}"
        for rel, token in found[:3]:
            _add(traits, trait, conf, rel, f"mentions {token!r}")
        traits[trait].confidence = conf  # _add bumps on repeats; the share decides
        traits[trait].evidence.insert(0, Evidence(path="*", detail=summary))
    return traits


PROFILE_OVERRIDE = ".agent-forge/profile.yaml"


class ProfileOverride(BaseModel):
    """`.agent-forge/profile.yaml`: what the team confirms or rules out about its project."""

    model_config = ConfigDict(extra="forbid")
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)
    traits: list[str] = Field(
        default_factory=list, description="domain traits the team confirms (ADR-0010)"
    )
    ignore: list[str] = Field(
        default_factory=list,
        description="detections to drop (language/framework/type/trait names)",
    )


def _load_override(walker: Walker, warnings: list[str] | None) -> ProfileOverride | None:
    text = walker.read_text(PROFILE_OVERRIDE)
    if text is None:
        return None
    try:
        raw = yaml.safe_load(text) or {}
        return ProfileOverride.model_validate(raw)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        if warnings is not None:
            warnings.append(f"{PROFILE_OVERRIDE} ignored: invalid ({str(exc).splitlines()[0]})")
        return None


def _apply_overrides(
    walker: Walker,
    languages: dict[str, Detection],
    frameworks: dict[str, Detection],
    warnings: list[str],
    types: dict[str, Detection],
    *,
    project_types_only: bool = False,
) -> None:
    ov = _load_override(walker, None if project_types_only else warnings)
    if ov is None:
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


def _apply_trait_overrides(
    walker: Walker, traits: dict[str, Detection], warnings: list[str]
) -> None:
    ov = _load_override(walker, None)
    if ov is None:
        return
    for name in ov.traits:
        if name not in TRAIT_NAMES:
            warnings.append(
                f"{PROFILE_OVERRIDE}: unknown trait {name!r} ignored "
                f"(known: {', '.join(TRAIT_NAMES)})"
            )
            continue
        traits.pop(name, None)
        _add(traits, name, 1.0, PROFILE_OVERRIDE, "confirmed by the project")
    for name in ov.ignore:
        traits.pop(name, None)


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
    _detect_kubernetes(walker, frameworks)
    if walker.exists("Makefile"):
        mk = walker.read_text("Makefile") or ""
        for target in ("test", "lint", "format", "build"):
            if re.search(rf"^{target}:", mk, re.MULTILINE):
                tests.append(f"make {target}")
    _apply_overrides(walker, languages, frameworks, warnings, types)
    _detect_project_types(walker, languages, frameworks, types)
    _apply_overrides(walker, languages, frameworks, warnings, types, project_types_only=True)
    traits = _detect_traits(walker, frameworks)
    _apply_trait_overrides(walker, traits, warnings)
    if agent_deps:
        _add(
            frameworks,
            "ai-sdk",
            0.8,
            "*",
            "agent-related dependencies: " + ", ".join(sorted(agent_deps)),
        )
    for kind, dets in (
        ("language", languages),
        ("framework", frameworks),
        ("project type", types),
        ("trait", traits),
    ):
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
        traits=sorted(traits.values(), key=lambda d: (-d.confidence, d.name)),
        platforms=inv.platforms,
        assets=inv.assets,
        managed=inv.managed,
        managed_manifest_valid=inv.managed_manifest_valid,
        test_commands=tests,
        sensitive_files=sorted(walker.sensitive),
        warnings=warnings,
        stats=walker.stats,
    )
