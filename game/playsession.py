"""Within-session persistence: a resumable walk of the handcrafted world spine.

The one-shot runner (:func:`game.session.play_session`) plays a whole session in
a single call — fine to *run* a session, but it owns no state a player can pause,
save, and come back to. :class:`PlaySession` is that owner. It walks the world
**one loop at a time**, accumulating the Mirror's player model *and* the player's
position in the spine, and it serializes to JSON / disk so a session saved after
loop *n* resumes — even in another process — with loops *1..n* intact.

**What persists, and why it is the log and not the deltas.** The locked
architecture (company memory; ``docs/SCHEMAS.md`` §0, ``docs/MIRROR_SCHEMA.md``
§6) is that *the append-only log is the only source of truth, and both the Mirror
and the world-state are pure reductions over it — derived state is never the
authority.* So a saved :class:`PlaySession` stores only the authoritative inputs:
the world and variant it was played under, the placebo seed, and the **input log**
(the choice id made each loop). On reload it **replays that log** to recompute
everything derived — the running tendency tally, the ``announced`` set, the world
position, and every branch selection / re-ordering the player was shown. This is
the same ``(seed, input log)`` contract :mod:`game.replay` already establishes:
the two fully determine the run, so "save the log, replay it"
(``docs/MIRROR_SCHEMA.md`` §225) reconstructs the session exactly.

Because the adaptation reads *only* from that reduced state, the content a resumed
loop shows — its revealed framing, its adapted choice order, its "Mirror noticed…"
beat — is **provably a function of the loops that came before it**, including loops
played before the save. ``game/tests/test_playsession.py`` pins that down: a
scripted session saved mid-play and resumed shows ≥2 adaptations compounding on
history that only survives because it was persisted, and a control that never
persists shows the same later loop adapting nothing.

**Lost on quit is acceptable for v0.** This is *within*-session persistence:
durability across a save/reload *inside* one play-through. There is no automatic,
durable store behind it — a :class:`PlaySession` held only in memory is gone when
the process exits unless the caller :meth:`save`\\d it. **Cross-session
persistence** (a session that survives quitting the game) is deliberately M2+ and
out of scope here (``docs/mirror_loop_m1_founder_brief.md`` "Out of scope";
``docs/RECONCILIATION.md`` §3 #5, ``docs/PERSISTENCE.md``).
"""

from __future__ import annotations

import json
from pathlib import Path

from loop.core import Mirror, PlayerState, Scene

from .session import (
    MAX_LOOPS,
    MIN_LOOPS,
    LoopRecord,
    Session,
    offer_scene,
    record_loop,
)
from .variants import ADAPTIVE, Variant, build_variant
from .world import DEFAULT_WORLD, Slot, World, get_world

#: Bump on any incompatible change to the persisted session shape. A snapshot
#: stamped with another version is refused at :meth:`PlaySession.from_dict`
#: rather than silently mis-restored (the shared version policy, SCHEMAS.md §5).
SCHEMA_VERSION = 1


