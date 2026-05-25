"""Deterministic, seeded replay of the baseline arm — the byte-identity gate.

This is the M1 reproducibility deliverable (``docs/mirror_loop_m1_synthesis.md``,
"Gates … byte-identity replay under seed 42"): a session that runs **end-to-end
from a ``(seed, input log)`` pair** and serializes to a canonical state snapshot,
such that the *same* pair reproduces a **byte-identical** snapshot across two
runs (in any process). It is the non-adaptive **baseline arm** — the A/B control
the company treats as a first-class deliverable that "must be coherent and
deterministically replayable before adaptation exists" (product principle).

Two invariants make the gate honest, and both are pinned in
``game/tests/test_replay.py``:

* **No forked code path.** The run goes through the ordinary
  :func:`game.session.play_session` with the adaptation seam toggled to a
  baseline :class:`~game.variants.Variant` (architecture principle: the baseline
  is "the same engine with the adaptation seam set to identity … never a forked
  code path"). The replay harness only *drives and serializes* that engine.
* **No wall-clock, no unsynced randomness.** Nothing on the game path reads the
  clock or the global RNG. The only randomness in the baseline — the placebo
  arm's player-independent variation — is seeded (``random.Random`` keyed by the
  run seed), so it is *synced* to the ``(seed, input log)`` contract rather than
  to entropy. ``test_replay.py`` enforces this by scanning the game packages.

The "input log" is just the sequence of choice ids the player made, one per loop
— exactly what :func:`game.session.scripted_policy` replays. ``(seed, input log)``
therefore fully determines a run: the seed fixes any non-player variation, the
input log fixes every player decision, and the snapshot is a pure function of the
two.

Run it::

    python -m game.replay                 # canonical baseline run -> state JSON
    python -m game.replay --seed 7        # a different seed (different placebo)
    python -m game.replay --variant fixed # the identity baseline (seed-invariant)
    python -m game.replay --check         # verify the canonical run vs the golden
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from loop.core import PlayerState

from .session import LoopRecord, Session, play_session, scripted_policy
from .variants import VARIANT_NAMES, build_variant
from .world import DEFAULT_WORLD, World

#: Bump when the snapshot shape changes incompatibly, so a stale golden fixture
#: (or an old persisted snapshot) fails loudly instead of comparing apples to
#: oranges.
SCHEMA_VERSION = 1

#: The canonical seed for the byte-identity gate (``m1_synthesis`` "seed 42").
DEFAULT_SEED = 42

#: The default baseline arm. ``random`` is the *seeded* non-adaptive arm: its
#: content visibly varies but never tracks the player, so the seed is genuinely
#: load-bearing and the "no *unsynced* randomness" clause has teeth. ``fixed`` is
#: also a baseline (the identity transform); it is seed-invariant by construction.
BASELINE_VARIANT = "random"

#: The canonical input log for the golden fixture: a consistent "kind" player,
#: one choice id per slot of :data:`~game.world.DEFAULT_WORLD`. These ids are the
#: kindness option of each slot and are stable across every framing the baseline
#: can reveal (all framings of a slot share one choice spine; see
#: ``game.world``). ``test_replay.py`` pins this against the live "kind" persona
#: so it cannot silently drift.
CANONICAL_INPUT_LOG: tuple[str, ...] = (
    "c_reassure",  # intake       — reassured the technician
    "c_close",     # records      — left another participant's file closed
    "c_help",      # corridor     — guided a disoriented participant to safety
    "c_wait",      # confrontation— stayed with the participant
    "c_accept",    # exit         — accepted the prepared conclusion
)

#: The committed golden snapshot the CI gate replays against.
GOLDEN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "baseline_seed42.json"


@dataclass(frozen=True)
class RunResult:
    """A completed seeded run, plus everything needed to serialize it.

    ``seed``/``variant``/``world_name``/``input_log`` are the full set of inputs
    that determined the run; :class:`~game.session.Session` is the engine output.
    Keeping the inputs alongside the output makes the snapshot self-describing —
    a reader (or a diffing CI gate) can see exactly what produced it.
    """

    seed: int
    variant: str
    world_name: str
    input_log: tuple[str, ...]
    session: Session

    def snapshot(self) -> dict:
        """The canonical, fully deterministic state of this run as plain data.

        Pure function of ``(seed, input log, variant, world)``: no clock, no PID,
        no paths, no RNG — so two runs of the same inputs serialize identically.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "run": {
                "seed": self.seed,
                "variant": self.variant,
                "world": self.world_name,
                "input_log": list(self.input_log),
            },
            "loops": [_loop_snapshot(record) for record in self.session.records],
            "final_state": _final_state_snapshot(self.session.final_state),
        }

    def to_json(self) -> str:
        """The snapshot as canonical JSON — sorted keys, stable indentation.

        This string is the unit of "byte-identical state": equality of two runs'
        :meth:`to_json` output is the gate (and what the golden fixture stores).
        """
        return json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n"


