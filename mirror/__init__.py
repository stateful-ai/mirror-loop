"""The "mirror" player-state: the typed, anti-mush model of the player.

Public API:

- Schema:  ``MIRROR_SCHEMA``, ``AttributeSpec``, ``AttributeKind``, ``Dynamics``,
  ``SEED_FEATURE_MAP``, ``coherence_report``, ``assert_coherent``,
  ``SCHEMA_VERSION``, ``schema_fingerprint``.
- Runtime: ``MirrorState``, ``Choice``, ``Signal``, ``AttributeReading``.
- Event log / reducer: ``EventLog``, ``MirrorEvent``, ``ChoiceObserved``,
  ``TurnAdvanced``, ``reduce``, ``scan``, ``log_from_choices``.

The event log is the source of truth; the Mirror is a pure reduction over it.
See ``docs/MIRROR_SCHEMA.md`` for the schema spec, the anti-mush review, and the
reducer contract.
"""

from __future__ import annotations

from mirror.log import (
    ChoiceObserved,
    EventLog,
    MirrorEvent,
    TurnAdvanced,
    event_from_dict,
    event_to_dict,
    log_from_choices,
    reduce,
    scan,
)
from mirror.schema import (
    MIRROR_SCHEMA,
    SCHEMA_VERSION,
    SEED_FEATURE_MAP,
    AttributeKind,
    AttributeSpec,
    CoherenceReport,
    Dynamics,
    assert_coherent,
    coherence_report,
    schema_fingerprint,
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
    "SCHEMA_VERSION",
    "SEED_FEATURE_MAP",
    "AttributeKind",
    "AttributeSpec",
    "CoherenceReport",
    "Dynamics",
    "assert_coherent",
    "coherence_report",
    "schema_fingerprint",
    "value_range",
    "AttributeReading",
    "Choice",
    "MirrorState",
    "Signal",
    "EventLog",
    "MirrorEvent",
    "ChoiceObserved",
    "TurnAdvanced",
    "event_to_dict",
    "event_from_dict",
    "reduce",
    "scan",
    "log_from_choices",
]
