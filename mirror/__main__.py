"""``python -m mirror`` — print the mirror schema and run the coherence review.

A quick, dependency-free way to see the inferred-attribute schema and confirm it
still passes the anti-mush invariants. Exit code is 0 when coherent, 1 otherwise.
"""

from __future__ import annotations

import sys

from mirror.schema import MIRROR_SCHEMA, AttributeKind, coherence_report


def _shape(spec) -> str:
    if spec.kind is AttributeKind.DISTRIBUTION:
        return "{" + ", ".join(spec.modes) + "}"
    return f"{spec.poles[0]}  <->  {spec.poles[1]}"


def main() -> int:
    print(f"Mirror player-state schema — {len(MIRROR_SCHEMA)} inferred axes\n")
    for name, spec in MIRROR_SCHEMA.items():
        print(f"  {name}")
        print(f"    kind={spec.kind.value}  dynamics={spec.dynamics.value}  "
              f"lr={spec.learning_rate}  decay/turn={spec.decay_per_turn}")
        print(f"    {_shape(spec)}")
        print(f"    {spec.description}")
        print()
    report = coherence_report()
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
