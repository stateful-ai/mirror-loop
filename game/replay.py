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
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from loop.core import PlayerState

from .adapt import adapt_slot
from .session import LoopRecord, Session, play_session, scripted_policy
from .variants import ADAPTIVE, FIXED, VARIANT_NAMES, build_variant
from .world import DEFAULT_WORLD, Slot, World, get_world

#: Bump when the snapshot shape changes incompatibly, so a stale golden fixture
#: (or an old persisted snapshot) fails loudly instead of comparing apples to
#: oranges.
SCHEMA_VERSION = 1

#: Bump when the canonical JSONL spec changes incompatibly. The spec is:
#:
#: * one JSON object per line, encoded by :func:`canonical_dumps` —
#:   ``sort_keys=True`` (so the bytes depend on the field *set*, not insertion
#:   order), compact ``(",", ":")`` separators, and ``allow_nan=False`` (NaN /
#:   Infinity have no canonical JSON form and so are refused at serialization
#:   rather than silently emitted as non-roundtripping tokens),
#: * every record carries a monotonic ``event_seq`` (the logical clock — 0 for
#:   the run header, then one increment per record, ending at the trailer) and
#:   a content-addressable ``event_id`` (SHA-256 of the rest of the canonical
#:   record, truncated; identical ``(seed, input_log)`` runs produce identical
#:   ``event_id``s by construction, so a same-seed regression in *any* field is
#:   localized to the line whose id moved),
#: * no wall-clock fields — the AST scan in :mod:`game.tests.test_replay`
#:   forbids ``time``/``datetime``/``secrets``/``uuid`` in the runtime
#:   packages, so a future contributor cannot smuggle one in.
#:
#: This is bumped independently of :data:`SCHEMA_VERSION`: the JSONL spec and
#: the JSON snapshot shape are two different serializations of the same run, and
#: each is versioned against its own consumers.
JSONL_SPEC_VERSION = 1

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

#: The committed JSONL fixture for the M1 canonical run — the same seeded run,
#: serialized as the append-only event stream the founder brief locks in (one
#: typed record per line: a ``run`` header, one ``loop`` record per slot, and a
#: ``final_state`` trailer). The byte-identity gate replays against this file.
M1_CANONICAL_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "m1_canonical.jsonl"
)


# --- Canonical JSONL encoding -------------------------------------------------
# These three primitives implement the JSONL_SPEC_VERSION contract above. They
# are deliberately tiny and pure — every property the byte-identity gate cares
# about is a property of `canonical_dumps`, `_event_id_for`, and
# `_stamp_clock_and_id`, not of the records that flow through them.


