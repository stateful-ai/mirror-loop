"""Pure render of a :class:`MirrorState` to one player-facing line.

This module is the **Reflection / spoken-observation** render of the eight-axis
mirror state, distinct from the loop-level legibility beat in ``loop/core.py``
(which speaks about a single categorical tendency). Per
``docs/ADAPTATION.md`` §4 the Reflection is a *render* of the player model — not
a transform of content — so it lives on its own seam: a pure function from
:class:`MirrorState` to ``str``, no IO, no globals, fully deterministic.

The rule the render obeys (``docs/MIRROR_SCHEMA.md`` §3): only **confidently-known**
axes are eligible. Predicting off an unobserved neutral is mush wearing a
confidence hat, and that is exactly what this line would amplify. With no axis
confident enough to name, the render says so plainly rather than picking the
loudest unknown.

Among the confident axes, the **dominant lean** is the one whose value sits
farthest from its own neutral, normalized into ``[0, 1]`` per kind so axes are
comparable, and weighted by the axis's confidence. Ties break by schema
declaration order (``MIRROR_SCHEMA``) so the rendered line is byte-stable across
runs. The label spoken is the axis's own pole/mode name from the schema, which
is the canonical player-facing wording for that lean.
"""

from __future__ import annotations

from mirror.schema import MIRROR_SCHEMA, AttributeKind, AttributeSpec
from mirror.state import AttributeReading, MirrorState

__all__ = ["render"]


# The line shown when no axis has accumulated enough evidence to name. Kept as a
# named constant so the snapshot test pins it and downstream UIs can match on it.
NO_LEAN_LINE = "Mirror noticed: nothing yet — no clear lean to name."


def render(state: MirrorState) -> str:
    """Render ``state``'s dominant axis lean as one player-facing line.

    Only axes in ``state.known()`` (default confidence threshold) are eligible,
    so an axis still sitting at its neutral default never speaks. With no
    eligible axis, returns :data:`NO_LEAN_LINE`.
    """
    known = state.known()
    # Collect (sort_key, label) for every eligible axis. Sort_key is built so a
    # plain ascending sort puts the dominant lean first: more strength wins,
    # earlier schema position breaks ties.
    candidates: list[tuple[tuple[float, int], str]] = []
    for priority, (name, spec) in enumerate(MIRROR_SCHEMA.items()):
        reading = known.get(name)
        if reading is None:
            continue
        lean = _lean(spec, reading)
        if lean is None:
            continue
        magnitude, label = lean
        strength = magnitude * reading.confidence
        if strength <= 0.0:
            continue
        candidates.append(((-strength, priority), label))
    if not candidates:
        return NO_LEAN_LINE
    candidates.sort(key=lambda item: item[0])
    _, label = candidates[0]
    return f"Mirror noticed: you read as {label}."


def _lean(
    spec: AttributeSpec, reading: AttributeReading
) -> tuple[float, str] | None:
    """Magnitude of this axis's lean in ``[0, 1]`` and the pole/mode it names.

    Returns ``None`` when the axis is at (or below) its neutral — nothing to
    name. Magnitudes are normalized per kind so axes of different shapes are
    comparable on the same scale.
    """
    if spec.kind is AttributeKind.DISTRIBUTION:
        mix = tuple(reading.value)  # type: ignore[arg-type]
        n = len(mix)
        # ``index`` returns the earliest occurrence on ties, which combined with
        # the schema's declared mode order makes the chosen mode deterministic.
        max_share = max(mix)
        idx = mix.index(max_share)
        uniform = 1.0 / n
        excess = max_share - uniform
        if excess <= 0.0:
            return None
        # Normalize the excess concentration into [0, 1]: 0 = uniform budget,
        # 1 = a one-hot on a single mode. (1 - 1/n) is the max possible excess.
        magnitude = excess / (1.0 - uniform)
        return magnitude, spec.modes[idx]

    value = float(reading.value)  # type: ignore[arg-type]
    diff = value - spec.neutral
    if diff == 0.0:
        return None

    if spec.kind is AttributeKind.BIPOLAR:
        # Range [-1, 1], neutral 0, so |value| is already a normalized magnitude.
        magnitude = abs(value)
        label = spec.poles[1] if diff > 0 else spec.poles[0]
        return magnitude, label

    # UNIT: range [0, 1]. The span on each side of neutral may differ
    # (e.g. frustration rests at 0, so only the upward span is meaningful).
    span = (1.0 - spec.neutral) if diff > 0 else (spec.neutral - 0.0)
    if span <= 0.0:
        return None
    magnitude = abs(diff) / span
    label = spec.poles[1] if diff > 0 else spec.poles[0]
    return magnitude, label
