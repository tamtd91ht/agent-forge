"""Export JSON Schemas for capability manifests, plans and transactions into registry/schema/.

Run:  python scripts/export_schemas.py           write changed schemas
      python scripts/export_schemas.py --check   exit 1 if any schema is out of date (CI)
The exported schemas are the published contract; tests assert they match the Pydantic models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_forge.models.capability import Capability  # noqa: E402
from agent_forge.models.envelope import Envelope  # noqa: E402
from agent_forge.models.plan import Plan  # noqa: E402
from agent_forge.models.project import ProjectProfile  # noqa: E402
from agent_forge.models.transaction import Transaction  # noqa: E402

SCHEMAS = {
    "capability.schema.json": Capability,
    "plan.schema.json": Plan,
    "transaction.schema.json": Transaction,
    "project-profile.schema.json": ProjectProfile,
    "envelope.schema.json": Envelope,
}


def main() -> int:
    check = "--check" in sys.argv[1:]
    out_dir = ROOT / "registry" / "schema"
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = 0
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://agent-forge.local/schema/{name}"
        text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path = out_dir / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            changed += 1
            if check:
                print(f"out of date: {path}")
                continue
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path}")
    if check:
        print(f"{len(SCHEMAS)} schema(s), {changed} out of date")
        return 1 if changed else 0
    print(f"{len(SCHEMAS)} schema(s), {changed} updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