def canonical_dumps(payload: dict) -> str:
    """Serialize ``payload`` to canonical JSON bytes for the JSONL spec.

    Three knobs, pinned, each closing a way the bytes could drift between two
    same-seed runs:

    * ``sort_keys=True`` — output is keyed by the field *set*, not the dict's
      insertion order. Two callers that build the same record in different
      orders (or under a different Python build's dict-iteration order) emit
      identical bytes.
    * compact ``(",", ":")`` separators — no incidental whitespace; each line
      stays one self-contained, diff-friendly record.
    * ``allow_nan=False`` — NaN/Infinity have no canonical JSON encoding and
      are not finite; if one ever leaked into a record this raises rather
      than emitting a JS-only ``NaN``/``Infinity`` token that no roundtrip
      reader is required to accept. Finite floats roundtrip through Python's
      shortest-repr serializer, which is platform-independent.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _event_id_for(payload: dict) -> str:
    """Deterministic content-addressable id for one JSONL record.

    SHA-256 of the record's canonical bytes minus the ``event_id`` field
    itself (which would otherwise be self-referential), truncated to 16 hex
    chars (64 bits — collision-resistant for the M1 record-count regime, and
    short enough that the id does not dominate the line).

    Two records with the same canonical body produce the same id. So an
    adaptive log stripped of its provenance and a fixed log on the same
    ``(seed, input_log)`` carry identical ids per line (the parity property
    :func:`strip_adaptation` relies on).
    """
    body = canonical_dumps({k: v for k, v in payload.items() if k != "event_id"})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _stamp_clock_and_id(records: list[dict]) -> list[dict]:
    """Stamp each record with its logical clock and content-addressable id.

    ``event_seq`` is the monotonic 0-based position in the stream — the
    logical clock the founder brief asks for. Including it in the payload
    means the content hash (``event_id``) also captures position, so two
    records that share a body but sit at different positions still get
    distinct ids.
    """
    stamped: list[dict] = []
    for seq, record in enumerate(records):
        payload = {**record, "event_seq": seq}
        payload["event_id"] = _event_id_for(payload)
        stamped.append(payload)
    return stamped


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
        Loop records in the adaptive arm carry a ``provenance`` tag for every
        decision the adaptation layer emitted or mutated, so the log alone is
        enough for :func:`strip_adaptation` to project the run to its baseline.
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "run": {
                "seed": self.seed,
                "variant": self.variant,
                "world": self.world_name,
                "input_log": list(self.input_log),
            },
            "loops": self._loop_dicts(),
            "final_state": _final_state_snapshot(self.session.final_state),
        }

    def to_json(self) -> str:
        """The snapshot as canonical JSON — sorted keys, stable indentation.

        This string is the unit of "byte-identical state": equality of two runs'
        :meth:`to_json` output is the gate (and what the golden fixture stores).
        """
        return json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n"

    def jsonl_records(self) -> list[dict]:
        """The run as a sequence of typed event records, one per JSONL line.

        The M1 founder brief locks the spine as "events (append-only JSONL) →
        reducer → MirrorState → render". This is the canonical event stream for
        the seed-42 baseline run: a ``run`` header that names the (seed, input
        log, variant, world) the run is replayable from, one ``loop`` record per
        slot (the same data :meth:`snapshot` carries, flattened with a ``type``
        discriminator), and a ``final_state`` trailer holding the resulting
        player model.

        Every record is stamped with two determinism-load-bearing fields, per
        the canonical JSONL spec (:data:`JSONL_SPEC_VERSION`):

        * ``event_seq`` — the logical clock, 0..N monotonic per record, so a
          replay reader has a record-position handle that does not depend on
          line numbering or stream boundaries.
        * ``event_id`` — a content hash of the rest of the record, so two
          same-seed runs produce per-line-identical ids and a drift in any
          single field is localized to the one line whose id moved.
        """
        raw: list[dict] = [
            {
                "type": "run",
                # Stamped as `jsonl_spec_version` (not `schema_version`) so the
                # wire byte distinguishes this from the JSON snapshot's
                # `schema_version`: two independently versioned serializations
                # of the same run must not name-collide on the wire, or a
                # consumer reading the JSONL cannot tell which constant a
                # mismatched version refers to.
                "jsonl_spec_version": JSONL_SPEC_VERSION,
                "seed": self.seed,
                "variant": self.variant,
                "world": self.world_name,
                "input_log": list(self.input_log),
            }
        ]
        for loop in self._loop_dicts():
            raw.append({"type": "loop", **loop})
        raw.append(
            {"type": "final_state", **_final_state_snapshot(self.session.final_state)}
        )
        return _stamp_clock_and_id(raw)

    def _loop_dicts(self) -> list[dict]:
        """The per-loop snapshot dicts, with adaptation provenance threaded in.

        Iterates the session with the *pre-loop* player state in hand, so each
        adaptation the loop emitted is tagged with the exact Mirror read it was a
        function of. Every loop in which the adaptation layer emitted or mutated
        content gets a ``provenance`` block; baseline arms produce none, so their
        per-loop dicts are byte-identical to what :func:`_loop_snapshot` would
        emit alone — keeping the canonical baseline fixture unchanged.
        """
        world = get_world(self.world_name)
        adaptive = self.variant == ADAPTIVE.name
        loops: list[dict] = []
        pre_state = PlayerState()
        for slot, record in zip(world.slots, self.session.records):
            entry = _loop_snapshot(record)
            if adaptive:
                provenance = _provenance_block(slot, record, pre_state)
                if provenance is not None:
                    entry["provenance"] = provenance
            loops.append(entry)
            pre_state = record.result.state
        return loops

    def to_jsonl(self) -> str:
        """The run as canonical JSONL — one event per line, sorted keys.

        This is the unit of byte-identical state for ``fixtures/m1_canonical.jsonl``:
        two runs of the same ``(seed, input log, variant, world)`` produce
        identical bytes. The serialization is intentionally compact (no
        whitespace between tokens) so each line is one self-contained record and
        the file is friendly to streaming readers.
        """
        lines = [canonical_dumps(record) for record in self.jsonl_records()]
        return "\n".join(lines) + "\n"


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


def _provenance_block(
    slot: Slot, record: LoopRecord, pre_state: PlayerState
) -> dict | None:
    """The adaptation provenance for one loop, or ``None`` if nothing fired.

    Defers to the single authoritative producer (:func:`game.adapt.adapt_slot`)
    so the layer's emissions are tagged with the exact
    :class:`~game.adaptation.Adaptation` records it would write to the audit log
    — the same trigger snapshot and source event-seq, threaded with the
    *pre-loop* player state the decision was a function of. Alongside the
    adaptations the block carries a ``baseline`` view: the values the mutated
    fields would have had under the identity baseline, sufficient on its own for
    :func:`strip_adaptation` to invert the transform from the log alone.

    The baseline view is reconstructed from the slot itself (via
    :data:`~game.variants.FIXED`), **not** from ``record.declared`` — which on a
    branch slot is the revealed branch's scene, whose choice IDs are not
    guaranteed to equal the default branch's. Reading from the slot keeps the
    projection sound for any world whose branches diverge in their authored
    choice set, not only the one whose branches happen to share an ID spine.
    """
    adapted = adapt_slot(slot, pre_state)
    if not adapted.adaptations:
        return None
    baseline_scene, baseline_branch = FIXED.select_scene(slot, pre_state)
    return {
        "adaptations": [a.to_dict() for a in adapted.adaptations],
        "baseline": {
            "branch_key": baseline_branch,
            "offered_order": [c.id for c in baseline_scene.choices],
            "reordered": False,
        },
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


# --- The structural parity projection ----------------------------------------
# Every event the adaptation layer emits or mutates in the canonical JSONL log
# carries a ``provenance`` tag (:func:`_provenance_block`); this function is the
# inverse — strip the tags, revert the mutated fields, and what remains is the
# baseline arm's log on the same seed and inputs. This is the mechanism the
# structural ``baseline ≡ adaptive`` parity gate
# (``docs/adr/0001-m1-locks.md`` §1, ``docs/mirror_loop_m1_synthesis.md``)
# depends on: the adaptive arm is the baseline arm with the adaptation seam
# enabled, and the parity is recoverable from the log alone without re-running
# the engine.


def strip_adaptation(jsonl_text: str) -> str:
    """Project an adaptive-arm JSONL log to its identity-baseline equivalent.

    Iterates the log line by line and inverts everything the adaptation layer
    tagged with provenance. For each ``loop`` record carrying a ``provenance``
    block this reverts the mutated fields (``branch_key``, ``offered_order``,
    ``reordered``) to the ``baseline`` view recorded inside it, then drops the
    block; for the ``run`` header it relabels ``variant: "adaptive"`` to
    ``"fixed"`` — the only run-level field the adaptation layer's choice of arm
    influences. All other fields are pure functions of the player model and so
    are arm-invariant by construction (the prediction, the reflection, the
    system message, the tendency tally) and pass through unchanged.

    The resulting text is byte-identical to ``run(seed, input_log,
    variant="fixed").to_jsonl()`` on the same seed and input log — the mechanism
    the parity gate depends on.

    Raises ``ValueError`` if the log refers to a world this build does not
    register (so an alien log fails loudly rather than silently producing a
    not-quite-baseline projection); pure with respect to ``jsonl_text`` (no I/O,
    no engine call), so the projection is exactly as deterministic as the log.
    """
    out_lines: list[str] = []
    for line in jsonl_text.rstrip("\n").split("\n"):
        if not line:
            continue
        record = json.loads(line)
        rtype = record.get("type")
        if rtype == "run":
            if record.get("variant") == ADAPTIVE.name:
                record["variant"] = FIXED.name
            # An unknown world is a different kind of log; refuse rather than
            # quietly producing a projection nobody can verify.
            get_world(record["world"])
        elif rtype == "loop":
            provenance = record.pop("provenance", None)
            if provenance is not None:
                baseline = provenance["baseline"]
                record["branch_key"] = baseline["branch_key"]
                record["offered_order"] = list(baseline["offered_order"])
                record["reordered"] = baseline["reordered"]
        # The event id is a content hash of the rest of the record, so any
        # mutation above invalidates the stored value; recompute it so the
        # projected line stays self-consistent (and byte-identical to the
        # fixed-baseline arm's line, which is what makes the parity gate
        # mechanical).
        if "event_id" in record:
            record["event_id"] = _event_id_for(record)
        out_lines.append(canonical_dumps(record))
    return "\n".join(out_lines) + "\n"


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


def load_m1_canonical() -> str:
    """The committed JSONL fixture (the expected byte-identical event stream)."""
    return M1_CANONICAL_FIXTURE.read_text(encoding="utf-8")


def write_m1_canonical() -> str:
    """(Re)generate ``fixtures/m1_canonical.jsonl`` from :func:`canonical_run`.

    Run this deliberately (``python -m game.replay --write-m1-fixture``) after
    an intended, reviewed change to the baseline; the committed file is the
    byte-identity gate for the M1 canonical run.
    """
    text = canonical_run().to_jsonl()
    M1_CANONICAL_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    M1_CANONICAL_FIXTURE.write_text(text, encoding="utf-8")
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
    parser.add_argument(
        "--format",
        choices=("json", "jsonl"),
        default="json",
        help="serialization for plain output (default 'json'; 'jsonl' emits the "
        "M1 event-stream form).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="replay the canonical run and verify it matches the golden fixture",
    )
    mode.add_argument(
        "--check-m1",
        action="store_true",
        help="replay the canonical run and verify it matches "
        f"{M1_CANONICAL_FIXTURE.name} (the JSONL event-stream fixture)",
    )
    mode.add_argument(
        "--write-fixture",
        action="store_true",
        help="(re)generate the golden fixture from the canonical run",
    )
    mode.add_argument(
        "--write-m1-fixture",
        action="store_true",
        help=f"(re)generate {M1_CANONICAL_FIXTURE.name} from the canonical run",
    )
    args = parser.parse_args(argv)

    if args.write_fixture:
        write_golden()
        print(f"wrote golden fixture: {GOLDEN_FIXTURE}", file=sys.stderr)
        return 0

    if args.write_m1_fixture:
        write_m1_canonical()
        print(f"wrote M1 canonical fixture: {M1_CANONICAL_FIXTURE}", file=sys.stderr)
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

    if args.check_m1:
        actual = canonical_run().to_jsonl()
        expected = load_m1_canonical()
        if actual == expected:
            print(
                "[PASS] canonical replay is byte-identical to "
                f"{M1_CANONICAL_FIXTURE.name}"
            )
            return 0
        print(
            "[FAIL] canonical replay drifted from "
            f"{M1_CANONICAL_FIXTURE.name}.\n"
            "If this change was intended, regenerate it with "
            "`python -m game.replay --write-m1-fixture`.",
            file=sys.stderr,
        )
        return 1

    result = run(args.seed, _parse_input_log(args.input), variant=args.variant)
    sys.stdout.write(result.to_jsonl() if args.format == "jsonl" else result.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
