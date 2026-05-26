"""Shared subprocess runner the two M1 gate scripts share.

A gate is just a curated pytest invocation (``ci.gates``) plus an optional
trailing CLI check (the byte-identity gate also runs
``python -m game.replay --check`` as a fast smoke). Keeping the shell-out
logic in one helper means the two ``python -m ci.<gate>`` entry points have
identical exit-code semantics and identical printed framing — handy when a
human is reading CI logs and trying to tell which gate failed.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Sequence

from .gates import REPO_ROOT, Gate


def run_pytest(nodes: Sequence[str]) -> int:
    """Run pytest on ``nodes`` from the repo root; return its exit code.

    Uses ``sys.executable -m pytest`` so the gate runs against whichever
    interpreter started the runner — the same one CI provisioned and the same
    one the dry-run drives.
    """
    cmd = [sys.executable, "-m", "pytest", "-q", *nodes]
    return subprocess.call(cmd, cwd=REPO_ROOT)


def run_gate(gate: Gate, *, extra_commands: Sequence[Sequence[str]] = ()) -> int:
    """Run ``gate``'s pytest selection, then any ``extra_commands`` in order.

    The first non-zero exit code wins (and short-circuits) — a single red
    step is enough to red the whole gate, and bailing early keeps the CI
    log focused on the actual failure.
    """
    banner = f"[ci] gate '{gate.name}': {gate.rationale}"
    print(banner, flush=True)
    code = run_pytest(gate.pytest_nodes)
    if code != 0:
        return code
    for cmd in extra_commands:
        print(f"[ci] gate '{gate.name}': $ {' '.join(cmd)}", flush=True)
        code = subprocess.call(list(cmd), cwd=REPO_ROOT)
        if code != 0:
            return code
    return 0
