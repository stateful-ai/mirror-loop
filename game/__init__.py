"""Mirror Loop — the playable prototype: deterministic core loop + handcrafted
world + templated adaptations, with no LLM.

This package is the runnable game layer that sits on top of the locked core loop
(``loop.core``) and feeds the locked acceptance gate (``acceptance.predictability``):

* :mod:`game.world` — the hand-authored, branching lab the Mirror reveals from
  the player model,
* :mod:`game.templates` — the Mirror's templated, escalating system voice,
* :mod:`game.variants` — the single adaptation seam, so the same engine plays the
  adaptive game or a non-adaptive baseline for A/B feel-testing,
* :mod:`game.session` — the runner that plays a full 3–5-loop session.

Play it with ``python -m game`` (interactive), ``python -m game --demo``
(a scripted persona), or ``python -m game --variant fixed`` (a baseline arm).
Nothing here makes a network call or loads a model.
"""

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

__all__ = [
    "ADAPTIVE",
    "DEFAULT_WORLD",
    "FIXED",
    "LoopRecord",
    "PERSONAS",
    "Session",
    "VARIANT_NAMES",
    "Variant",
    "World",
    "build_variant",
    "live_feedback",
    "persona_policy",
    "play_session",
    "random_variant",
    "report_block",
    "scripted_policy",
    "transcript",
]
