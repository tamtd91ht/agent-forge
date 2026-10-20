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


def run(registry_dir: Path = ROOT / "registry", corpus: Path | None = None) -> dict[str, dict]:
    """`corpus` is an extra directory of reviewed projects laid out like examples/ (an
    anonymised set of real repositories kept outside this repository)."""
    out: dict[str, dict] = {}
    roots = [EXAMPLES] + ([corpus] if corpus else [])
    for root in roots:
        for example in sorted(p for p in root.iterdir() if (p / "expected.json").is_file()):
            expected = json.loads((example / "expected.json").read_text(encoding="utf-8"))
            actual = observe(example, registry_dir)
            key = example.name if root == EXAMPLES else f"corpus/{example.name}"
            out[key] = {"actual": actual, **compare(expected, actual)}
    return out


def aggregate(results: dict[str, dict]) -> dict[str, float]:
    """Micro-averaged precision / recall over every project (the CI threshold input),
    recomputed from the raw sets so it does not depend on per-project rounding."""
    hits = got = exp = 0
    for r in results.values():
        rec = set(r["actual"]["recommended"])
        missed, unexpected = set(r["missed"]), set(r["unexpected"])
        expected = (rec - unexpected) | missed
        hits += len(rec & expected)
        got += len(rec)
        exp += len(expected)
    return {
        "precision": round(hits / got, 3) if got else 1.0,
        "recall": round(hits / exp, 3) if exp else 1.0,
        "projects": len(results),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-actual", action="store_true")
    ap.add_argument("--corpus", type=Path, help="extra reviewed projects (examples/ layout)")
    ap.add_argument(
        "--min-precision", type=float, default=1.0, help="fail below this (micro-averaged)"
    )
    ap.add_argument(
        "--min-recall", type=float, default=1.0, help="fail below this (micro-averaged)"
    )
    args = ap.parse_args()
    if args.write_actual:
        for example in sorted(p for p in EXAMPLES.iterdir() if (p / "project").is_dir()):
            print(example.name, json.dumps(observe(example, ROOT / "registry"), indent=2))
        return 0
    results = run(corpus=args.corpus)
    totals = aggregate(results)
    if args.json:
        print(json.dumps({"projects": results, "aggregate": totals}, indent=2))
    else:
        for name, r in results.items():
            print(
                f"{name:18} precision {r['precision']:.2f}  recall {r['recall']:.2f}"
                + (f"  unexpected {r['unexpected']}" if r["unexpected"] else "")
                + (f"  missed {r['missed']}" if r["missed"] else "")
                + (f"  profile missing {r['profile_missing']}" if r["profile_missing"] else "")
                + (f"  optional differs {r['optional_diff']}" if r["optional_diff"] else "")
            )
    exact = all(
        r["precision"] == 1
        and r["recall"] == 1
        and not r["profile_missing"]
        and not r["optional_diff"]
        for name, r in results.items()
        if not name.startswith("corpus/")
    )
    thresholds = totals["precision"] >= args.min_precision and totals["recall"] >= args.min_recall
    if not args.json:
        print(
            f"aggregate over {totals['projects']} project(s): precision {totals['precision']:.2f} "
            f"recall {totals['recall']:.2f} (min {args.min_precision:.2f} / {args.min_recall:.2f})"
        )
    return 0 if exact and thresholds else 1


if __name__ == "__main__":
    raise SystemExit(main())
