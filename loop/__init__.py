"""Mirror Loop — the core turn loop, the single adaptation type, and the
Reflection/legibility beat, as a runnable specification.

See ``docs/CORE_LOOP.md`` for the prose spec this module operationalizes. Like
``acceptance/predictability.py`` enforces the *thesis*, this package pins down
the *loop*: it is the single executable source of truth for what one turn does
(``scene -> choices -> state update -> visible "Mirror noticed..." reason``) and
for the one adaptation the prototype ships with.
"""

from .core import (
    NOTICE_THRESHOLD,
    Choice,
    Mirror,
    PlayerState,
    Reflection,
    Scene,
    StepResult,
    Turn,
)

__all__ = [
    "NOTICE_THRESHOLD",
    "Choice",
    "Mirror",
    "PlayerState",
    "Reflection",
    "Scene",
    "StepResult",
    "Turn",
]
