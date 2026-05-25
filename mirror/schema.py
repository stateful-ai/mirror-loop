"""The "mirror" player-state schema — the typed set of attributes the system
infers about the player, and the static rules that govern how each one moves.

Mirror Loop's locked thesis (``docs/THESIS.md``) is that a lightweight player
model can out-predict a naive baseline. That only works if the inferred state is
*coherent*: a small set of orthogonal, independently-evidenced axes — not a pile
of vaguely-named scalars that all drift together. We call the failure mode
**mush**, and this module is deliberately built to make mush hard to introduce.

This file holds the **static schema** (what the axes are and how each is allowed
to move). ``mirror/state.py`` holds the **runtime state** (a player's current
values) and applies the per-choice updates. ``docs/MIRROR_SCHEMA.md`` is the
human-facing review, including the mapping from the seed design's loose
``game_design.md`` §6.1 feature list onto these axes.

The anti-mush invariants are not just prose: ``assert_coherent()`` enforces them,
and the tests run it, so the schema cannot silently rot back into mush.

    python -m mirror   # prints the schema table + the coherence report
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class AttributeKind(Enum):
    """The three shapes an inferred attribute can take.

    Keeping the *kind* explicit is itself anti-mush: a magnitude, a signed
    disposition, and an activity budget are different things and must not be
    averaged together as if they were interchangeable floats.
    """

    #: A bounded magnitude in ``[0, 1]`` (e.g. curiosity). Has two named ends.
    UNIT = "unit"
    #: A signed disposition in ``[-1, 1]`` between two named poles
    #: (e.g. authority_trust: defiant ↔ deferential). Neutral is exactly 0.
    BIPOLAR = "bipolar"
    #: A normalized probability distribution over named modes that sums to 1
    #: (e.g. playstyle_mix). Models a *budget*, not independent scalars.
    DISTRIBUTION = "distribution"


class Dynamics(Enum):
    """How fast an attribute moves and whether it relaxes on its own.

    Conflating slow personality *traits* with fast affective *state* is a classic
    mush move — they live on different timescales and must decay differently.
    """

    #: Slow, sticky. Accumulates evidence and does not relax on its own.
    TRAIT = "trait"
    #: Fast, self-relaxing. Spikes on a triggering choice and decays each turn
    #: back toward its resting value.
    STATE = "state"


def value_range(kind: AttributeKind) -> tuple[float, float]:
    """The inclusive ``(low, high)`` a scalar attribute of this kind may hold."""
    if kind is AttributeKind.UNIT:
        return (0.0, 1.0)
    if kind is AttributeKind.BIPOLAR:
        return (-1.0, 1.0)
    raise ValueError(f"{kind} is not a scalar kind")


@dataclass(frozen=True)
class AttributeSpec:
    """The static definition of one inferred attribute (one axis of the mirror).

    Every field exists to pin down *what the axis means* and *how it is allowed
    to move*, so updates are bounded, legible, and tied to observable evidence
    rather than vibes.
    """

    name: str
    kind: AttributeKind
    dynamics: Dynamics
    description: str
    #: For UNIT/BIPOLAR: the (low_pole, high_pole) meanings. For DISTRIBUTION:
    #: left empty (use ``modes`` instead). Naming both ends is mandatory — an
    #: axis whose ends you can't name is mush.
    poles: tuple[str, str] | tuple[()] = ()
    #: For DISTRIBUTION only: the named modes the budget is split across.
    modes: tuple[str, ...] = ()
    #: Resting / "we have no evidence yet" value. BIPOLAR must rest at 0.0.
    neutral: float = 0.0
    #: EWMA step size in ``(0, 1]``: how far one full-weight choice pulls the
    #: value toward the evidence. Small = needs repeated evidence to move.
    learning_rate: float = 0.25
    #: STATE only: fraction of the gap to neutral closed each turn, in ``[0, 1)``.
    #: TRAITs must be 0.0 (they don't relax on their own).
    decay_per_turn: float = 0.0
    #: Evidence count at which confidence reaches 0.5. Lower = trusts fewer
    #: observations. Confidence saturates toward 1 with more evidence.
    evidence_halflife: float = 3.0

    def neutral_value(self) -> float | tuple[float, ...]:
        """The starting value for this attribute in a fresh, unobserved state."""
        if self.kind is AttributeKind.DISTRIBUTION:
            n = len(self.modes)
            return tuple(1.0 / n for _ in self.modes)
        return self.neutral

    def clamp(self, value: float) -> float:
        """Clamp a scalar value into this attribute's legal range."""
        low, high = value_range(self.kind)
        return max(low, min(high, value))

    def confidence(self, evidence_count: float) -> float:
        """Map an evidence count to confidence in ``[0, 1)``.

        Zero evidence → zero confidence (the axis is *unknown*, not "0.5"). This
        is the runtime guarantee against mush: an unobserved axis never
        masquerades as a confident reading.
        """
        if evidence_count <= 0:
            return 0.0
        return 1.0 - 0.5 ** (evidence_count / self.evidence_halflife)


