"""Mirror Loop — the playable prototype: deterministic core loop + handcrafted
world + templated adaptations, with no LLM.

This package is the runnable game layer that sits on top of the locked core loop
(``loop.core``) and feeds the locked acceptance gate (``acceptance.predictability``):

* :mod:`game.world` — the hand-authored, branching lab the Mirror reveals from
  the player model,
* :mod:`game.worldstate` — the player's position in that world, as a pure
  reduction over the event log,
* :mod:`game.adaptation` — the versioned record of one content decision, with the
  trigger Mirror snapshot and source event-seq that make it auditable,
* :mod:`game.adapt` — the templated, toggleable adaptation layer that presents a
  world under a player-model read and emits those records, invariant-checked,
* :mod:`game.templates` — the Mirror's templated, escalating system voice,
* :mod:`game.variants` — the single adaptation seam, so the same engine plays the
  adaptive game or a non-adaptive baseline for A/B feel-testing,
* :mod:`game.session` — the runner that plays a full 3–5-loop session,
* :mod:`game.replay` — the deterministic, seeded replay of the baseline arm: a
  session runs end-to-end from a ``(seed, input log)`` pair and serializes to a
  canonical state that reproduces byte-for-byte (the byte-identity gate),
* :mod:`game.instrumentation` — the seed-anchored replay log of the *adaptive*
  run: every input, Mirror transition, and fired adaptation, with the Reflection
  beat locatable from the log and a deterministic state hash pinned across runs.

Play it with ``python -m game`` (interactive), ``python -m game --demo``
(a scripted persona), or ``python -m game --variant fixed`` (a baseline arm).
Replay the seeded baseline with ``python -m game.replay``, or trace and locate
the adaptive run's events with ``python -m game.instrumentation``. Nothing here
makes a network call or loads a model.
"""

from .adapt import AdaptedSlot, AdaptedWorld, adapt, adapt_slot
from .adaptation import (
    ADAPTATION_SCHEMA_VERSION,
    Adaptation,
    AdaptationKind,
    AdaptationLog,
    AdaptationProvenance,
    MirrorSnapshot,
)
from .session import (
    PERSONAS,
    LoopRecord,
    Session,
    live_feedback,
    persona_policy,
    play_session,
    report_block,
    scripted_policy,
    transcript,
)
from .variants import (
    ADAPTIVE,
    FIXED,
    VARIANT_NAMES,
    Variant,
    build_variant,
    random_variant,
)
from .world import DEFAULT_WORLD, World
from .worldstate import WORLDSTATE_SCHEMA_VERSION, VisitedSlot, WorldState

__all__ = [
    "ADAPTATION_SCHEMA_VERSION",
    "ADAPTIVE",
    "Adaptation",
    "AdaptationKind",
    "AdaptationLog",
    "AdaptationProvenance",
    "AdaptedSlot",
    "AdaptedWorld",
    "DEFAULT_WORLD",
    "FIXED",
    "LoopRecord",
    "MirrorSnapshot",
    "PERSONAS",
    "Session",
    "VARIANT_NAMES",
    "Variant",
    "VisitedSlot",
    "WORLDSTATE_SCHEMA_VERSION",
    "World",
    "WorldState",
    "adapt",
    "adapt_slot",
    "build_variant",
    "live_feedback",
    "persona_policy",
    "play_session",
    "random_variant",
    "report_block",
    "scripted_policy",
    "transcript",
]
