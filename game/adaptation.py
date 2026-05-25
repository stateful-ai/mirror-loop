"""Adaptation — the recorded, auditable schema for one content decision.

The prototype ships exactly one adaptation *type*, **tendency mirroring**
(``docs/ADAPTATION.md``): the Mirror reads the player's dominant behavioral
tendency and reflects it back by selecting/ordering pre-authored content. That one
type has two *surfaces* — picking which framing a slot reveals, and surfacing the
predicted choice first — both reading the same axis. This module defines the
**record** every such decision produces.

Why a stored record at all, when the architecture says the event log is the only
source of truth and the Mirror is recomputed from it? Because of a deliberate
companion rule (company memory ``mem_20260524T192411Z_0bc52d``): *raw events, the
derived Mirror projection, and the player-facing Reflection beat are separate
primitives, and the Reflection beat may render only from stored adaptation
**provenance**, never recomputation.* So an adaptation is not re-derived after the
fact — it is captured at the instant it is made, together with the provenance that
makes it auditable and replayable:

* its **trigger Mirror snapshot** — the exact player-model read the decision was a
  function of (:class:`MirrorSnapshot`), and
* its **source event-seq** — how far into the append-only log that read was
  reduced from (``AdaptationProvenance.source_event_seq``).

:class:`AdaptationProvenance` is a *required*, non-default field of every
:class:`Adaptation`, so the schema makes it structurally impossible to record an
adaptation without saying what it was based on.

Versioned, like the Mirror and world-state schemas: :data:`ADAPTATION_SCHEMA_VERSION`
bumps on any incompatible change to the serialized shape, and an
:class:`AdaptationLog` written under another version is refused at load.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from loop.core import PlayerState

from .world import dominant_tendency

#: Bump on any incompatible change to the serialized adaptation shape (a new/
#: removed field, a renamed :class:`AdaptationKind`, a changed snapshot shape).
ADAPTATION_SCHEMA_VERSION = 1


class AdaptationKind(Enum):
    """Which *surface* of tendency mirroring an :class:`Adaptation` records.

    One adaptation type, two granularities (``docs/ADAPTATION.md`` §1). Naming the
    surface keeps the record self-describing — a branch selection and a choice
    re-ordering produce structurally different outputs and must not be conflated.
    """

    #: Across-scene: the Mirror revealed the framing written for the dominant
    #: tendency instead of the neutral one (``game.world.Slot.pick``).
    BRANCH_SELECTION = "branch_selection"
    #: In-scene: the Mirror re-presented the scene with the predicted choice first
    #: (``loop.core.Mirror.adapt``).
    CHOICE_REORDERING = "choice_reordering"


@dataclass(frozen=True)
class MirrorSnapshot:
    """An immutable read of the player model at the instant an adaptation fired.

    This is the *trigger Mirror snapshot* the acceptance contract requires: the
    reading the adaptation was a pure function of, frozen into the record so the
    decision can be audited — and the Reflection beat rendered — from stored
    provenance rather than recomputation.

    v0's Mirror reads **one axis**: the player's dominant behavioral *tendency*
    from the running tally (``docs/ADAPTATION.md`` §2). So the snapshot captures
    that tally, the dominant tendency it implies (``None`` when there is no clear
    leader, exactly as :func:`~game.world.dominant_tendency` resolves it), and how
    many loops it was built from. When the richer eight-axis model
    (``docs/MIRROR_SCHEMA.md``) later feeds the adaptation, this snapshot is where
    its reading is added — bumping :data:`ADAPTATION_SCHEMA_VERSION`.
    """

    #: Number of choices the player had made when this read was taken.
    turn_count: int
    #: The running tendency tally as ``(tendency, count)`` pairs, sorted by
    #: tendency name so the serialized form is stable and diffable.
    tendency_counts: tuple[tuple[str, int], ...] = ()
    #: The strict-argmax dominant tendency, or ``None`` on an empty history or an
    #: exact top tie — i.e. the same "no lean, no tailoring" rule the adaptation
    #: itself obeys (``docs/ADAPTATION.md`` §4).
    dominant: str | None = None

    @classmethod
    def from_player_state(cls, state: PlayerState) -> "MirrorSnapshot":
        """Read a :class:`~loop.core.PlayerState` into a snapshot."""
        counts = tuple(sorted(state.tendency_counts.items()))
        return cls(
            turn_count=state.turn_count,
            tendency_counts=counts,
            dominant=dominant_tendency(state),
        )

    def to_dict(self) -> dict:
        return {
            "turn_count": self.turn_count,
            "tendency_counts": [list(pair) for pair in self.tendency_counts],
            "dominant": self.dominant,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MirrorSnapshot":
        return cls(
            turn_count=data["turn_count"],
            tendency_counts=tuple(
                (name, count) for name, count in data.get("tendency_counts", [])
            ),
            dominant=data.get("dominant"),
        )


@dataclass(frozen=True)
class AdaptationProvenance:
    """Where an adaptation came from: a point in the log, and the read taken there.

    These two fields *are* the acceptance contract for every adaptation, so both
    are required:

    * ``source_event_seq`` — the number of events consumed from the append-only
      log (``mirror/log.py``) when the adaptation was computed. The decision is a
      pure function of ``events[:source_event_seq]``; indexing by *count of events
      reduced* (not a wall clock) keeps provenance replayable — reduce the log to
      this seq and you recover exactly the state the decision saw. In the v0
      runtime, where one loop folds one choice event, this equals the snapshot's
      ``turn_count``.
    * ``trigger_snapshot`` — the :class:`MirrorSnapshot` read at that seq.
    """

    #: Count of log events the trigger snapshot was reduced from (the as-of index).
    source_event_seq: int
    #: The player-model read the adaptation was a function of.
    trigger_snapshot: MirrorSnapshot

    def __post_init__(self) -> None:
        if self.source_event_seq < 0:
            raise ValueError(
                f"source_event_seq must be >= 0, got {self.source_event_seq}"
            )

    def to_dict(self) -> dict:
        return {
            "source_event_seq": self.source_event_seq,
            "trigger_snapshot": self.trigger_snapshot.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdaptationProvenance":
        return cls(
            source_event_seq=data["source_event_seq"],
            trigger_snapshot=MirrorSnapshot.from_dict(data["trigger_snapshot"]),
        )


@dataclass(frozen=True)
class Adaptation:
    """One recorded adaptation: a single content decision, plus its provenance.

    Both surfaces of tendency mirroring serialize through this one record;
    ``kind`` says which, and the two output fields are constrained to match it:

    * :attr:`AdaptationKind.BRANCH_SELECTION` sets :attr:`revealed` (the branch key
      shown) and leaves :attr:`ordering` empty;
    * :attr:`AdaptationKind.CHOICE_REORDERING` sets :attr:`ordering` (the resulting
      choice-id order, predicted-first) and leaves :attr:`revealed` ``None``.

    :attr:`provenance` is required — there is no way to construct an adaptation
    that does not record its trigger snapshot and source event-seq.
    """

    kind: AdaptationKind
    #: The world slot / scene this adaptation acted on.
    slot_key: str
    #: BRANCH_SELECTION: the branch key revealed (a tendency or ``"default"``).
    #: ``None`` for a re-ordering.
    revealed: str | None
    #: CHOICE_REORDERING: the choice ids in the order offered (the predicted
    #: choice is ``ordering[0]``). Empty for a branch selection.
    ordering: tuple[str, ...]
    #: The trigger Mirror snapshot + source event-seq this decision came from.
    provenance: AdaptationProvenance

    def __post_init__(self) -> None:
        if self.kind is AdaptationKind.BRANCH_SELECTION:
            if not self.revealed:
                raise ValueError("BRANCH_SELECTION must set 'revealed'")
            if self.ordering:
                raise ValueError("BRANCH_SELECTION must not set 'ordering'")
        elif self.kind is AdaptationKind.CHOICE_REORDERING:
            if self.revealed is not None:
                raise ValueError("CHOICE_REORDERING must not set 'revealed'")
            if not self.ordering:
                raise ValueError("CHOICE_REORDERING must set a non-empty 'ordering'")

    @property
    def predicted_choice(self) -> str | None:
        """The choice the Mirror surfaced first, for a re-ordering; else ``None``."""
        return self.ordering[0] if self.ordering else None

    # --- convenience constructors: provenance is captured, not optional ------

    @classmethod
    def branch_selection(
        cls,
        slot_key: str,
        revealed: str,
        *,
        state: PlayerState,
        source_event_seq: int,
    ) -> "Adaptation":
        """Record a branch-framing selection from the state that drove it."""
        return cls(
            kind=AdaptationKind.BRANCH_SELECTION,
            slot_key=slot_key,
            revealed=revealed,
            ordering=(),
            provenance=_provenance(state, source_event_seq),
        )

    @classmethod
    def choice_reordering(
        cls,
        slot_key: str,
        ordering: Iterable[str],
        *,
        state: PlayerState,
        source_event_seq: int,
    ) -> "Adaptation":
        """Record an in-scene re-ordering from the state that drove it."""
        return cls(
            kind=AdaptationKind.CHOICE_REORDERING,
            slot_key=slot_key,
            revealed=None,
            ordering=tuple(ordering),
            provenance=_provenance(state, source_event_seq),
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "slot_key": self.slot_key,
            "revealed": self.revealed,
            "ordering": list(self.ordering),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Adaptation":
        return cls(
            kind=AdaptationKind(data["kind"]),
            slot_key=data["slot_key"],
            revealed=data.get("revealed"),
            ordering=tuple(data.get("ordering", ())),
            provenance=AdaptationProvenance.from_dict(data["provenance"]),
        )


def _provenance(state: PlayerState, source_event_seq: int) -> AdaptationProvenance:
    return AdaptationProvenance(
        source_event_seq=source_event_seq,
        trigger_snapshot=MirrorSnapshot.from_player_state(state),
    )


@dataclass(frozen=True)
class AdaptationLog:
    """An ordered, version-stamped record of the adaptations made in a session.

    This is the *stored adaptation provenance* the Reflection beat renders from
    (company memory ``mem_20260524T192411Z_0bc52d``): append-only and replayable,
    it sits beside the Mirror's event log as a separate primitive — the log of
    *what the Mirror did*, distinct from the log of *what the player did*.
    """

    adaptations: tuple[Adaptation, ...] = ()
    schema_version: int = ADAPTATION_SCHEMA_VERSION

    def append(self, *adaptations: Adaptation) -> "AdaptationLog":
        """Return a new log with ``adaptations`` appended (the log is append-only)."""
        return AdaptationLog(
            adaptations=self.adaptations + adaptations,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "adaptations": [a.to_dict() for a in self.adaptations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdaptationLog":
        version = data.get("schema_version")
        if version != ADAPTATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported adaptation schema version {version!r} "
                f"(this build reads v{ADAPTATION_SCHEMA_VERSION})"
            )
        return cls(
            adaptations=tuple(
                Adaptation.from_dict(a) for a in data.get("adaptations", [])
            ),
            schema_version=version,
        )

    def to_json(self) -> str:
        """Serialize to an indented, key-sorted JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "AdaptationLog":
        """Rebuild from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text))
