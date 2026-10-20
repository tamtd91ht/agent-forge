"""Watch the official documentation pages each adapter was verified against.

Every adapter records `docs_url` and `verified_on`. This script fetches each page, reduces it
to normalised text (tags stripped, whitespace collapsed) and compares its digest with the one
stored in `src/agent_forge/adapters/docs_hashes.json`:

  python scripts/watch_docs.py --update   # (maintainer, after re-verifying) store the digests
  python scripts/watch_docs.py --check    # (weekly CI) exit 1 and list pages that changed

A changed page does not mean the conventions changed; it means someone must look. The weekly
workflow opens an issue listing the pages, and the maintainer re-verifies, bumps
`verified_on` and runs `--update` in the same PR. Network access is the only side effect.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_forge.adapters import all_adapters  # noqa: E402

HASHES = ROOT / "src" / "agent_forge" / "adapters" / "docs_hashes.json"
# docs_url plus the other pages a docstring names as verified
EXTRA_PAGES: dict[str, list[str]] = {
    "cursor": ["https://cursor.com/docs/context/mcp"],
    "gemini": [
        "https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/skills.md",
        "https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md",
    ],
    "copilot": ["https://docs.github.com/en/copilot/concepts/agents/about-agent-skills"],
    "claude_code": [
        "https://code.claude.com/docs/en/skills",
        "https://code.claude.com/docs/en/sub-agents",
        "https://code.claude.com/docs/en/hooks",
        "https://code.claude.com/docs/en/mcp",
    ],
}


def normalise(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch(url: str, timeout: float = 30.0) -> str:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https url {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "agent-forge-docs-watch"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https docs pages only
        return resp.read().decode("utf-8", errors="replace")


def digest(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https url {url}")
    return hashlib.sha256(normalise(fetch(url)).encode("utf-8")).hexdigest()


def pages() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for a in all_adapters():
        key = a.platform.value
        out[key] = [a.info.docs_url, *EXTRA_PAGES.get(key, [])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--update", action="store_true", help="store current digests")
    g.add_argument("--check", action="store_true", help="compare with stored digests")
    args = ap.parse_args()
    stored: dict[str, dict] = (
        json.loads(HASHES.read_text(encoding="utf-8")) if HASHES.is_file() else {}
    )
    current: dict[str, dict] = {}
    failures: list[str] = []
    changed: list[str] = []
    for platform, urls in pages().items():
        verified_on = next(
            a.info.verified_on for a in all_adapters() if a.platform.value == platform
        )
        entry: dict = {"verified_on": verified_on, "pages": {}}
        for url in urls:
            try:
                entry["pages"][url] = digest(url)
            except Exception as exc:  # network / http errors are reported, not hidden
                failures.append(f"{platform}: {url}: {exc}")
        current[platform] = entry
    if args.update:
        HASHES.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"stored digests for {sum(len(e['pages']) for e in current.values())} page(s) in {HASHES}"
        )
        for f in failures:
            print("not stored:", f)
        return 1 if failures else 0
    for platform, entry in current.items():
        old = (stored.get(platform) or {}).get("pages", {})
        for url, h in entry["pages"].items():
            if url not in old:
                changed.append(f"{platform}: {url} (no stored digest; run --update)")
            elif old[url] != h:
                changed.append(
                    f"{platform}: {url} changed since verified_on {stored[platform].get('verified_on')}"
                )
    for line in changed:
        print("CHANGED", line)
    for line in failures:
        print("ERROR  ", line)
    if not changed and not failures:
        print("documentation pages unchanged")
    return 1 if (changed or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
