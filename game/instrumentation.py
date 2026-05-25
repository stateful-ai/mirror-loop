"""Instrumentation & replay logging — the seed-anchored session trace.

``game/replay.py`` proves the *baseline* arm is byte-identical under a seed: it
serialises a whole run to one canonical snapshot and diffs it against a golden
fixture. This module is the complementary instrument for the **adaptive** arm —
the real game — and answers three operational questions the snapshot alone does
not:

* **What happened, event by event?** A :class:`SessionTrace` is an ordered,
  seed-anchored log of every loop: the **input** the player gave, the **Mirror
  transition** it caused (the player-model read before and after, plus the ranked
  forecast the Mirror made), and every **adaptation that fired** (the
  player-model-driven content decisions, as the audited
  :class:`~game.adaptation.Adaptation` records, provenance included).
* **Where is the Reflection beat?** The legibility beat — the visible "Mirror
  noticed…" moment (``docs/CORE_LOOP.md`` §3) — is recorded on the loop it fires,
  so it is locatable straight from the log
  (:meth:`SessionTrace.reflection_beats`) without re-running the engine.
* **Is the run reproducible?** :meth:`SessionTrace.state_hash` is a stable digest
  of the resulting state; the same ``(seed, input log)`` hashes identically across
  any number of runs and processes (pinned in ``test_instrumentation.py``), and a
  recorded trace :meth:`~SessionTrace.replay` reproduces itself exactly.

**No forked code path.** The trace is built by *observing* the ordinary engine:
:func:`record_session` drives :func:`game.replay.run` (which drives
:func:`game.session.play_session`), then reads back the per-loop records. Each
fired adaptation is produced by the single authoritative producer,
:func:`game.adapt.adapt_slot`, threaded with the exact player-model snapshot the
loop saw, and pinned to match the engine's per-loop content (``_assert_matches_engine``)
so the log can never silently drift from what was played.

**Adaptations vs. the Reflection beat.** Only the adaptive arm bends content to
the player, so fired adaptations are logged only there; under a baseline the
adaptation log is empty by construction. The Reflection beat, by contrast, is a
*render* of the player model (a reduction over logged behaviour), not an
adaptation (``game/variants.py``), so it is logged in every arm — keeping the
A/B shell identical while the adaptation seam is the only thing that differs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from typing import Sequence

from loop.core import PlayerState

from .adapt import AdaptedSlot, adapt_slot
from .adaptation import Adaptation, AdaptationLog, MirrorSnapshot
from .replay import CANONICAL_INPUT_LOG, DEFAULT_SEED, RunResult
from .replay import run as _run
from .session import LoopRecord
from .variants import ADAPTIVE, VARIANT_NAMES
from .world import DEFAULT_WORLD, World

#: Bump when the serialized trace shape changes incompatibly, so a stale, on-disk
#: trace fails loudly at load instead of being mis-read against a newer schema.
SCHEMA_VERSION = 1

#: The hash algorithm behind :func:`state_hash`. Named once so the digest is
#: self-describing and a future migration is a single edit.
_HASH_ALGORITHM = "sha256"


# --- The logged primitives ----------------------------------------------------


@dataclass(frozen=True)
class MirrorTransition:
    """The Mirror's state change across one loop.

    ``before``/``after`` are the player-model reads taken either side of the
    player's input (:class:`~game.adaptation.MirrorSnapshot`); ``predicted_actions``
    is the ranked forecast the Mirror made *before* the choice — exactly what the
    acceptance gate scores. Together they are the full record of one transition:
    the read the Mirror held, the forecast it staked on it, and the read it held
    after the input landed.
    """

    before: MirrorSnapshot
    after: MirrorSnapshot
    predicted_actions: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "predicted_actions": list(self.predicted_actions),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MirrorTransition":
        return cls(
            before=MirrorSnapshot.from_dict(data["before"]),
            after=MirrorSnapshot.from_dict(data["after"]),
            predicted_actions=tuple(data["predicted_actions"]),
        )


@dataclass(frozen=True)
class LoopTrace:
    """Everything one loop logged: the input, the transition, what fired.

    This is the unit of the log. ``input`` is the player's choice id (the input
    recorded against the seed); ``transition`` is the Mirror state change it
    caused; ``adaptations`` are the content decisions that fired this loop (empty
    unless the arm bent content to the player); ``reflection`` is the rendered
    "Mirror noticed…" line if the legibility beat fired on this loop, else
    ``None`` — which is what makes the beat locatable straight from the log.
    """

    loop_index: int
    scene_id: str
    input: str
    transition: MirrorTransition
    adaptations: tuple[Adaptation, ...]
    reflection: str | None

    @property
    def fired_adaptation(self) -> bool:
        """True if any adaptation fired this loop."""
        return bool(self.adaptations)

    @property
    def reflected(self) -> bool:
        """True if the Reflection beat fired this loop."""
        return self.reflection is not None

    @property
    def predicted_hit(self) -> bool:
        """True if the Mirror's top forecast matched the input the player gave."""
        return bool(self.transition.predicted_actions) and (
            self.transition.predicted_actions[0] == self.input
        )

    def to_dict(self) -> dict:
        return {
            "loop_index": self.loop_index,
            "scene_id": self.scene_id,
            "input": self.input,
            "transition": self.transition.to_dict(),
            "adaptations": [a.to_dict() for a in self.adaptations],
            "reflection": self.reflection,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LoopTrace":
        return cls(
            loop_index=data["loop_index"],
            scene_id=data["scene_id"],
            input=data["input"],
            transition=MirrorTransition.from_dict(data["transition"]),
            adaptations=tuple(
                Adaptation.from_dict(a) for a in data.get("adaptations", [])
            ),
            reflection=data.get("reflection"),
        )


@dataclass(frozen=True)
class SessionTrace:
    """A full session as an ordered, seed-anchored log.

    The header (``seed``/``variant``/``world_name``/``input_log``) is the complete
    set of inputs that determined the run, so a trace replays itself
    (:meth:`replay`) and a reader can see exactly what produced it. ``loops`` is
    the per-loop log; ``final_state`` and ``announced`` are the resulting player
    model. Every field is plain, deterministic data — :meth:`state_hash` digests
    it and two runs of the same ``(seed, input log)`` digest identically.
    """

    seed: int
    variant: str
    world_name: str
    input_log: tuple[str, ...]
    loops: tuple[LoopTrace, ...]
    final_state: MirrorSnapshot
    announced: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    # --- locating moments in the log -----------------------------------------

    def reflection_beats(self) -> list[LoopTrace]:
        """Every loop on which the Reflection beat fired, in order.

        This is the "the Reflection-beat moment is locatable from logs" contract:
        each returned :class:`LoopTrace` carries the ``loop_index``, ``scene_id``,
        and rendered line of a beat, recovered from the log with no engine replay.
        """
        return [loop for loop in self.loops if loop.reflected]

    def first_reflection_beat(self) -> LoopTrace | None:
        """The first loop the Reflection beat fired on, or ``None`` if it never did."""
        beats = self.reflection_beats()
        return beats[0] if beats else None

    def adaptation_log(self) -> AdaptationLog:
        """Every fired adaptation across the session, in loop order, as one log.

        The audited "log of what the Mirror did" (``game/adaptation.py``),
        recovered from the trace — empty under a baseline arm, which never adapts.
        """
        log = AdaptationLog()
        for loop in self.loops:
            log = log.append(*loop.adaptations)
        return log

    # --- the determinism digest ----------------------------------------------

    def state_payload(self) -> dict:
        """The resulting-state portion of the trace (no input header).

        :meth:`state_hash` digests exactly this, so the hash is a pure function of
        the state the run *produced*, independent of how the header echoes the
        inputs back.
        """
        return {
            "loops": [loop.to_dict() for loop in self.loops],
            "final_state": self._final_state_dict(),
        }

    def state_hash(self) -> str:
        """A stable digest of the resulting state — the determinism fingerprint."""
        return state_hash(self.state_payload())

    # --- replay ---------------------------------------------------------------

    def replay(self, *, world: World = DEFAULT_WORLD) -> "SessionTrace":
        """Re-run from this trace's own ``(seed, input log)`` header.

        Returns a freshly recorded trace which, because the engine is
        deterministic, equals ``self``. ``world`` must be the one the trace was
        recorded against (matched by name) so a trace cannot be silently replayed
        against a different spine.
        """
        if world.name != self.world_name:
            raise ValueError(
                f"trace was recorded against world {self.world_name!r}, not "
                f"{world.name!r}; cannot replay across worlds"
            )
        return record_session(
            self.input_log, seed=self.seed, variant=self.variant, world=world
        )

    # --- (de)serialization ----------------------------------------------------

    def _final_state_dict(self) -> dict:
        return {
            "tendency_counts": [list(pair) for pair in self.final_state.tendency_counts],
            "dominant": self.final_state.dominant,
            "turn_count": self.final_state.turn_count,
            "announced": list(self.announced),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run": {
                "seed": self.seed,
                "variant": self.variant,
                "world": self.world_name,
                "input_log": list(self.input_log),
            },
            "loops": [loop.to_dict() for loop in self.loops],
            "final_state": self._final_state_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionTrace":
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported trace schema version {version!r} "
                f"(this build reads v{SCHEMA_VERSION})"
            )
        run_block = data["run"]
        fs = data["final_state"]
        final_state = MirrorSnapshot(
            turn_count=fs["turn_count"],
            tendency_counts=tuple(
                (name, count) for name, count in fs.get("tendency_counts", [])
            ),
            dominant=fs.get("dominant"),
        )
        return cls(
            seed=run_block["seed"],
            variant=run_block["variant"],
            world_name=run_block["world"],
            input_log=tuple(run_block["input_log"]),
            loops=tuple(LoopTrace.from_dict(loop) for loop in data["loops"]),
            final_state=final_state,
            announced=tuple(fs.get("announced", [])),
            schema_version=version,
        )

    def to_json(self) -> str:
        """Serialize to canonical JSON — sorted keys, stable indentation, newline."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "SessionTrace":
        """Rebuild a trace from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text))


