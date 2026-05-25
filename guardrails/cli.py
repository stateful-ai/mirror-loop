"""CLI for the guardrails validator.

Validate a generated content package and print a PASS/REJECTED report::

    python -m guardrails <package.json>

Exit code is 0 when no hard invariant is violated (warnings allowed), 1 when the
content must not be promoted, 2 on usage error. This mirrors
``python -m acceptance.predictability`` so the two gates feel the same.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

from .invariants import validate_package


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        print("usage: python -m guardrails <package.json>", file=sys.stderr)
        return 2

    raw = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    report = validate_package(raw)
    print(report.render())
    return 0 if report.ok else 1