# --- The schema. This registry IS the "mirror" player-state definition. --------
#
# Eight orthogonal axes replace the seed's fifteen loosely-named features. The
# consolidation is the anti-mush review in code form; see SEED_FEATURE_MAP below
# and docs/MIRROR_SCHEMA.md for the full rationale.

_SPECS: tuple[AttributeSpec, ...] = (
    AttributeSpec(
        name="playstyle_mix",
        kind=AttributeKind.DISTRIBUTION,
        dynamics=Dynamics.TRAIT,
        description=(
            "How the player spends their turns. A budget over activity modes, "
            "not four independent rates — they necessarily trade off."
        ),
        modes=("combat", "conversation", "exploration", "optimization"),
        learning_rate=0.30,
        evidence_halflife=2.0,
    ),
    AttributeSpec(
        name="authority_trust",
        kind=AttributeKind.BIPOLAR,
        dynamics=Dynamics.TRAIT,
        description=(
            "Disposition toward the lab/system's authority. The single signed "
            "axis for trust-vs-resistance; 'agency_resistance' is its negative "
            "pole, not a separate number."
        ),
        poles=("defiant / distrustful", "deferential / trusting"),
        neutral=0.0,
        learning_rate=0.25,
        evidence_halflife=3.0,
    ),
    AttributeSpec(
        name="risk_tolerance",
        kind=AttributeKind.BIPOLAR,
        dynamics=Dynamics.TRAIT,
        description="Appetite for risky options when a safer one is available.",
        poles=("cautious", "reckless"),
        neutral=0.0,
        learning_rate=0.25,
        evidence_halflife=3.0,
    ),
    AttributeSpec(
        name="curiosity",
        kind=AttributeKind.UNIT,
        dynamics=Dynamics.TRAIT,
        description=(
            "Pull toward optional content: lore, side hooks, poking at things "
            "with no instrumental payoff. Absorbs 'lore_engagement'."
        ),
        poles=("incurious", "probing"),
        neutral=0.5,
        learning_rate=0.20,
        evidence_halflife=3.0,
    ),
    AttributeSpec(
        name="moral_consistency",
        kind=AttributeKind.UNIT,
        dynamics=Dynamics.TRAIT,
        description=(
            "How stably the player's value-laden choices line up over time. "
            "Raised by choices consistent with priors, lowered by contradictions."
        ),
        poles=("erratic", "principled"),
        neutral=0.5,
        learning_rate=0.15,
        evidence_halflife=4.0,
    ),
    AttributeSpec(
        name="boundary_testing",
        kind=AttributeKind.UNIT,
        dynamics=Dynamics.TRAIT,
        description=(
            "Tendency to probe the limits of the system itself — exits, "
            "fourth-wall pokes, doing the thing it told you not to."
        ),
        poles=("stays in-bounds", "probes the system"),
        neutral=0.5,
        learning_rate=0.25,
        evidence_halflife=3.0,
    ),
    AttributeSpec(
        name="failure_recovery",
        kind=AttributeKind.UNIT,
        dynamics=Dynamics.TRAIT,
        description=(
            "How the player responds to a setback: tilt/quit vs. adapt and "
            "retry. Only updated by choices made right after a failure."
        ),
        poles=("tilts / disengages", "adapts / persists"),
        neutral=0.5,
        learning_rate=0.25,
        evidence_halflife=3.0,
    ),
    AttributeSpec(
        name="frustration",
        kind=AttributeKind.UNIT,
        dynamics=Dynamics.STATE,
        description=(
            "Live affective load. Fast to rise, relaxes each turn. A STATE, not "
            "a trait — it answers 'how are they feeling right now', not 'who "
            "are they'."
        ),
        poles=("calm", "frustrated"),
        neutral=0.0,
        learning_rate=0.40,
        decay_per_turn=0.25,
        evidence_halflife=2.0,
    ),
)

