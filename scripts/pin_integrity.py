"""Pin (or verify) the assets digest of every curated capability in capability.yaml.

    python scripts/pin_integrity.py            # write/refresh `integrity.assets_sha256`
    python scripts/pin_integrity.py --check    # exit 1 if any pin is missing or stale

The digest covers `assets/` only (relative paths + sha256 of each file), so editing the
manifest itself does not invalidate it, while editing any installed content does.
`agent-forge validate` reports mismatches as errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_forge.registry.loader import load_registry

ROOT = Path(__file__).resolve().parents[1]
_BLOCK = re.compile(r"^integrity:\n(?:[ \t]+.*\n)+", re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--registry", default=str(ROOT / "registry"))
    args = ap.parse_args()
    reg = load_registry(Path(args.registry), strict=True)
    # .gitattributes stores text as LF, so a CRLF working copy (Windows) would pin bytes that
    # no clone or release archive ever contains
    crlf = [
        p
        for lc in reg.items.values()
        for p in sorted((lc.directory / "assets").rglob("*"))
        if p.is_file() and b"\r\n" in p.read_bytes()
    ]
    if crlf:
        for p in crlf:
            print(f"!! CRLF line endings: {p}")
        print("normalize to LF first (git add --renormalize . && git checkout -- registry)")
        return 1
    stale = 0
    changed = 0
    for cid, lc in sorted(reg.items.items()):
        cap = lc.capability
        pinned = cap.integrity.assets_sha256 if cap.integrity else None
        if pinned == lc.assets_digest:
            continue
        stale += 1
        if args.check:
            print(f"!! {cid}: pinned={pinned and pinned[:12]} actual={lc.assets_digest[:12]}")
            continue
        manifest = lc.directory / "capability.yaml"
        text = manifest.read_text(encoding="utf-8")
        block = (
            "integrity:\n"
            f"  assets_sha256: {lc.assets_digest}\n"
            f'  pinned_at: "{datetime.now(UTC).date().isoformat()}"\n'
        )
        has_block = _BLOCK.search(text) is not None
        text = _BLOCK.sub(block, text, count=1) if has_block else text.rstrip("\n") + "\n" + block
        manifest.write_text(text, encoding="utf-8", newline="\n")
        changed += 1
        print(f"pinned {cid}: {lc.assets_digest[:12]}")
    print(f"{len(reg.items)} capabilities, {stale} stale/missing, {changed} written")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