def _loop_snapshot(record: LoopRecord) -> dict:
    """One loop's worth of observable state (what was shown, chosen, and said)."""
    result = record.result
    counts = result.state.tendency_counts
    return {
        "loop_index": record.loop_index,
        "scene_id": record.offered.id,
        "branch_key": record.branch_key,
        "declared_order": [c.id for c in record.declared.choices],
        "offered_order": [c.id for c in record.offered.choices],
        "predicted_actions": list(result.predicted_actions),
        "actual_action": result.actual_action,
        "reordered": record.reordered,
        "reflection": result.reflection.render() if result.reflection else None,
        "system_message": record.system_message.render(),
        # The player model after this loop, so a snapshot is a turn-by-turn audit
        # trail, not just an end state.
        "tendency_counts": dict(counts),
        "turn_count": result.state.turn_count,
    }


def _final_state_snapshot(state: PlayerState) -> dict:
    """The resulting player model: the running tally and what the Mirror named.

    ``announced`` is sorted so the serialized form is order-stable even though it
    restores from / lives in a ``frozenset``.
    """
    return {
        "tendency_counts": dict(state.tendency_counts),
        "announced": sorted(state.announced),
        "turn_count": state.turn_count,
    }


def run(
    seed: int,
    input_log: Sequence[str],
    *,
    variant: str = BASELINE_VARIANT,
    world: World = DEFAULT_WORLD,
) -> RunResult:
    """Play one full session from ``(seed, input_log)`` and return the result.

    The session is driven entirely by the two inputs: ``seed`` fixes any
    non-player variation (the placebo arm's framing/order draws), and
    ``input_log`` — one choice id per loop — fixes every player decision. The
    adaptation seam is set to ``variant`` (a baseline by default) through the
    ordinary :func:`game.session.play_session`; this harness never forks the
    engine, it only seeds, drives, and serializes it.

    Raises ``ValueError`` if ``input_log`` does not have exactly one choice per
    slot of ``world`` (so a short or long log fails loudly instead of replaying
    a partial session or running off the end of the spine).
    """
    if len(input_log) != world.length:
        raise ValueError(
            f"input log has {len(input_log)} choices but world {world.name!r} has "
            f"{world.length} slots; expected exactly one choice per loop"
        )
    arm = build_variant(variant, seed=seed)
    session = play_session(
        scripted_policy(list(input_log)),
        world=world,
        variant=arm,
    )
    return RunResult(
        seed=seed,
        variant=arm.name,
        world_name=world.name,
        input_log=tuple(input_log),
        session=session,
    )


def canonical_run() -> RunResult:
    """The run the golden fixture and the byte-identity gate are defined against."""
    return run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=BASELINE_VARIANT)


def load_golden() -> str:
    """The committed golden snapshot JSON (the expected byte-identical state)."""
    return GOLDEN_FIXTURE.read_text(encoding="utf-8")


def write_golden() -> str:
    """(Re)generate the golden fixture from :func:`canonical_run`; return its JSON.

    Run this deliberately (``python -m game.replay --write-fixture``) after an
    intended, reviewed change to the baseline so the committed golden tracks it.
    """
    text = canonical_run().to_json()
    GOLDEN_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FIXTURE.write_text(text, encoding="utf-8")
    return text


# --- CLI ---------------------------------------------------------------------


def _parse_input_log(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return CANONICAL_INPUT_LOG
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m game.replay", description=__doc__)
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"run seed (default {DEFAULT_SEED}; fixes any non-player variation)",
    )
    parser.add_argument(
        "--variant",
        choices=VARIANT_NAMES,
        default=BASELINE_VARIANT,
        help=f"adaptation arm (default {BASELINE_VARIANT!r}, a baseline)",
    )
    parser.add_argument(
        "--input",
        metavar="ID,ID,...",
        default=None,
        help="comma-separated choice-id input log (default: the canonical kind log)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="replay the canonical run and verify it matches the golden fixture",
    )
    mode.add_argument(
        "--write-fixture",
        action="store_true",
        help="(re)generate the golden fixture from the canonical run",
    )
    args = parser.parse_args(argv)

    if args.write_fixture:
        write_golden()
        print(f"wrote golden fixture: {GOLDEN_FIXTURE}", file=sys.stderr)
        return 0

    if args.check:
        actual = canonical_run().to_json()
        expected = load_golden()
        if actual == expected:
            print("[PASS] baseline replay is byte-identical to the golden fixture")
            return 0
        print(
            "[FAIL] baseline replay drifted from the golden fixture "
            f"({GOLDEN_FIXTURE.name}).\n"
            "If this change was intended, regenerate it with "
            "`python -m game.replay --write-fixture`.",
            file=sys.stderr,
        )
        return 1

    result = run(args.seed, _parse_input_log(args.input), variant=args.variant)
    sys.stdout.write(result.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