# --- the digest function ------------------------------------------------------


def state_hash(payload: dict) -> str:
    """A deterministic content hash of ``payload``.

    The payload is canonicalised (sorted keys, no incidental whitespace) before
    hashing, so the digest depends only on the *values*, never on dict ordering or
    formatting. The algorithm name is prefixed so the digest is self-describing.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{_HASH_ALGORITHM}:{hashlib.sha256(blob).hexdigest()}"


# --- building a trace by observing the engine ---------------------------------


def record_session(
    input_log: Sequence[str],
    *,
    seed: int = DEFAULT_SEED,
    variant: str = ADAPTIVE.name,
    world: World = DEFAULT_WORLD,
) -> SessionTrace:
    """Play one session from ``(seed, input_log)`` and return its trace.

    Drives the ordinary engine through :func:`game.replay.run` (never a fork) and
    instruments the result: every input, every Mirror transition, every fired
    adaptation, and the Reflection beat where it fires. ``variant`` defaults to
    the real adaptive game; a baseline arm records the same shape with an empty
    adaptation log (a baseline does not adapt to the player). ``seed`` is recorded
    in the header for the uniform ``(seed, input log)`` contract — it fixes the
    placebo arm's player-independent variation and is inert for the adaptive arm,
    whose content is a pure function of the player model.

    Raises ``ValueError`` (via :func:`game.replay.run`) if ``input_log`` does not
    have exactly one choice per slot of ``world``.
    """
    result = _run(seed, input_log, variant=variant, world=world)
    return _trace_from_run(result, world)


def canonical_trace() -> SessionTrace:
    """The canonical adaptive run: a consistent kind player on the default world.

    The one a CLI prints by default and the determinism test pins. It exercises
    every primitive — branch selections, an in-scene re-ordering, and the
    Reflection beat — because the kind player crosses the notice threshold.
    """
    return record_session(CANONICAL_INPUT_LOG)


def _trace_from_run(result: RunResult, world: World) -> SessionTrace:
    """Instrument a completed :class:`~game.replay.RunResult` into a trace."""
    adaptive = result.variant == ADAPTIVE.name
    loops: list[LoopTrace] = []
    # The state the *next* loop's adaptation reads is the previous loop's result
    # state; loop 0 reads the blank mirror. Threading it here is what lets each
    # adaptation carry the snapshot it was actually a function of.
    before = PlayerState()
    for slot, record in zip(world.slots, result.session.records):
        res = record.result
        adaptations: tuple[Adaptation, ...] = ()
        if adaptive:
            # Reuse the one authoritative producer, then pin it to what the engine
            # actually presented so the log can't drift from the played session.
            adapted = adapt_slot(slot, before)
            _assert_matches_engine(adapted, record)
            adaptations = adapted.adaptations
        loops.append(
            LoopTrace(
                loop_index=record.loop_index,
                scene_id=record.offered.id,
                input=res.actual_action,
                transition=MirrorTransition(
                    before=MirrorSnapshot.from_player_state(before),
                    after=MirrorSnapshot.from_player_state(res.state),
                    predicted_actions=tuple(res.predicted_actions),
                ),
                adaptations=adaptations,
                reflection=res.reflection.render() if res.reflection else None,
            )
        )
        before = res.state

    final_state = result.session.final_state
    return SessionTrace(
        seed=result.seed,
        variant=result.variant,
        world_name=result.world_name,
        input_log=tuple(result.input_log),
        loops=tuple(loops),
        final_state=MirrorSnapshot.from_player_state(final_state),
        announced=tuple(sorted(final_state.announced)),
    )


def _assert_matches_engine(adapted: AdaptedSlot, record: LoopRecord) -> None:
    """Fail loudly if the trace's adaptation producer disagrees with the engine.

    The fired-adaptation records come from :func:`game.adapt.adapt_slot`, the
    in-scene re-ordering and branch selection from
    :func:`game.session.play_session`. For the adaptive arm the two must present
    byte-for-byte the same content every loop; if they ever diverge the log would
    silently misreport what was played, so this raises instead.
    """
    if (
        adapted.branch_key != record.branch_key
        or [c.id for c in adapted.declared.choices]
        != [c.id for c in record.declared.choices]
        or [c.id for c in adapted.offered.choices]
        != [c.id for c in record.offered.choices]
    ):
        raise RuntimeError(
            "instrumentation drifted from the engine: game.adapt.adapt_slot and "
            f"game.session.play_session disagree on slot {record.declared.id!r}"
        )


# --- CLI ----------------------------------------------------------------------


def _parse_input_log(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return CANONICAL_INPUT_LOG
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _format_reflection_locations(trace: SessionTrace) -> str:
    beats = trace.reflection_beats()
    if not beats:
        return "(no Reflection beat fired in this session)"
    lines = []
    for beat in beats:
        lines.append(f"loop {beat.loop_index + 1} [{beat.scene_id}]:")
        for ln in (beat.reflection or "").splitlines():
            lines.append(f"  {ln}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m game.instrumentation", description=__doc__
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"run seed (default {DEFAULT_SEED}; fixes any non-player variation)",
    )
    parser.add_argument(
        "--variant",
        choices=VARIANT_NAMES,
        default=ADAPTIVE.name,
        help=f"the arm to trace (default {ADAPTIVE.name!r}, the real game)",
    )
    parser.add_argument(
        "--input",
        metavar="ID,ID,...",
        default=None,
        help="comma-separated choice-id input log (default: the canonical kind log)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--state-hash",
        action="store_true",
        help="print only the deterministic state hash of the run",
    )
    mode.add_argument(
        "--locate-reflection",
        action="store_true",
        help="print where the Reflection beat fired, located from the log",
    )
    args = parser.parse_args(argv)

    trace = record_session(
        _parse_input_log(args.input), seed=args.seed, variant=args.variant
    )

    if args.state_hash:
        print(trace.state_hash())
        return 0
    if args.locate_reflection:
        print(_format_reflection_locations(trace))
        return 0

    sys.stdout.write(trace.to_json())
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())


__all__ = [
    "LoopTrace",
    "MirrorTransition",
    "SCHEMA_VERSION",
    "SessionTrace",
    "canonical_trace",
    "record_session",
    "state_hash",
]