class PlaySession:
    """A persistent, resumable play session over a :class:`~game.world.World`.

    Construct one, drive it one loop at a time with :meth:`play` (optionally
    previewing each loop with :meth:`current_offer`), and persist/resume it with
    :meth:`to_json` / :meth:`from_json` (or the disk wrappers). The accumulated
    :class:`~loop.core.PlayerState` and the world position are both recomputed
    from the stored input log, so every adaptation a later loop shows is grounded
    in the loops already recorded here.
    """

    def __init__(
        self,
        *,
        world: World = DEFAULT_WORLD,
        variant: Variant = ADAPTIVE,
        session_id: str = "session",
        mirror: Mirror | None = None,
    ) -> None:
        # The 3–5-loop session target is a property of the world spine, so reject
        # an out-of-range world up front rather than only when the session would
        # complete — a resumable session has no single "end" to defer the check to.
        if not (MIN_LOOPS <= world.length <= MAX_LOOPS):
            raise ValueError(
                f"world {world.name!r} has {world.length} slots; a session must be "
                f"{MIN_LOOPS}-{MAX_LOOPS} loops"
            )
        self.session_id = session_id
        self.world = world
        self.variant = variant
        self.mirror = mirror if mirror is not None else Mirror()
        self.state = PlayerState()
        self.records: list[LoopRecord] = []
        self.input_log: list[str] = []

    # --- position in the spine ----------------------------------------------

    @property
    def position(self) -> int:
        """Loops completed so far = index of the next slot to play.

        Equal to ``state.turn_count`` and to ``len(self.input_log)``; the world
        position is itself a reduction over the accumulated state, never stored
        independently.
        """
        return self.state.turn_count

    @property
    def is_complete(self) -> bool:
        """True once every slot in the world has been played."""
        return self.position >= self.world.length

    def current_slot(self) -> Slot | None:
        """The slot to play next, or ``None`` if the spine is finished."""
        if self.is_complete:
            return None
        return self.world.slots[self.position]

    def current_offer(self) -> tuple[Scene, Scene, str]:
        """The Mirror's offer for the current slot: ``(declared, offered, branch_key)``.

        The read-only preview of the next loop — what the player would be shown
        before choosing — recomputed from the accumulated state, so it reflects
        every loop played (and persisted) so far. Raises ``ValueError`` if the
        session is already complete.
        """
        slot = self.current_slot()
        if slot is None:
            raise ValueError(
                f"session {self.session_id!r} is complete "
                f"({self.world.length} loops); nothing left to offer"
            )
        return offer_scene(self.variant, self.mirror, self.state, slot)

    # --- advancing -----------------------------------------------------------

    def play(self, choice_id: str) -> LoopRecord:
        """Advance the session by exactly one loop and accumulate the result.

        Offers the current slot from the accumulated state (so the framing and
        choice order reflect every prior loop), steps the chosen choice, folds the
        new state back in, and appends to the input log — the persistence step.
        Returns the :class:`~game.session.LoopRecord` the player was shown. Raises
        ``ValueError`` past the end of the spine, so a stale or overrun log fails
        loudly instead of running off the world.
        """
        slot = self.current_slot()
        if slot is None:
            raise ValueError(
                f"session {self.session_id!r} is complete "
                f"({self.world.length} loops); cannot play another loop"
            )
        declared, offered, branch_key = offer_scene(
            self.variant, self.mirror, self.state, slot
        )
        record = record_loop(
            self.mirror,
            self.state,
            declared,
            offered,
            branch_key,
            choice_id,
            loop_index=self.position,
            is_finale=(self.position == self.world.length - 1),
        )
        self.state = record.result.state  # accumulate, don't discard
        self.records.append(record)
        self.input_log.append(choice_id)
        return record

    def completed(self) -> Session:
        """The finished :class:`~game.session.Session`, once every slot is played.

        Produces exactly what :func:`game.session.play_session` returns, so a
        resumed session feeds the transcript, report, and acceptance-gate log with
        no special-casing. Raises ``ValueError`` if the spine is not yet done.
        """
        if not self.is_complete:
            raise ValueError(
                f"session {self.session_id!r} has played {self.position} of "
                f"{self.world.length} loops; not complete"
            )
        return Session(
            records=tuple(self.records),
            final_state=self.state,
            world_name=self.world.name,
            variant_name=self.variant.name,
        )

    # --- persistence ---------------------------------------------------------

    @property
    def _seed(self) -> int:
        """The placebo seed this session's variant carries (0 for non-placebo).

        Only ``random`` varies on the seed; ``adaptive``/``fixed`` ignore it. It
        is stored so the placebo arm round-trips exactly, keeping the saved form a
        complete description of the run.
        """
        return int(getattr(self.variant, "seed", 0))

    def to_dict(self) -> dict:
        """A JSON-serializable snapshot: the authoritative log, nothing derived.

        Stores the run configuration (world name, variant, seed) and the input
        log. The Mirror model, the ``announced`` set, the world position, and
        every adaptation shown are *not* stored — they are recomputed on reload by
        replaying the log, so derived state is never the persisted authority
        (``docs/SCHEMAS.md`` §0).
        """
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "world": self.world.name,
            "variant": self.variant.name,
            "seed": self._seed,
            "input_log": list(self.input_log),
        }

    @classmethod
    def from_dict(cls, data: dict, *, world: World | None = None) -> "PlaySession":
        """Rebuild a session from :meth:`to_dict` output by replaying its log.

        Resolves the world by name from the registry (or verifies a ``world``
        passed explicitly matches the recorded name — handy for tests that play
        an ad-hoc spine), rebuilds the variant, then replays each recorded choice
        so the accumulated state is reduced from the log exactly as it was first
        played. Refuses an unknown schema version up front.
        """
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported session schema version {version!r} "
                f"(this build writes/reads v{SCHEMA_VERSION})"
            )
        world_name = data["world"]
        if world is None:
            world = get_world(world_name)
        elif world.name != world_name:
            raise ValueError(
                f"world mismatch: snapshot was recorded against {world_name!r} but "
                f"{world.name!r} was supplied"
            )
        variant = build_variant(data["variant"], seed=data.get("seed", 0))
        session = cls(world=world, variant=variant, session_id=data["session_id"])
        for choice_id in data["input_log"]:
            session.play(choice_id)  # replay: reduce mirror + world from the log
        return session

    def to_json(self) -> str:
        """Serialize to an indented, key-sorted JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str, *, world: World | None = None) -> "PlaySession":
        """Rebuild a session from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text), world=world)

    def save(self, path: str | Path) -> None:
        """Persist the session to ``path`` as JSON."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, *, world: World | None = None) -> "PlaySession":
        """Resume a session previously written by :meth:`save`."""
        return cls.from_json(Path(path).read_text(encoding="utf-8"), world=world)


# --- A runnable proof that adaptations compound across a save/reload ----------
# The kind player's choice ids, one per slot of DEFAULT_WORLD (the kindness
# option of each slot; identical to game.replay.CANONICAL_INPUT_LOG).
_KIND_LOG = ("c_reassure", "c_close", "c_help", "c_wait", "c_accept")
#: Where the save/reload happens in the demo: after loop 3, before loops 4-5.
_SAVE_AFTER = 3


def demo() -> str:  # pragma: no cover - exercised via the public API in tests
    """Show ≥2 adaptations compounding across a within-session save/reload.

    Plays the first three loops as a consistently kind player, persists the
    session to JSON, resumes it in a brand-new :class:`PlaySession` (a fresh
    :class:`~loop.core.Mirror`, state reduced from the log), then plays loops 4-5
    — and reports the adaptations the resumed loops show, each of which depends on
    the loops 1-3 that only survived because they were persisted.
    """
    live = PlaySession(session_id="demo")
    for choice_id in _KIND_LOG[:_SAVE_AFTER]:
        live.play(choice_id)

    saved = live.to_json()
    resumed = PlaySession.from_json(saved)
    restored = resumed.position

    loop4 = resumed.play(_KIND_LOG[3])  # confrontation — declares kindness LAST
    loop5 = resumed.play(_KIND_LOG[4])  # exit — the tailored reveal

    declared4 = [c.id for c in loop4.declared.choices]
    offered4 = [c.id for c in loop4.offered.choices]
    lines = [
        f"Played loops 1-{_SAVE_AFTER} (a kind player), saved to JSON, resumed in a "
        "fresh session.",
        f"Resumed with {restored} loops of history reduced from the saved log.",
        "",
        "Adaptations the resumed loops show, compounding on the persisted history:",
        f"  loop 4 [{loop4.offered.id}] in-scene re-ordering: "
        f"declared {declared4} -> offered {offered4} "
        f"(kindness lifted to the front; reordered={loop4.reordered})",
        f"  loop 5 [{loop5.offered.id}] branch selection: "
        f"revealed the {loop5.branch_key!r} framing",
    ]
    return "\n".join(lines)


#: The committed golden snapshot of the adaptive arm driven through a save/reload.
#: ``game/tests/test_playsession.py`` replays against it so a code change that
#: silently altered what a resumed loop shows fails loudly. Regenerate with
#: ``python -m game.playsession --write-golden`` after an intended, reviewed change.
GOLDEN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "adaptive_kind_resumed.json"


def _resumed_golden_snapshot() -> str:
    """Serialize the adaptive ``_KIND_LOG`` run, driven through a real save/reload.

    Uses :class:`game.replay.RunResult` — the same determinism-audited serializer
    the baseline byte-identity gate uses — so the golden is in the canonical
    snapshot form (sorted keys, no clock/PID/RNG).
    """
    from .replay import RunResult  # local import: avoid a package import cycle

    live = PlaySession()
    for choice_id in _KIND_LOG[:_SAVE_AFTER]:
        live.play(choice_id)
    resumed = PlaySession.from_json(live.to_json())
    for choice_id in _KIND_LOG[_SAVE_AFTER:]:
        resumed.play(choice_id)
    return RunResult(
        seed=0,  # adaptive ignores the seed; the input log fully determines the run
        variant=ADAPTIVE.name,
        world_name=DEFAULT_WORLD.name,
        input_log=_KIND_LOG,
        session=resumed.completed(),
    ).to_json()


def write_golden() -> str:
    """(Re)generate the adaptive persistence golden fixture; return its JSON."""
    text = _resumed_golden_snapshot()
    GOLDEN_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FIXTURE.write_text(text, encoding="utf-8")
    return text


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI wrapper
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="python -m game.playsession")
    parser.add_argument(
        "--write-golden",
        action="store_true",
        help="(re)generate the adaptive save/reload golden fixture the tests pin",
    )
    args = parser.parse_args(argv)
    if args.write_golden:
        write_golden()
        print(f"wrote golden fixture: {GOLDEN_FIXTURE}", file=sys.stderr)
        return 0
    print(demo())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
