"""The Mirror as a pure reducer over a recorded event log.

The locked architecture rule for Mirror Loop is: **the append-only event log is
the only source of truth, and the Mirror is a pure reduction over it.** Nothing
about the player is kept as authoritative *derived* state — the player-state is
recomputed from the log every time, so two reductions of the same log produce
byte-identical state. (``mirror/schema.py`` says what the axes are;
``mirror/state.py`` says how each one moves per choice; this module says how a
*recorded session* folds into a state.)

What lives here:

- :class:`MirrorEvent` — the typed, serializable facts a log records. There are
  exactly two, one per state transition in :mod:`mirror.state`:
  :class:`ChoiceObserved` (a player action emitted these signals) and
  :class:`TurnAdvanced` (a turn boundary passed, so STATE axes decay one step).
  Events record *inputs* (the signals), never *outputs* (the resulting values):
  the values are derived, and derived state is never the authority.
- :class:`EventLog` — an ordered, version-stamped container that (de)serializes
  itself and reduces to a :class:`MirrorState`.
- :func:`reduce` — the pure fold ``events -> MirrorState``.
- :func:`scan` — the running reductions: the state after each event, for
  reconstructing the Mirror *as of* any turn (e.g. what the prediction loop saw
  just before decision point *t*).

Because a log is stamped with the schema version *and* a structural fingerprint,
replaying it against a schema that changed underneath it fails loudly instead of
silently producing a different "recomputation".
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from mirror.schema import SCHEMA_VERSION, schema_fingerprint
from mirror.state import Choice, MirrorState, Signal


# --- The events: the typed facts the log records ------------------------------


@dataclass(frozen=True)
class ChoiceObserved:
    """Recorded fact: the player made a choice that emitted typed evidence.

    Carries the same :class:`~mirror.state.Signal` payload a live ``Choice``
    would, plus optional provenance (which scene/act it happened in) so a piece
    of evidence can be traced to its origin — the grounding the "Mirror noticed…"
    callbacks and the debug panel need. The reducer re-derives the per-axis
    updates from these signals; it never reads back a stored delta.
    """

    #: Discriminator used in the serialized form (matches ``event_type`` in the
    #: game's event-log spec, game_design.md §14).
    EVENT_TYPE = "choice_observed"

    choice_id: str
    signals: tuple[Signal, ...] = ()
    scene_id: str | None = None
    act_id: str | None = None

    @classmethod
    def from_choice(
        cls, choice: Choice, *, scene_id: str | None = None, act_id: str | None = None
    ) -> "ChoiceObserved":
        """Record a live :class:`~mirror.state.Choice` as a log event."""
        return cls(
            choice_id=choice.id,
            signals=tuple(choice.signals),
            scene_id=scene_id,
            act_id=act_id,
        )

    def as_choice(self) -> Choice:
        """Reconstitute the :class:`~mirror.state.Choice` this event recorded."""
        return Choice(id=self.choice_id, signals=tuple(self.signals))

    def apply_to(self, state: MirrorState) -> None:
        """Apply this fact to ``state`` (mutates it; used inside the reducer)."""
        state.apply_choice(self.as_choice())


@dataclass(frozen=True)
class TurnAdvanced:
    """Recorded fact: a turn boundary passed.

    Its only effect is decay — every STATE axis relaxes one step toward its
    resting value while TRAITs are untouched. Modeling the turn boundary as its
    own event keeps decay explicit in the log (not smuggled into a choice) and
    lets a turn pass with no choice at all.
    """

    EVENT_TYPE = "turn_advanced"

    def apply_to(self, state: MirrorState) -> None:
        """Apply this fact to ``state`` (mutates it; used inside the reducer)."""
        state.tick()


#: The discriminated union of everything a Mirror event log can contain.
MirrorEvent = ChoiceObserved | TurnAdvanced


# --- (de)serialization of events ----------------------------------------------
# Events are pure data; serialization lives here as plain functions so the event
# dataclasses stay a clean statement of the facts. JSON has no tuples, so every
# round-trip re-tuples on the way back in.


def _signal_to_dict(signal: Signal) -> dict:
    data: dict = {"attribute": signal.attribute, "weight": signal.weight}
    if signal.target is not None:
        data["target"] = signal.target
    if signal.mode is not None:
        data["mode"] = signal.mode
    return data


def _signal_from_dict(data: dict) -> Signal:
    return Signal(
        attribute=data["attribute"],
        target=data.get("target"),
        mode=data.get("mode"),
        weight=data.get("weight", 1.0),
    )


def event_to_dict(event: MirrorEvent) -> dict:
    """Serialize one event to a JSON-ready dict, tagged with its ``event_type``."""
    if isinstance(event, ChoiceObserved):
        data: dict = {
            "event_type": ChoiceObserved.EVENT_TYPE,
            "choice_id": event.choice_id,
            "signals": [_signal_to_dict(s) for s in event.signals],
        }
        if event.scene_id is not None:
            data["scene_id"] = event.scene_id
        if event.act_id is not None:
            data["act_id"] = event.act_id
        return data
    if isinstance(event, TurnAdvanced):
        return {"event_type": TurnAdvanced.EVENT_TYPE}
    raise TypeError(f"cannot serialize unknown event type {type(event).__name__}")


def event_from_dict(data: dict) -> MirrorEvent:
    """Rebuild one event from :func:`event_to_dict` output."""
    event_type = data.get("event_type")
    if event_type == ChoiceObserved.EVENT_TYPE:
        return ChoiceObserved(
            choice_id=data["choice_id"],
            signals=tuple(_signal_from_dict(s) for s in data.get("signals", [])),
            scene_id=data.get("scene_id"),
            act_id=data.get("act_id"),
        )
    if event_type == TurnAdvanced.EVENT_TYPE:
        return TurnAdvanced()
    raise ValueError(f"unknown event_type {event_type!r} in log")


# --- The reducer: the pure fold from log to state -----------------------------
# The canonical implementation lives in ``mirror/reducer.py`` so the pure fold
# can stay structurally isolated from the (future) impure ``mirror/loop.py`` —
# the architectural rule locked in by ``docs/mirror_loop_m1_founder_brief.md``.
# This module re-exports it so existing callers keep working.

from mirror.reducer import reduce, scan  # noqa: E402,F401


# --- The log: an ordered, version-stamped container ---------------------------


@dataclass(frozen=True)
class EventLog:
    """An ordered, version-stamped event log — the Mirror's source of truth.

    The events are the only authoritative record; the player-state is whatever
    :meth:`reduce` computes from them. The log also records the schema version
    and structural fingerprint it was produced under, so a later reduce can
    refuse a log whose schema has shifted underneath it.
    """

    events: tuple[MirrorEvent, ...] = ()
    schema_version: int = SCHEMA_VERSION
    fingerprint: str = field(default_factory=schema_fingerprint)

    def append(self, *events: MirrorEvent) -> "EventLog":
        """Return a new log with ``events`` appended (the log is append-only)."""
        return EventLog(
            events=self.events + events,
            schema_version=self.schema_version,
            fingerprint=self.fingerprint,
        )

    def _assert_reducible(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"event log schema version {self.schema_version!r} != current "
                f"{SCHEMA_VERSION!r}; refusing to reduce a log from another schema"
            )
        current = schema_fingerprint()
        if self.fingerprint != current:
            raise ValueError(
                "schema fingerprint mismatch: the schema changed without a "
                "SCHEMA_VERSION bump, so recomputation would not match the log. "
                f"(log={self.fingerprint!r}, current={current!r})"
            )

    def reduce(self) -> MirrorState:
        """Recompute the player-state from this log (with the schema guard)."""
        self._assert_reducible()
        return reduce(self.events)

    def scan(self) -> Iterator[MirrorState]:
        """The running player-state after each event (with the schema guard)."""
        self._assert_reducible()
        return scan(self.events)

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        """A JSON-serializable snapshot of the whole log."""
        return {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "events": [event_to_dict(e) for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EventLog":
        """Rebuild a log from :meth:`to_dict` output.

        Preserves the recorded version/fingerprint verbatim, so a log written
        under an incompatible schema is reconstructed faithfully and then
        rejected at :meth:`reduce` time — not silently coerced to the current
        schema.
        """
        return cls(
            events=tuple(event_from_dict(e) for e in data["events"]),
            schema_version=data["schema_version"],
            fingerprint=data.get("fingerprint", ""),
        )

    def to_json(self) -> str:
        """Serialize to an indented, key-sorted JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "EventLog":
        """Rebuild a log from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text))


def log_from_choices(
    choices: Iterable[Choice], *, tick_each_turn: bool = True
) -> EventLog:
    """Build a log from a sequence of choices, one turn each.

    Mirrors the common play pattern (apply a choice, then advance the turn). With
    ``tick_each_turn=False`` it records only the choices and no decay events — for
    flows where turns and choices don't line up one-to-one.
    """
    events: list[MirrorEvent] = []
    for choice in choices:
        events.append(ChoiceObserved.from_choice(choice))
        if tick_each_turn:
            events.append(TurnAdvanced())
    return EventLog(events=tuple(events))