#: The schema, keyed by attribute name. Import this to read the mirror's shape.
MIRROR_SCHEMA: dict[str, AttributeSpec] = {spec.name: spec for spec in _SPECS}


# --- Versioning. The schema is the contract a recorded event log reduces against.
#
# The Mirror is a *pure reduction* over an append-only event log (see
# ``mirror/log.py``): the player-state is recomputed from the log, never stored
# as authoritative. That only stays deterministic if the schema the log was
# recorded under matches the schema reducing it. So the schema is versioned, and
# a log carries the version + a structural fingerprint it was produced under.

#: Bump on ANY structural change to the axes — a new/removed axis, a changed
#: kind/dynamics/learning_rate/decay/neutral/halflife, or a renamed pole/mode.
#: A recorded event log is stamped with this; replaying a log produced under a
#: different version is refused rather than silently mis-reduced.
SCHEMA_VERSION = 1


def schema_fingerprint(schema: dict[str, AttributeSpec] | None = None) -> str:
    """A stable hash of the schema's *structure*, independent of dict ordering.

    Two processes whose axes are structurally identical produce the same
    fingerprint; any change to an axis's shape changes it. The event log records
    this alongside :data:`SCHEMA_VERSION`, so a reducer can catch a schema that
    drifted *without* a version bump — the one way a "deterministic recompute"
    could silently disagree with the log it claims to reproduce.

    Pass an explicit ``schema`` to fingerprint a hypothetical one (used in tests);
    defaults to the live :data:`MIRROR_SCHEMA`.
    """
    specs = (schema if schema is not None else MIRROR_SCHEMA).values()
    payload = [
        {
            "name": s.name,
            "kind": s.kind.value,
            "dynamics": s.dynamics.value,
            "poles": list(s.poles),
            "modes": list(s.modes),
            "neutral": s.neutral,
            "learning_rate": s.learning_rate,
            "decay_per_turn": s.decay_per_turn,
            "evidence_halflife": s.evidence_halflife,
        }
        # Sort by name so the fingerprint depends on the axis set, not its order.
        for s in sorted(specs, key=lambda spec: spec.name)
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- Provenance: every seed §6.1 feature is accounted for. ---------------------
#
# This maps the fifteen features in game_design.md §6.1 onto this schema. Each
# either lands on an axis above or is explicitly excluded with a reason. Keeping
# it in code (and tested) means the refactor stays honest: nothing was silently
# dropped, and nothing was silently duplicated.

SEED_FEATURE_MAP: dict[str, str] = {
    "combat_rate": "playstyle_mix",
    "conversation_rate": "playstyle_mix",
    "exploration_rate": "playstyle_mix",
    "loot_behavior": "playstyle_mix",  # the 'optimization' mode
    "quest_following_rate": "authority_trust",  # following the offered path = deference
    "authority_trust": "authority_trust",
    "agency_resistance": "authority_trust",  # negative pole; not its own number
    "risk_tolerance": "risk_tolerance",
    "lore_engagement": "curiosity",
    "curiosity_score": "curiosity",
    "moral_consistency": "moral_consistency",
    "system_boundary_testing": "boundary_testing",
    "failure_recovery": "failure_recovery",
    "frustration_risk": "frustration",
    # Excluded: this is the model's confidence in its own forecast, not a fact
    # about the player. It belongs to the prediction loop, not the mirror state.
    "prediction_confidence": "excluded:meta-prediction-loop",
}


@dataclass
class CoherenceReport:
    """Result of an anti-mush coherence review of the schema."""

    ok: bool
    problems: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.ok:
            return f"[COHERENT] {len(MIRROR_SCHEMA)} axes, no mush detected."
        lines = [f"[INCOHERENT] {len(self.problems)} problem(s):"]
        lines += [f"  - {p}" for p in self.problems]
        return "\n".join(lines)


def coherence_report() -> CoherenceReport:
    """Check the schema against the anti-mush invariants.

    The invariants, each guarding a specific way mush creeps in:

    1. Every axis names both of its ends (or, for a distribution, ≥2 modes).
       An axis you can't label at both ends measures nothing in particular.
    2. Ranges and neutrals are well-formed; bipolar axes rest at exactly 0.
    3. Learning rates and decays are bounded and sane.
    4. Traits don't self-relax; states do — the timescale split is explicit.
    5. Distributions are genuine budgets: ≥2 modes, neutral is uniform.
    6. Every axis carries a real description (no nameless placeholders).
    7. The seed feature map covers exactly §6.1 and points only at real axes.
    """
    problems: list[str] = []

    for name, spec in MIRROR_SCHEMA.items():
        if name != spec.name:
            problems.append(f"{name}: registry key disagrees with spec.name {spec.name!r}")
        if not spec.description.strip():
            problems.append(f"{name}: empty description (nameless axis is mush)")
        if not (0.0 < spec.learning_rate <= 1.0):
            problems.append(f"{name}: learning_rate {spec.learning_rate} not in (0, 1]")
        if not (0.0 <= spec.decay_per_turn < 1.0):
            problems.append(f"{name}: decay_per_turn {spec.decay_per_turn} not in [0, 1)")
        if spec.evidence_halflife <= 0:
            problems.append(f"{name}: evidence_halflife must be > 0")

        # Invariant 4: the trait/state timescale split must be real.
        if spec.dynamics is Dynamics.TRAIT and spec.decay_per_turn != 0.0:
            problems.append(f"{name}: TRAIT must not self-relax (decay_per_turn=0)")
        if spec.dynamics is Dynamics.STATE and spec.decay_per_turn <= 0.0:
            problems.append(f"{name}: STATE must self-relax (decay_per_turn>0)")

        if spec.kind is AttributeKind.DISTRIBUTION:
            if len(spec.modes) < 2:
                problems.append(f"{name}: distribution needs >= 2 modes")
            if spec.poles:
                problems.append(f"{name}: distribution must use modes, not poles")
            if len(set(spec.modes)) != len(spec.modes):
                problems.append(f"{name}: distribution has duplicate modes")
        else:
            low, high = value_range(spec.kind)
            if len(spec.poles) != 2 or not all(p.strip() for p in spec.poles):
                problems.append(f"{name}: scalar axis must name both poles")
            if not (low <= spec.neutral <= high):
                problems.append(f"{name}: neutral {spec.neutral} outside [{low}, {high}]")
            if spec.kind is AttributeKind.BIPOLAR and spec.neutral != 0.0:
                problems.append(f"{name}: bipolar axis must rest at 0.0")

    # Invariant 7: provenance is complete and points only at real axes.
    seed_features = set(SEED_FEATURE_MAP)
    for feature, target in SEED_FEATURE_MAP.items():
        if target.startswith("excluded:"):
            continue
        if target not in MIRROR_SCHEMA:
            problems.append(f"seed feature {feature!r} maps to unknown axis {target!r}")
    mapped_axes = {t for t in SEED_FEATURE_MAP.values() if not t.startswith("excluded:")}
    for name in MIRROR_SCHEMA:
        if name not in mapped_axes:
            problems.append(f"axis {name!r} has no seed-feature provenance")

    return CoherenceReport(ok=not problems, problems=problems)


def assert_coherent() -> None:
    """Raise ``ValueError`` if the schema violates an anti-mush invariant."""
    report = coherence_report()
    if not report.ok:
        raise ValueError(report.render())


# Fail fast at import time: a mushy schema should never be loadable.
assert_coherent()
