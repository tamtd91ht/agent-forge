"""Measure scanner and resolver quality against the reviewed example projects (vision Gate E).

For each `examples/<name>/` the project is copied to a temporary directory, scanned and
matched against the registry with the default policy; the result is compared with the
manually reviewed `expected.json`:

  profile:     expected languages / frameworks / project types must all be detected
  recommended: precision (recommended ∩ expected / recommended) and
               recall    (recommended ∩ expected / expected)

Run:  python scripts/matching_report.py [--json] [--write-actual]
`--write-actual` prints the observed result per example, to help review a new fixture; it
never writes expected.json (expectations are reviewed by hand).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_forge.matching.rules import MatchContext, evaluate  # noqa: E402
from agent_forge.models.capability import Platform  # noqa: E402
from agent_forge.policy.engine import load_policies  # noqa: E402
from agent_forge.registry.loader import load_registry  # noqa: E402
from agent_forge.scanner.project_profile import scan_project  # noqa: E402

EXAMPLES = ROOT / "examples"


def observe(example: Path, registry_dir: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / example.name
        shutil.copytree(example / "project", target)
        profile = scan_project(target)
        reg = load_registry(registry_dir)
        ctx = MatchContext(
            platforms=(Platform.CLAUDE_CODE,),
            policy=load_policies(registry_dir, None, target),
        )
        res = evaluate(reg, profile, ctx)
        return {
            "languages": sorted(profile.language_names),
            "frameworks": sorted(profile.framework_names),
            "project_types": sorted(profile.project_type_names),
            "test_commands": profile.test_commands,
            "warnings": [w for w in profile.warnings if "git" not in w],
            "recommended": sorted({c.capability.id for c in res.recommended}),
            "optional": sorted({c.capability.id for c in res.optional}),
        }


def compare(expected: dict, actual: dict) -> dict:
    exp, got = set(expected["recommended"]), set(actual["recommended"])
    hits = exp & got
    missing_profile = {
        key: sorted(set(expected.get(key, [])) - set(actual[key]))
        for key in ("languages", "frameworks", "project_types", "test_commands")
    }
    optional_diff = sorted(set(expected.get("optional", [])) ^ set(actual["optional"]))
    return {
        "optional_diff": optional_diff,
        "precision": round(len(hits) / len(got), 3) if got else 1.0,
        "recall": round(len(hits) / len(exp), 3) if exp else 1.0,
        "unexpected": sorted(got - exp),
        "missed": sorted(exp - got),
        "profile_missing": {k: v for k, v in missing_profile.items() if v},
    }


def run(registry_dir: Path = ROOT / "registry") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for example in sorted(p for p in EXAMPLES.iterdir() if (p / "expected.json").is_file()):
        expected = json.loads((example / "expected.json").read_text(encoding="utf-8"))
        actual = observe(example, registry_dir)
        out[example.name] = {"actual": actual, **compare(expected, actual)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-actual", action="store_true")
    args = ap.parse_args()
    if args.write_actual:
        for example in sorted(p for p in EXAMPLES.iterdir() if (p / "project").is_dir()):
            print(example.name, json.dumps(observe(example, ROOT / "registry"), indent=2))
        return 0
    results = run()
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for name, r in results.items():
            print(
                f"{name:18} precision {r['precision']:.2f}  recall {r['recall']:.2f}"
                + (f"  unexpected {r['unexpected']}" if r["unexpected"] else "")
                + (f"  missed {r['missed']}" if r["missed"] else "")
                + (f"  profile missing {r['profile_missing']}" if r["profile_missing"] else "")
                + (f"  optional differs {r['optional_diff']}" if r["optional_diff"] else "")
            )
    ok = all(
        r["precision"] == 1
        and r["recall"] == 1
        and not r["profile_missing"]
        and not r["optional_diff"]
        for r in results.values()
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
