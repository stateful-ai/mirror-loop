"""Declarative spec of the two M1 CI gates — names, descriptions, selectors.

Both the GitHub Actions workflows (via the runner modules) and the dry-run
harness import this module, so the *gate definition* is in exactly one place.
A gate is a name, a one-line rationale, and the concrete ``pytest`` node ids
it runs — that triple is what GitHub branch protection ultimately requires
green, and what :mod:`ci.dry_run` deliberately drives red.

The check names below (``BYTE_IDENTITY_REPLAY_CHECK`` /
``BASELINE_ADAPTIVE_PARITY_CHECK``) are the literal job ids in
``.github/workflows/`` and are the strings a repo admin must paste into the
branch-protection "Require status checks to pass" list. Renaming a gate
here is therefore a coordinated change with both the workflow YAML *and* the
branch-protection settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Branch-protection check name for the byte-identity replay gate.
#: Must match ``.github/workflows/byte-identity-replay.yml`` ``jobs.<id>``.
BYTE_IDENTITY_REPLAY_CHECK = "byte-identity-replay"

#: Branch-protection check name for the structural baseline≡adaptive parity
#: gate. Must match ``.github/workflows/baseline-adaptive-parity.yml``
#: ``jobs.<id>``.
BASELINE_ADAPTIVE_PARITY_CHECK = "baseline-adaptive-parity"


@dataclass(frozen=True)
class Gate:
    """One required CI check: name, rationale, and the pytest nodes it runs."""

    #: GitHub Actions job id == branch-protection check name. Stable identifier.
    name: str
    #: One-line rationale, surfaced in the dry-run report and CI logs.
    rationale: str
    #: Pytest node ids that constitute the gate (files or ``file::test_name``).
    pytest_nodes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Gate 1: byte-identity replay (``docs/THESIS.md`` §2; seed 42 in
# ``docs/mirror_loop_m1_synthesis.md``).
#
# The whole of ``test_replay.py`` is the byte-identity gate: identical
# ``(seed, input log)`` reproduces byte-identical state across runs and
# processes, no clock or unsynced randomness on the game path (AST scan), and
# the committed golden fixture matches the canonical run. Selecting the file
# (not a subset of names) means an added byte-identity test is automatically
# part of the gate, so the CI surface never silently shrinks.
BYTE_IDENTITY_REPLAY = Gate(
    name=BYTE_IDENTITY_REPLAY_CHECK,
    rationale=(
        "Identical (seed, input log) reproduces a byte-identical state "
        "snapshot, with no wall-clock or unsynced randomness on the game path."
    ),
    pytest_nodes=("game/tests/test_replay.py",),
)


# ---------------------------------------------------------------------------
# Gate 2: structural baseline≡adaptive parity
# (``docs/mirror_loop_m1_synthesis.md`` "Gates"; the central finding of the
# blind A/B in ``game/tests/test_playtest.py``).
#
# Two complementary surfaces make up "structural parity":
#
# * ``game/tests/test_variants.py`` — the *same-shell* parity: every variant
#   plays the same spine, keeps the Reflection beat, preserves agency, and
#   feeds the locked gate; the baseline arms are player-independent.
# * ``game/tests/test_playtest.py::test_null_arms_produce_identical_decision_points``
#   — the headline structural assertion: under the conservative-null
#   population, adaptive and the fixed baseline produce byte-identical
#   ``decision_points()`` (predicted_actions + actual_action), which is why
#   the locked prediction metric cannot, by construction, separate the arms.
# * the canonical-run companion
#   ``::test_canonical_run_is_inconclusive_with_identical_arms`` — pins that
#   the aggregate scoring still reflects the parity (Δ top-1 == 0).
BASELINE_ADAPTIVE_PARITY = Gate(
    name=BASELINE_ADAPTIVE_PARITY_CHECK,
    rationale=(
        "The adaptive arm and the baseline arms run through the *same* "
        "engine (one toggle, never a forked path) and produce identical "
        "decision points under the conservative-null population."
    ),
    pytest_nodes=(
        "game/tests/test_variants.py",
        "game/tests/test_playtest.py::test_null_arms_produce_identical_decision_points",
        "game/tests/test_playtest.py::test_canonical_run_is_inconclusive_with_identical_arms",
    ),
)


#: Both gates as a tuple, in the order they are documented in
#: ``docs/CI.md``. ``ci.dry_run`` iterates this to report on each gate.
ALL_GATES: tuple[Gate, ...] = (BYTE_IDENTITY_REPLAY, BASELINE_ADAPTIVE_PARITY)
