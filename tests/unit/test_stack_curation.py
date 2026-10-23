"""0.4.0 stack curation: the catalog serves every detected stack, stack-specific counterparts
replace the generic TypeScript-flavoured skills, rule packs cost no always-loaded context, and
the scanner records data-store / tooling integrations the capabilities key on."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_forge.matching.rules import MatchContext, evaluate
from agent_forge.models.capability import CapabilityKind, Platform
from agent_forge.policy.engine import load_policies
from agent_forge.registry.context_load import context_chars
from agent_forge.registry.loader import load_registry
from agent_forge.scanner.project_profile import scan_project
from agent_forge.util import parse_frontmatter
from tests.conftest import REAL_REGISTRY, REPO_ROOT

REG = load_registry(REAL_REGISTRY)
POLICY = load_policies(REAL_REGISTRY)


def _recommended(root: Path) -> dict[str, str]:
    profile = scan_project(root)
    res = evaluate(REG, profile, MatchContext(platforms=(Platform.CLAUDE_CODE,), policy=POLICY))
    out = {c.capability.id: "recommended" for c in res.recommended}
    out.update({r.capability.id: r.category for r in res.rejected if r.capability.id not in out})
    return out


def test_rule_packs_are_path_scoped_and_cost_nothing_always_on() -> None:
    packs = [
        lc
        for cid, lc in REG.items.items()
        if cid.startswith("ecc.rules.") and cid != "ecc.rules.common"
    ]
    assert len(packs) == 21
    for lc in packs:
        assert lc.capability.kind == CapabilityKind.RULE
        assert context_chars(lc, Platform.CLAUDE_CODE) == 0, lc.capability.id
        assert not (
            lc.assets_dir
            / "claude_code"
            / lc.capability.id.replace("ecc.rules.", "ecc-")
            / "hooks.md"
        ).exists()
        for md in lc.assets_dir.rglob("*.md"):
            text = md.read_text(encoding="utf-8")
            assert text.startswith("---\npaths:"), md
            assert "](../" not in text and "](./" not in text, md  # links rewritten to names


def test_java_spring_gets_its_own_stack_and_not_the_typescript_flavoured_generics() -> None:
    got = _recommended(REPO_ROOT / "examples" / "java-spring" / "project")
    for cid in (
        "ecc.rules.java",
        "ecc.java-coding-standards",
        "ecc.springboot-patterns",
        "ecc.springboot-tdd",
        "ecc.springboot-security",
        "ecc.springboot-verification",
    ):
        assert got.get(cid) == "recommended", (cid, got.get(cid))
    # spring-boot-starter-web only: no JPA / Hibernate dependency, so no JPA patterns
    assert got.get("ecc.jpa-patterns") == "not_applicable"
    for generic in ("ecc.tdd-workflow", "ecc.security-review", "ecc.verification-loop"):
        assert got.get(generic) == "conflict", (generic, got.get(generic))
    # nothing from other stacks leaks in
    assert all(
        got.get(cid) == "not_applicable"
        for cid in (
            "ecc.rules.golang",
            "ecc.golang-patterns",
            "ecc.react-patterns",
            "ecc.rules.typescript",
            "ecc.python-testing",
        )
    )


def test_go_and_dotnet_fixtures_get_their_packs_only() -> None:
    go = _recommended(REPO_ROOT / "examples" / "go-gin" / "project")
    assert {go["ecc.rules.golang"], go["ecc.golang-patterns"], go["ecc.golang-testing"]} == {
        "recommended"
    }
    assert go["ecc.rules.java"] == "not_applicable" and go["ecc.tdd-workflow"] == "recommended"
    net = _recommended(REPO_ROOT / "examples" / "dotnet-webapi" / "project")
    assert {net["ecc.rules.csharp"], net["ecc.dotnet-patterns"], net["ecc.csharp-testing"]} == {
        "recommended"
    }


def test_view_data_loading_applies_to_web_and_mobile_projects_only() -> None:
    web = _recommended(REPO_ROOT / "examples" / "nextjs-ts" / "project")
    assert web["forge.skill.view-data-loading"] == "recommended"
    assert web["ecc.rules.react"] == "recommended" and web["ecc.react-testing"] == "recommended"
    backend = _recommended(REPO_ROOT / "examples" / "java-spring" / "project")
    assert backend["forge.skill.view-data-loading"] == "not_applicable"


@pytest.mark.parametrize(
    ("files", "framework", "capability"),
    [
        (
            {
                "pom.xml": "<project><dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-data-redis</artifactId></dependency><dependency><groupId>org.apache.kafka</groupId><artifactId>kafka-clients</artifactId></dependency></dependencies></project>",
                "src/main/java/App.java": "class App {}",
            },
            "redis",
            "ecc.redis-patterns",
        ),
        (
            {
                "package.json": '{"name":"web","dependencies":{"react":"18","pg":"8","@prisma/client":"5"}}',
                "src/a.tsx": "export const A = 1;",
            },
            "prisma",
            "ecc.prisma-patterns",
        ),
        (
            {
                "pyproject.toml": "[project]\nname='svc'\nversion='0'\ndependencies=['fastapi','psycopg','celery']\n",
                "app/main.py": "x=1\n",
            },
            "celery",
            "ecc.django-celery",
        ),
        (
            {
                "go.mod": "module m\n\nrequire github.com/redis/go-redis/v9 v9.0.0\nrequire github.com/segmentio/kafka-go v0.4.0\n",
                "main.go": "package main\nfunc main(){}\n",
            },
            "kafka",
            None,
        ),
    ],
)
def test_scanner_records_integrations_and_capabilities_key_on_them(
    tmp_path: Path, files, framework, capability
) -> None:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    profile = scan_project(tmp_path)
    assert framework in profile.framework_names, profile.framework_names
    if capability:
        got = _recommended(tmp_path)
        assert got.get(capability) == "recommended", (capability, got.get(capability))
    # a Dockerfile makes deployment-patterns applicable
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert "docker" in scan_project(tmp_path).framework_names
    assert _recommended(tmp_path).get("ecc.deployment-patterns") == "recommended"


_POM = (
    "<project><dependencies>"
    "<dependency><groupId>org.springframework.boot</groupId>"
    "<artifactId>spring-boot-starter-web</artifactId></dependency>{extra}"
    "</dependencies></project>"
)
_JPA = (
    "<dependency><groupId>org.springframework.boot</groupId>"
    "<artifactId>spring-boot-starter-data-jpa</artifactId></dependency>"
)
_MONGO = (
    "<dependency><groupId>org.springframework.boot</groupId>"
    "<artifactId>spring-boot-starter-data-mongodb</artifactId></dependency>"
)


@pytest.mark.parametrize(
    ("extra", "jpa", "mongo"),
    [
        (_JPA, "recommended", "not_applicable"),
        (_MONGO, "not_applicable", "recommended"),
        ("", "not_applicable", "not_applicable"),
        # Bean Validation lives at org.hibernate.validator and says nothing about ORM
        (
            "<dependency><groupId>org.hibernate.validator</groupId>"
            "<artifactId>hibernate-validator</artifactId></dependency>",
            "not_applicable",
            "not_applicable",
        ),
    ],
)
def test_jpa_patterns_need_a_jpa_dependency_not_only_spring(
    tmp_path: Path, extra: str, jpa: str, mongo: str
) -> None:
    (tmp_path / "pom.xml").write_text(_POM.format(extra=extra), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.java").write_text("class App {}\n", encoding="utf-8")
    got = _recommended(tmp_path)
    assert got["ecc.springboot-patterns"] == "recommended"
    assert got["ecc.jpa-patterns"] == jpa, got["ecc.jpa-patterns"]
    assert got["forge.skill.mongodb-patterns"] == mongo


def test_stack_skills_follow_their_integrations_on_the_platform_fixture() -> None:
    got = _recommended(REPO_ROOT / "examples" / "jvm-platform" / "project")
    for cid in (
        "forge.skill.vertx-patterns",
        "forge.skill.elasticsearch-patterns",
        "forge.skill.mongodb-patterns",
        "ecc.kubernetes-patterns",
        "ecc.springboot-patterns",
        "forge.skill.event-consumer-safety",
    ):
        assert got.get(cid) == "recommended", (cid, got.get(cid))
    assert got["ecc.jpa-patterns"] == "not_applicable"
    for cid in (
        "forge.skill.vertx-patterns",
        "forge.skill.elasticsearch-patterns",
        "forge.skill.mongodb-patterns",
    ):
        lc = REG.get(cid)
        assert lc.capability.kind == CapabilityKind.SKILL
        assert Platform.CODEX in lc.capability.platforms
        claude = lc.capability.destinations_for(Platform.CLAUDE_CODE)[0].source
        codex = lc.capability.destinations_for(Platform.CODEX)[0].source
        raw = (lc.assets_dir / claude / "SKILL.md").read_bytes()
        assert raw == (lc.assets_dir / codex / "SKILL.md").read_bytes()
        fm, _ = parse_frontmatter(raw.decode("utf-8"))
        # name + description only: the body is loaded on demand
        assert context_chars(lc, Platform.CLAUDE_CODE) == len(fm["name"]) + len(fm["description"])


def test_kubernetes_patterns_are_not_recommended_without_manifests() -> None:
    got = _recommended(REPO_ROOT / "examples" / "java-spring" / "project")
    assert got["ecc.kubernetes-patterns"] == "not_applicable"
