"""The evaluation harness is a separate package (tools/agent-forge-eval); tests import it
from its source tree so the root suite covers it without installing it."""

from __future__ import annotations

import sys
from pathlib import Path

EVAL_SRC = Path(__file__).resolve().parents[2] / "tools" / "agent-forge-eval" / "src"
if str(EVAL_SRC) not in sys.path:
    sys.path.insert(0, str(EVAL_SRC))
