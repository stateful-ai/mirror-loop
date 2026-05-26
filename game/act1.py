"""The Act 1 scene graph — a single-branch linear spine, authored as data.

This is the M1 "Act 1 scene graph (~12-16 scenes, single branch) authored
against frozen schemas" deliverable (``docs/mirror_loop_m1_synthesis.md``
Phase B2). It is **not** the v0 prototype world in :mod:`game.world` (which is
a five-slot, multi-variant spine the 3-5-loop session bound was tuned for);
it is the longer, fully linear spine the M1 north-star runs against:

    Lab Intake -> Act 1 beats -> Recalibration -> Act 2 entry.

Three contracts are honoured here, none of them re-defined locally:

* **Authoring format** — every scene lives as a ``.scene`` text file under
  ``game/scenes/data/act1/`` and is parsed by the frozen loader in
  :mod:`game.scenes` (``docs/SCENE_FORMAT.md``). The loader is the only path
  from disk to ``Scene``; the spine is *just* an ordered list of those scenes.
* **Frozen ``WorldState``** — the spine is a :class:`~game.world.World` of
  fixed-scene slots, so a session's input log reduces under
  :meth:`game.worldstate.WorldState.reduce` exactly as the v0 world does. The
  WorldState schema is not touched.
* **Single adaptation type, single axis** — every choice still carries one of
  the v0 tendencies (``kindness`` / ``control`` / ``defiance``;
  ``docs/ADAPTATION.md`` §2), so the in-scene re-ordering surface of tendency
  mirroring (``loop.core.Mirror.adapt``) runs without change. The spine
  varies declared choice order across scenes on purpose: a dominant-tendency
  player visibly experiences the Mirror lifting their predicted option to the
  top in several scenes — the "exercises the mirror axis" acceptance.

"Single branch" means the spine is linear: every slot holds exactly one
authored scene (no across-scene framing variants in :class:`~game.world.Slot`).
The only adaptation surface in Act 1 is the in-scene re-ordering; the
across-scene branch-selection surface is intentionally not engaged here.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Callable, Sequence

from loop.core import Mirror, PlayerState, Scene

from .scenes import load_scene
from .session import LoopRecord, Policy, Session, offer_scene, record_loop
from .variants import ADAPTIVE, Variant
from .world import Slot, World

#: The Act 1 spine sits in [12, 16] loops per the synthesis brief. The bound is
#: asserted at world-build time so an accidental scene drop/duplicate during
#: authoring fails loudly instead of shipping an out-of-range spine.
ACT1_MIN_LOOPS = 12
ACT1_MAX_LOOPS = 16

#: Name registered on the built :class:`~game.world.World`.
ACT1_WORLD_NAME = "act1-mirror-lab"

#: Canonical seed for the Act 1 deterministic walk (matches the M1 byte-identity
#: gate seed in :data:`game.replay.DEFAULT_SEED`).
DEFAULT_SEED = 42

#: The tendencies the seeded policy draws from. Order is fixed so the policy's
#: RNG draws stay byte-identical across processes regardless of dict ordering.
_TENDENCIES: tuple[str, ...] = ("kindness", "control", "defiance")

#: Directory holding the Act 1 ``.scene`` source files. The spine is the files
#: sorted by name, which — because every file is prefixed with a two-digit
#: ordinal — gives the authored walk order: 01_intake ... 14_act2_entry.
ACT1_DATA_DIR: Path = Path(__file__).resolve().parent / "scenes" / "data" / "act1"

#: Filename prefix every Act 1 scene file carries. Used to detect drift if a
#: file slips into the directory under another name.
_FILE_PREFIX = "act1_"


def _act1_scene_paths() -> list[Path]:
    """Return the Act 1 ``.scene`` files in spine order.

    Sorted by filename so the spine is a pure function of the directory's
    contents — no in-code list to drift out of sync with what was authored.
    """
    paths = sorted(ACT1_DATA_DIR.glob("*.scene"))
    for path in paths:
        if not path.name.startswith(_FILE_PREFIX):
            raise ValueError(
                f"unexpected scene file in {ACT1_DATA_DIR}: {path.name!r} "
                f"(every Act 1 scene file must be prefixed {_FILE_PREFIX!r})"
            )
    return paths


def load_act1_scenes() -> tuple[Scene, ...]:
    """Load every Act 1 ``.scene`` file in spine order, deterministically.

    Each file is parsed by the frozen loader (:func:`game.scenes.load_scene`);
    any malformed scene raises :class:`~game.scenes.SceneFormatError` with the
    offending line number. The returned tuple is the authored spine, in order.
    """
    return tuple(load_scene(path) for path in _act1_scene_paths())


def load_act1_world() -> World:
    """Build the Act 1 spine as a :class:`~game.world.World` of fixed slots.

    Every slot wraps exactly one authored scene — no across-scene variants, so
    the spine is *single-branch* (linear). The slot key equals the scene id, so
    a recorded :class:`~mirror.log.ChoiceObserved` whose ``scene_id`` is the
    scene id matches its slot under :meth:`game.worldstate.WorldState.reduce`
    without a translation table.

    Raises :class:`ValueError` if the spine lands outside
    ``[ACT1_MIN_LOOPS, ACT1_MAX_LOOPS]`` (an authored drift safeguard), if two
    scenes share an id, or if a file's name disagrees with the scene id it
    declares.
    """
    paths = _act1_scene_paths()
    scenes = [load_scene(path) for path in paths]
    seen: set[str] = set()
    slots: list[Slot] = []
    for path, scene in zip(paths, scenes):
        if path.stem != scene.id:
            raise ValueError(
                f"scene id {scene.id!r} disagrees with filename {path.name!r}: "
                "every Act 1 scene file must be named <scene_id>.scene so the "
                "spine order from filename sort matches the authored ids"
            )
        if scene.id in seen:
            raise ValueError(
                f"duplicate scene id {scene.id!r} in Act 1 spine"
            )
        seen.add(scene.id)
        slots.append(Slot(key=scene.id, fixed=scene))
    if not (ACT1_MIN_LOOPS <= len(slots) <= ACT1_MAX_LOOPS):
        raise ValueError(
            f"Act 1 spine has {len(slots)} scenes; the M1 target is "
            f"{ACT1_MIN_LOOPS}-{ACT1_MAX_LOOPS} per "
            "docs/mirror_loop_m1_synthesis.md"
        )
    return World(name=ACT1_WORLD_NAME, slots=tuple(slots))


def seeded_policy(seed: int = DEFAULT_SEED) -> Policy:
    """A deterministic policy: each loop, draw a tendency with ``Random(seed)``.

    Picks among ``_TENDENCIES`` with the standard-library ``random.Random``
    (forbidden modules / unsynced randomness are caught by the runtime AST scan
    in ``game/tests/test_replay.py`` — only ``random.Random(seed)`` is allowed).
    The same seed yields the same input log byte-for-byte across processes and
    Python hash seeds, which is what makes the M1 byte-identity gate honest.

    The RNG is created fresh per call to :func:`seeded_policy`, so two
    independent ``seeded_policy(42)`` instances produce identical sequences;
    one instance's draws advance across loops in declared order.
    """
    rng = random.Random(seed)

    def pick(scene: Scene, state: PlayerState, loop_index: int) -> str:
        target = rng.choice(_TENDENCIES)
        for choice in scene.choices:
            if choice.tendency == target:
                return choice.id
        # The Act 1 spine guarantees every scene tags one choice per tendency
        # (asserted in test_act1.py), so the fall-through is unreachable in
        # practice. We still return a real choice rather than raise so a
        # future scene that drops a tendency degrades to "play the first
        # choice" instead of crashing mid-walk.
        return scene.choices[0].id

    return pick


def play_act1(
    policy: Policy | None = None,
    *,
    world: World | None = None,
    mirror: Mirror | None = None,
    variant: Variant = ADAPTIVE,
    on_loop: Callable[[LoopRecord], None] | None = None,
) -> Session:
    """Walk the Act 1 spine once under ``policy`` and return the session.

    A parallel runner to :func:`game.session.play_session`: it shares the same
    per-loop building blocks (:func:`~game.session.offer_scene` and
    :func:`~game.session.record_loop`), so the *engine* — predict, adapt,
    record, reflect — is identical. The only thing this runner does
    differently is its loop-count bound: Act 1's spine is
    :data:`ACT1_MIN_LOOPS`-:data:`ACT1_MAX_LOOPS` loops (not the v0 prototype's
    3-5), and ``play_session`` would reject it on length.

    The default ``policy`` is the seeded :func:`seeded_policy`, so the bare
    ``play_act1()`` call is the deterministic seed-42 reference walk the M1
    north-star quotes.
    """
    if policy is None:
        policy = seeded_policy(DEFAULT_SEED)
    if world is None:
        world = load_act1_world()
    if not (ACT1_MIN_LOOPS <= world.length <= ACT1_MAX_LOOPS):
        raise ValueError(
            f"Act 1 runner requires a world with {ACT1_MIN_LOOPS}-"
            f"{ACT1_MAX_LOOPS} loops; {world.name!r} has {world.length}"
        )

    mirror = mirror or Mirror()
    state = PlayerState()
    records: list[LoopRecord] = []
    for i, slot in enumerate(world.slots):
        declared, offered, branch_key = offer_scene(variant, mirror, state, slot)
        choice_id = policy(offered, state, i)
        record = record_loop(
            mirror,
            state,
            declared,
            offered,
            branch_key,
            choice_id,
            loop_index=i,
            is_finale=(i == world.length - 1),
        )
        records.append(record)
        if on_loop is not None:
            on_loop(record)
        state = record.result.state

    return Session(
        records=tuple(records),
        final_state=state,
        world_name=world.name,
        variant_name=variant.name,
    )


def seeded_input_log(seed: int = DEFAULT_SEED) -> tuple[str, ...]:
    """The exact input log :func:`seeded_policy` produces against the Act 1 spine.

    Convenience for tests and tooling that want the seeded walk's choice ids
    without driving a full session through the engine. The result is one
    choice id per slot, in spine order.
    """
    world = load_act1_world()
    policy = seeded_policy(seed)
    state = PlayerState()
    mirror = Mirror()
    log: list[str] = []
    for i, slot in enumerate(world.slots):
        _declared, offered, _branch_key = offer_scene(ADAPTIVE, mirror, state, slot)
        choice_id = policy(offered, state, i)
        log.append(choice_id)
        # Advance the engine the same way play_act1 does, so the offered scene
        # the policy sees on the next loop reflects every prior choice — without
        # this fold the seeded log would drift from a real run.
        record = record_loop(
            mirror,
            state,
            _declared,
            offered,
            _branch_key,
            choice_id,
            loop_index=i,
            is_finale=(i == world.length - 1),
        )
        state = record.result.state
    return tuple(log)


#: First and last slot keys of the Act 1 spine, fixed by the brief
#: (Lab Intake -> ... -> Act 2 entry). Importable so the test that pins the
#: endpoints does not duplicate the magic strings.
ACT1_START_SLOT = "act1_01_intake"
ACT1_END_SLOT = "act1_14_act2_entry"
ACT1_RECALIBRATION_SLOT = "act1_13_recalibration"
