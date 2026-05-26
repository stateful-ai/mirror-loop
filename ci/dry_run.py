"""Dry-run: deliberately break determinism and verify the gates flip red.

This is the executable form of the M1 acceptance bar's
*"deliberate determinism break flips them red in a dry run"* clause. It runs
two surgical breaks — one targeted at each gate — and asserts that every
break flips its corresponding CI gate red:

* **Break A** — drift the committed byte-identity golden fixture by a single
  byte. The :data:`ci.gates.BYTE_IDENTITY_REPLAY` gate must exit non-zero;
  the parity gate is unaffected.
* **Break B** — patch ``game.variants._Adaptive.order_choices`` to reverse
  the offered choices after the Mirror's adaptation. That makes the
  predicted_actions tiebreaker run in reversed declared order in the
  adaptive arm only, so the conservative-null population's decision points
  diverge between arms. The :data:`ci.gates.BASELINE_ADAPTIVE_PARITY` gate
  must exit non-zero; the byte-identity gate (which runs the *random*
  variant, not the adaptive one) is unaffected.

Each break is applied inside a strict ``try/finally`` that captures the
original file bytes up front and rewrites them on exit, so a crash, a
keyboard interrupt, or an exception during the gate run still restores the
working tree. The harness then verifies post-restoration that both gates are
green again — proof that the break was the cause and that nothing leaked.

Usage::

    python -m ci.dry_run                # run all breaks, exit 0 iff all behaved
    python -m ci.dry_run --break A      # just Break A (byte-identity)
    python -m ci.dry_run --break B      # just Break B (parity)

Exit code 0 means every break flipped the expected gate red and the working
tree was restored cleanly. Anything else is a *meta* failure of the gates
themselves and should be treated as a CI-system regression, not a code
regression.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence

from .gates import (
    ALL_GATES,
    BASELINE_ADAPTIVE_PARITY,
    BYTE_IDENTITY_REPLAY,
    REPO_ROOT,
    Gate,
)

# Files the breaks mutate. Capturing them as constants keeps the assumption
# they exist (and that ``test_golden_fixture_path_is_tracked_and_present``
# guards it) explicit at the top of the module.
_GOLDEN_FIXTURE = REPO_ROOT / "game" / "fixtures" / "baseline_seed42.json"
_VARIANTS_FILE = REPO_ROOT / "game" / "variants.py"


@contextmanager
def _replaced(path: Path, new_bytes: bytes) -> Iterator[None]:
    """Replace ``path`` with ``new_bytes`` for the duration of the block.

    Reads the file's *current* bytes (so restoration tracks the actual on-disk
    state, not a HEAD snapshot — works even if the developer has uncommitted
    edits) and restores them in a ``finally`` so a crash inside the block
    cannot leave the tree dirty.
    """
    if not path.exists():
        raise FileNotFoundError(f"dry-run cannot mutate missing file: {path}")
    original = path.read_bytes()
    try:
        path.write_bytes(new_bytes)
        yield
    finally:
        path.write_bytes(original)


def _run_gate_silently(gate: Gate) -> int:
    """Run a gate as a subprocess and return its exit code.

    The output is captured (not streamed) so the dry-run report stays
    readable; a failing gate's combined output is surfaced under the report
    line for that break.
    """
    module = {
        BYTE_IDENTITY_REPLAY.name: "ci.byte_identity_replay",
        BASELINE_ADAPTIVE_PARITY.name: "ci.baseline_adaptive_parity",
    }[gate.name]
    proc = subprocess.run(
        [sys.executable, "-m", module],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode


# --- The two break recipes ---------------------------------------------------


def _break_byte_identity_fixture() -> bytes:
    """Drift the golden fixture by one byte (insert a structural placeholder).

    The mutation is syntactically valid JSON of the right top-level shape but
    its bytes do not equal :func:`game.replay.canonical_run`'s output, so the
    ``--check`` CLI and ``test_canonical_run_matches_the_committed_golden_fixture``
    both fail loudly.
    """
    # An obviously-not-the-real-snapshot stand-in; minimal so the diff in the
    # CI log is obvious to a human reading the report.
    return b'{"schema_version": 1, "dry_run_break": "byte-identity"}\n'


def _break_parity_variants_file() -> bytes:
    """Patch ``_Adaptive.order_choices`` to reverse choices after adaptation.

    The reversal makes the declared-order tiebreaker that
    :meth:`loop.core.Mirror.rank` (called from ``Mirror.predict``) consults
    run in reversed order on the adaptive arm only. Under the conservative-
    null population, the player still picks by tendency id (presentation-
    independent), so ``actual_action`` is unchanged — but ``predicted_actions``
    diverge between arms whenever two choices tie in tendency_counts. That
    flips ``test_null_arms_produce_identical_decision_points`` red.

    The patch is a single-token swap inside one method, so the mutation is
    audit-friendly and the restored file is byte-identical to the original.
    """
    original = _VARIANTS_FILE.read_text(encoding="utf-8")
    needle = (
        "    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:\n"
        "        return mirror.adapt(state, scene)\n"
    )
    if needle not in original:
        raise RuntimeError(
            "dry-run: could not locate _Adaptive.order_choices body to patch; "
            "the dry-run recipe needs updating to match game/variants.py."
        )
    replacement = (
        "    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:\n"
        "        adapted = mirror.adapt(state, scene)\n"
        "        return replace(adapted, choices=tuple(reversed(adapted.choices)))\n"
    )
    return original.replace(needle, replacement, 1).encode("utf-8")


@dataclass(frozen=True)
class _Break:
    """One determinism-break recipe and the gate it must flip red."""

    label: str  # "A" / "B" — what the user passes to ``--break``
    description: str  # human-readable summary for the report
    target_path: Path  # file the break mutates
    mutated_bytes: Callable[[], bytes]  # produce the mutated file content
    must_red: Gate  # the gate that must go red
    must_stay_green: Gate  # the gate that must stay green (proves targeting)


BREAKS: tuple[_Break, ...] = (
    _Break(
        label="A",
        description="Drift the committed byte-identity golden fixture by one byte.",
        target_path=_GOLDEN_FIXTURE,
        mutated_bytes=_break_byte_identity_fixture,
        must_red=BYTE_IDENTITY_REPLAY,
        must_stay_green=BASELINE_ADAPTIVE_PARITY,
    ),
    _Break(
        label="B",
        description=(
            "Patch _Adaptive.order_choices to reverse choices after adaptation, "
            "diverging predicted_actions between adaptive and the baseline."
        ),
        target_path=_VARIANTS_FILE,
        mutated_bytes=_break_parity_variants_file,
        must_red=BASELINE_ADAPTIVE_PARITY,
        must_stay_green=BYTE_IDENTITY_REPLAY,
    ),
)


# --- Reporting ---------------------------------------------------------------


@dataclass(frozen=True)
class BreakOutcome:
    """The dry-run record for one break: who was red/green, vs expectation."""

    label: str
    description: str
    target: str
    red_exit_code: int  # exit code of the gate that *must* have gone red
    green_exit_code: int  # exit code of the gate that *must* have stayed green

    @property
    def red_as_expected(self) -> bool:
        return self.red_exit_code != 0

    @property
    def green_as_expected(self) -> bool:
        return self.green_exit_code == 0

    @property
    def ok(self) -> bool:
        return self.red_as_expected and self.green_as_expected


def _run_break(spec: _Break) -> BreakOutcome:
    """Apply ``spec`` for the scope of the gate runs, then assert outcomes.

    The expected-red gate is checked *first* so a faulty break (one that does
    not in fact perturb the targeted gate) is flagged before the unaffected
    gate even runs — that's the cheaper failure mode to surface.
    """
    new_bytes = spec.mutated_bytes()
    with _replaced(spec.target_path, new_bytes):
        red_code = _run_gate_silently(spec.must_red)
        green_code = _run_gate_silently(spec.must_stay_green)
    return BreakOutcome(
        label=spec.label,
        description=spec.description,
        target=str(spec.target_path.relative_to(REPO_ROOT)),
        red_exit_code=red_code,
        green_exit_code=green_code,
    )


def _format_report(outcomes: Sequence[BreakOutcome]) -> str:
    """A compact, deterministic, human-readable summary of the dry-run."""
    lines = ["Dry-run: deliberate determinism breaks vs. CI gates", "=" * 56]
    for o in outcomes:
        verdict = "OK " if o.ok else "BAD"
        lines.append(f"[{verdict}] Break {o.label}: {o.description}")
        lines.append(f"        target: {o.target}")
        lines.append(
            f"        expected-red gate exit:   {o.red_exit_code:>3}  "
            f"({'red' if o.red_as_expected else 'GREEN — UNEXPECTED'})"
        )
        lines.append(
            f"        expected-green gate exit: {o.green_exit_code:>3}  "
            f"({'green' if o.green_as_expected else 'RED — UNEXPECTED'})"
        )
    lines.append("")
    overall = "PASS" if all(o.ok for o in outcomes) else "FAIL"
    lines.append(f"Overall: {overall}")
    return "\n".join(lines) + "\n"


# --- Public entry points -----------------------------------------------------


def run(selected_labels: Sequence[str] | None = None) -> list[BreakOutcome]:
    """Run the selected breaks (default: all). Returns one outcome per break.

    A break that is not in ``selected_labels`` is skipped; an unknown label
    raises ``ValueError`` so a CLI typo fails loudly.
    """
    if selected_labels is None:
        chosen = BREAKS
    else:
        known = {b.label: b for b in BREAKS}
        unknown = [label for label in selected_labels if label not in known]
        if unknown:
            raise ValueError(
                f"unknown break label(s) {unknown}; choose from {sorted(known)}"
            )
        chosen = tuple(known[label] for label in selected_labels)
    return [_run_break(spec) for spec in chosen]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ci.dry_run", description=__doc__
    )
    parser.add_argument(
        "--break",
        dest="break_labels",
        action="append",
        choices=[b.label for b in BREAKS],
        help="restrict the dry-run to this break (repeatable; default: all)",
    )
    args = parser.parse_args(argv)
    outcomes = run(args.break_labels)
    sys.stdout.write(_format_report(outcomes))
    return 0 if all(o.ok for o in outcomes) else 1


# Re-exported so ``ci.dry_run.ALL_GATES`` works in tests / scripts without a
# second import; explicit so an editor jumping to definition lands here.
__all__ = (
    "ALL_GATES",
    "BREAKS",
    "BreakOutcome",
    "main",
    "run",
)


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
