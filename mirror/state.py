"""Runtime "mirror" player-state and the per-choice update mechanics.

``mirror/schema.py`` says *what* the axes are. This module says *how a player's
values move as they play*. The contract is the anti-mush behavior:

- A fresh state knows **nothing**: every axis sits at its neutral value with
  confidence 0. Nothing is assumed about a player before they act.
- A choice only moves the axes it carries **signals** for. There is no global
  drift — most axes are untouched by any given choice.
- Each update is a bounded EWMA step toward the evidence, so values stay in
  range and one choice can never slam an axis to an extreme.
- Confidence rises only with evidence. An axis nobody has given evidence for
  stays unknown; the prediction loop is expected to ignore unknown axes.

A ``Choice`` is the runtime carrier of "how each updates per choice": it bundles
the signals a given player action emits. See ``docs/MIRROR_SCHEMA.md`` for the
catalog of which choices emit which signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mirror.schema import (
    MIRROR_SCHEMA,
    AttributeKind,
    AttributeSpec,
    Dynamics,
)


@dataclass(frozen=True)
class Signal:
    """One piece of evidence a choice provides about one attribute.

    For a UNIT/BIPOLAR axis, ``target`` is the value in the axis's range that the
    choice is evidence *for* (e.g. a defiant choice → ``target=-1.0`` on
    ``authority_trust``); the value EWMAs toward it. For a DISTRIBUTION axis,
    ``mode`` names the activity the turn was spent on. ``weight`` in ``(0, 1]``
    scales how strong this single piece of evidence is.
    """

    attribute: str
    target: float | None = None
    mode: str | None = None
    weight: float = 1.0

    @classmethod
    def toward(cls, attribute: str, target: float, weight: float = 1.0) -> "Signal":
        """Evidence pulling a scalar axis toward ``target``."""
        return cls(attribute=attribute, target=target, weight=weight)

    @classmethod
    def spend(cls, attribute: str, mode: str, weight: float = 1.0) -> "Signal":
        """Evidence that a turn was spent on ``mode`` of a distribution axis."""
        return cls(attribute=attribute, mode=mode, weight=weight)


@dataclass(frozen=True)
class Choice:
    """A player action, and the evidence it emits about the player.

    This is the unit of "how each attribute updates per choice": feed a ``Choice``
    to :meth:`MirrorState.apply_choice` and the signals it carries move the named
    axes. A choice with no signals is inert (it moves nothing) — which is itself
    a guard against accidental mush.
    """

    id: str
    label: str = ""
    signals: tuple[Signal, ...] = ()


@dataclass
class AttributeReading:
    """A player's current value on one axis, plus how sure we are of it."""

    value: float | tuple[float, ...]
    evidence_count: float = 0.0
    confidence: float = 0.0

    def as_dict(self) -> dict:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        return {
            "value": value,
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class MirrorState:
    """The system's current model of one player — the "mirror" itself.

    Construct with :meth:`new`, drive it with :meth:`apply_choice` per player
    action and :meth:`tick` per turn, and read it back with :meth:`known` (the
    confident axes) or :meth:`snapshot` (for the event log / ActPackage
    ``player_model_snapshot``).
    """

    readings: dict[str, AttributeReading] = field(default_factory=dict)

    @classmethod
    def new(cls) -> "MirrorState":
        """A blank mirror: every axis at neutral, confidence 0 (nothing known)."""
        return cls(
            readings={
                name: AttributeReading(value=spec.neutral_value())
                for name, spec in MIRROR_SCHEMA.items()
            }
        )

    def apply_choice(self, choice: Choice) -> dict[str, float]:
        """Update the mirror from one player choice.

        Applies every signal the choice carries, bumping evidence and confidence
        on exactly the axes touched and leaving all others unchanged. Returns the
        per-axis value delta (positive/negative scalar move, or for a
        distribution the change in the spent mode's share) — the same shape the
        event log records as ``player_model_updates``.
        """
        # Atomic: apply to a working copy and commit only if *every* signal is
        # valid, so a malformed signal late in the choice can't leave the mirror
        # half-updated. Deltas accumulate per axis when a choice carries several
        # signals for the same attribute (they compound, not overwrite).
        import copy

        working = copy.deepcopy(self.readings)
        deltas: dict[str, float] = {}
        for signal in choice.signals:
            spec = MIRROR_SCHEMA.get(signal.attribute)
            if spec is None:
                # A stray signal name is exactly how mush sneaks in. Reject it.
                raise KeyError(f"signal targets unknown attribute {signal.attribute!r}")
            if not (0.0 < signal.weight <= 1.0):
                raise ValueError(f"signal weight {signal.weight} not in (0, 1]")
            delta = self._apply_signal(working, spec, signal)
            deltas[signal.attribute] = deltas.get(signal.attribute, 0.0) + delta
        self.readings = working
        return deltas

    def _apply_signal(
        self, readings: dict[str, AttributeReading], spec: AttributeSpec, signal: Signal
    ) -> float:
        reading = readings[spec.name]
        if spec.kind is AttributeKind.DISTRIBUTION:
            delta = self._update_distribution(spec, reading, signal)
        else:
            delta = self._update_scalar(spec, reading, signal)
        reading.evidence_count += signal.weight
        reading.confidence = spec.confidence(reading.evidence_count)
        return delta

    def _update_scalar(
        self, spec: AttributeSpec, reading: AttributeReading, signal: Signal
    ) -> float:
        if signal.target is None:
            raise ValueError(f"scalar axis {spec.name!r} needs a target, not a mode")
        low, high = (
            (0.0, 1.0) if spec.kind is AttributeKind.UNIT else (-1.0, 1.0)
        )
        if not (low <= signal.target <= high):
            raise ValueError(
                f"target {signal.target} outside [{low}, {high}] for {spec.name!r}"
            )
        old = float(reading.value)
        # Bounded EWMA: step a fraction of the way toward the evidence. Convex,
        # so the result can never leave [old, target] ⊆ range — no overshoot.
        step = spec.learning_rate * signal.weight
        new = spec.clamp(old + step * (signal.target - old))
        reading.value = new
        return new - old

    def _update_distribution(
        self, spec: AttributeSpec, reading: AttributeReading, signal: Signal
    ) -> float:
        if signal.mode is None:
            raise ValueError(f"distribution axis {spec.name!r} needs a mode, not a target")
        if signal.mode not in spec.modes:
            raise ValueError(f"unknown mode {signal.mode!r} for {spec.name!r}")
        old = tuple(reading.value)  # type: ignore[arg-type]
        alpha = spec.learning_rate * signal.weight
        idx = spec.modes.index(signal.mode)
        # Mix the current budget toward a one-hot on the spent mode. A convex
        # combination of two distributions stays a distribution (sums to 1).
        new = tuple(
            (1.0 - alpha) * p + alpha * (1.0 if i == idx else 0.0)
            for i, p in enumerate(old)
        )
        reading.value = new
        return new[idx] - old[idx]

    def tick(self) -> None:
        """Advance one turn: relax every STATE axis toward its resting value.

        TRAIT axes are untouched (they don't self-relax). This is what keeps
        fast affect (frustration) from being mistaken for a stable trait.
        """
        for name, spec in MIRROR_SCHEMA.items():
            if spec.dynamics is not Dynamics.STATE:
                continue
            reading = self.readings[name]
            old = float(reading.value)
            reading.value = spec.clamp(old + spec.decay_per_turn * (spec.neutral - old))

    def known(self, min_confidence: float = 0.5) -> dict[str, AttributeReading]:
        """The axes we actually have a confident read on.

        The prediction loop should forecast from these, not from unknown axes
        sitting at their neutral defaults — predicting off neutrals is mush
        dressed up as signal.
        """
        return {
            name: r for name, r in self.readings.items() if r.confidence >= min_confidence
        }

    def snapshot(self) -> dict:
        """A JSON-serializable view for the event log / ActPackage snapshot."""
        return {name: r.as_dict() for name, r in self.readings.items()}
