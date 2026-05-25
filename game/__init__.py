"""Mirror Loop — the playable prototype: deterministic core loop + handcrafted
world + templated adaptations, with no LLM.

This package is the runnable game layer that sits on top of the locked core loop
(``loop.core``) and feeds the locked acceptance gate (``acceptance.predictability``):

* :mod:`game.world` — the hand-authored, branching lab the Mirror reveals from
  the player model,
* :mod:`game.templates` — the Mirror's templated, escalating system voice,
* :mod:`game.session` — the runner that plays a full 3–5-loop session.

Play it with ``python -m game`` (interactive) or ``python -m game --demo``
(a scripted persona). Nothing here makes a network call or loads a model.
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
from .world import DEFAULT_WORLD, World

__all__ = [
    "DEFAULT_WORLD",
    "LoopRecord",
    "PERSONAS",
    "Session",
    "World",
    "live_feedback",
    "persona_policy",
    "play_session",
    "report_block",
    "scripted_policy",
    "transcript",
]
