"""Runner for the **byte-identity replay** CI gate.

This is the command ``.github/workflows/byte-identity-replay.yml`` shells out
to, and the same command a developer can run locally to reproduce a red gate:

    python -m ci.byte_identity_replay

It does two things, in order:

1. Runs the byte-identity test surface (``ci.gates.BYTE_IDENTITY_REPLAY``).
2. Runs ``python -m game.replay --check`` — the canonical replay against the
   committed golden fixture. Redundant with the test that pins the same
   property, but it surfaces a fixture drift quickly in CI logs without
   requiring a reader to know which pytest test pinned what.

Exit code is the first non-zero exit code of any step (0 on full success).
"""

from __future__ import annotations

import sys

from ._runner import run_gate
from .gates import BYTE_IDENTITY_REPLAY


def main() -> int:
    return run_gate(
        BYTE_IDENTITY_REPLAY,
        extra_commands=[[sys.executable, "-m", "game.replay", "--check"]],
    )


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
