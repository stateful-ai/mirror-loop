"""Runner for the **structural baseline≡adaptive parity** CI gate.

This is the command ``.github/workflows/baseline-adaptive-parity.yml`` shells
out to, and the same command a developer can run locally to reproduce a red
gate:

    python -m ci.baseline_adaptive_parity

It runs the parity test surface declared in
``ci.gates.BASELINE_ADAPTIVE_PARITY`` (the same-shell variant tests plus the
two ``test_playtest.py`` assertions that pin identical decision points and
the canonical Δ-top1=0 outcome).
"""

from __future__ import annotations

from ._runner import run_gate
from .gates import BASELINE_ADAPTIVE_PARITY


def main() -> int:
    return run_gate(BASELINE_ADAPTIVE_PARITY)


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
