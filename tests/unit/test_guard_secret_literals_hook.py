"""The workspace-authored credential-literal guard, run exactly as Claude Code would run it."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.conftest import REAL_REGISTRY

SCRIPT = (
    REAL_REGISTRY
    / "capabilities/forge.hook.guard-secret-literals/assets/claude_code/scripts/guard_secret_literals.py"
)


def _run(tool_input: dict, tool: str = "Write") -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input=payload, capture_output=True, text=True
    )


_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
_JWT = (
    "eyJhbGciOiJIUzI1NiJ9."
    + "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


@pytest.mark.parametrize(
    "text",
    [
        'password = "hunter2hunter2"',
        "API_KEY: 'sk_test_51H8f9a0b1c2d3e4f5g6h'",
        'client_secret="0123456789abcdef0123"',
        "key = 'AKIA" + "J7Q2W9X4Z1B8C5D3'",
        _PEM,
        "token = " + _JWT,
        "DATABASE_URL = 'postgres://app:s3cretpass@db.internal:5432/app'",
        "url: amqp://guest:guestpass@rabbit/",
        "GITHUB_TOKEN=ghp_" + "a" * 40,
    ],
)
def test_credential_literal_is_blocked(text: str) -> None:
    r = _run({"file_path": "src/config.py", "content": text})
    assert r.returncode == 2, text
    assert "agent-forge guard: blocked" in r.stderr


@pytest.mark.parametrize(
    "text",
    [
        'password = os.environ["DB_PASSWORD"]',
        "password: ${DB_PASSWORD}",
        'api_key = "<your-api-key>"',
        'password = "changeme"',
        "key = 'AKIA" + "IOSFODNN7EXAMPLE'",  # the AWS documentation example key
        "secret_key = settings.SECRET_KEY",
        "url: postgres://app@db.internal:5432/app",  # no password
        "# The password lives in the vault, never here.",
        'password = "ab"',  # too short to be a credential
    ],
)
def test_indirection_and_placeholders_pass(text: str) -> None:
    assert _run({"file_path": "src/config.py", "content": text}).returncode == 0, text


def test_edit_and_multiedit_payloads_are_inspected() -> None:
    bad = 'password = "hunter2hunter2"'
    assert _run({"file_path": "a.py", "old_string": "x", "new_string": bad}, "Edit").returncode == 2
    assert (
        _run(
            {
                "file_path": "a.py",
                "edits": [
                    {"old_string": "x", "new_string": "y"},
                    {"old_string": "y", "new_string": bad},
                ],
            },
            "MultiEdit",
        ).returncode
        == 2
    )
    # the old_string is what is being replaced; a secret there is being removed, not written
    assert (
        _run({"file_path": "a.py", "old_string": bad, "new_string": "clean"}, "Edit").returncode
        == 0
    )


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_auth.py",
        "src/__tests__/auth.spec.ts",
        "fixtures/creds.json",
        "docs/setup.md",
        "README.md",
        ".env.example",
        "config/app.yaml.template",
    ],
)
def test_test_fixture_and_doc_paths_are_skipped(path: str) -> None:
    r = _run({"file_path": path, "content": 'password = "hunter2hunter2"'})
    assert r.returncode == 0, path


def test_malformed_payload_fails_open() -> None:
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)], input="not json", capture_output=True, text=True
    )
    assert r.returncode == 0
    assert _run({}).returncode == 0
