"""The "mirror" player-state: the typed, anti-mush model of the player.

Public API:

- Schema:  ``MIRROR_SCHEMA``, ``AttributeSpec``, ``AttributeKind``, ``Dynamics``,
  ``SEED_FEATURE_MAP``, ``coherence_report``, ``assert_coherent``.
- Runtime: ``MirrorState``, ``Choice``, ``Signal``, ``AttributeReading``.

See ``docs/MIRROR_SCHEMA.md`` for the schema spec and the anti-mush review.
"""

from __future__ import annotations

from mirror.schema import (
    MIRROR_SCHEMA,
    SEED_FEATURE_MAP,
    AttributeKind,
    AttributeSpec,
    CoherenceReport,
    Dynamics,
    assert_coherent,
    coherence_report,
    value_range,
)
from mirror.state import (
    AttributeReading,
    Choice,
    MirrorState,
    Signal,
)

__all__ = [
    "MIRROR_SCHEMA",
    "SEED_FEATURE_MAP",
    "AttributeKind",
    "AttributeSpec",
    "CoherenceReport",
    "Dynamics",
    "assert_coherent",
    "coherence_report",
    "value_range",
    "AttributeReading",
    "Choice",
    "MirrorState",
    "Signal",
]
