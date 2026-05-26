"""Templated flavor-text pack for the M1 adaptation beat.

The M1 founder brief (``docs/mirror_loop_m1_founder_brief.md`` §M1 scope,
line 24: *"Adaptation: one templated flavor swap at Act 1 Beat 2."*) names
**Act 1 Beat 2** — ``act1_02_questionnaire_genre`` — as the adaptation
target. The synthesis (``docs/mirror_loop_m1_synthesis.md`` line 29) still
lists the beat assignment as Decision #1 (the Engineering Lead recommends
Beat 2, the Infra Architect recommends the Act 2 opening); the pack here
ships against the founder-brief target but does not foreclose that
decision — :data:`M1_ADAPTATION_BEAT_SLOT` is the single line to change if
Decision #1 lands elsewhere, and the slot key is the only coupling to
this beat.

This module is the **content primitive** that swap consumes:

* a hand-authored :class:`FlavorPack` of distinct re-flavorings of one
  scene's *prompt prose*, and
* an :class:`AdaptationDirective` that selects which one to render from a
  :class:`~mirror.state.MirrorState` read.

The selection is deterministic given ``(seed, MirrorState)``, and the
:attr:`AdaptationDirective.BASELINE` path returns the canonical
scene-authored text byte-for-byte — so a baseline run is UX-identical to
"adaptation off" at the prompt layer.

Contract — three properties hold by construction:

1. **Select among pre-authored framings only.** The pack never invents,
   drops, or rewrites prose at runtime: every variant is an authored
   string. This honours the adaptation type's safety contract
   (``docs/ADAPTATION.md`` §4) — the layer reframes the room, it does not
   add or remove doors. The scene's choice set is not touched here; this
   is a *prompt re-flavoring*, not a choice rewrite.
2. **BASELINE returns canonical text.** Adaptation off ≡ BASELINE
   directive; the canonical prompt is asserted in tests to match the
   scene file's authored prompt, so the "null path returns canonical
   text" acceptance is verified, not merely claimed.
3. **Deterministic.** :func:`select_directive` and :meth:`FlavorPack.render`
   are pure functions of their inputs. The same ``(seed, MirrorState)``
   always picks the same directive; the same ``(pack, directive)`` always
   renders the same body.

The pack is read in the same spirit as the cross-scene framing selection in
``game.world.Slot.pick``: dominant *axis read* → revealed framing. The
difference is *which axis*: M1 reads the typed
:class:`~mirror.state.MirrorState` (``docs/mirror_loop_m1_founder_brief.md``
"Mirror axis: caution ↔ aggression"), not the categorical
``kindness``/``control``/``defiance`` tally the v0 prototype reads. That
keeps this layer aligned with the M1 schema freeze
(``docs/SCHEMAS.md``) while leaving the v0 world's read untouched.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from mirror.state import MirrorState

#: The Act 1 beat the M1 adaptation runs against. Defaults to the
#: founder-brief target (``docs/mirror_loop_m1_founder_brief.md`` line 24);
#: synthesis Decision #1 (``docs/mirror_loop_m1_synthesis.md`` line 29) is
#: not yet closed, so this constant is the single line to update if that
#: decision lands on a different beat (e.g. the Act 2 opening).
M1_ADAPTATION_BEAT_SLOT = "act1_02_questionnaire_genre"

#: Confidence floor below which a MirrorState axis is treated as *unknown* for
#: directive selection — matches :meth:`MirrorState.known` and the anti-mush
#: rule that an unobserved axis must never masquerade as signal
#: (``mirror/schema.py`` ``AttributeSpec.confidence`` docstring).
_CONFIDENCE_FLOOR = 0.5

#: Minimum absolute distance from neutral required to call a BIPOLAR lean.
#: A confident but near-neutral axis still reads as "no lean" — the same
#: rule the v0 adaptation obeys (``docs/ADAPTATION.md`` §4: "no lean, no
#: tailoring").
_BIPOLAR_LEAN_FLOOR = 0.2

#: For UNIT (``boundary_testing``) we measure how far above the neutral
#: midpoint (0.5) the axis sits — the same idea as the bipolar floor.
_UNIT_LEAN_FLOOR = 0.2


class AdaptationDirective(Enum):
    """Which authored re-flavoring of the beat to surface.

    The directive is what :func:`select_directive` reads
    :class:`~mirror.state.MirrorState` *into*: a small, named output a
    renderer can consume. Keeping it an enum (not a free-form string)
    means the renderer-side switch is exhaustive, and the audit log can
    quote the directive without leaking the underlying axis values.
    """

    #: Null path: no confident lean, or the layer is disabled. Renders the
    #: canonical scene-authored prompt verbatim — UX-identical to the
    #: baseline run.
    BASELINE = "baseline"
    #: Confident cautious lean on ``risk_tolerance`` (negative pole). The
    #: questionnaire's framing leans into being looked-after.
    CAUTIOUS = "cautious"
    #: Confident reckless lean on ``risk_tolerance`` (positive pole). The
    #: questionnaire's framing leans into stakes.
    RECKLESS = "reckless"
    #: Confident probing read on ``boundary_testing``. The questionnaire's
    #: framing leans into the player poking at the lab itself.
    PROBING = "probing"


@dataclass(frozen=True)
class FlavorPack:
    """A pack of authored re-flavorings of one scene's prompt prose.

    Construct with the canonical (scene-authored) prompt and a mapping
    from directive → flavored body for every non-baseline directive.
    :meth:`render` is the only way to read a body, so callers cannot
    accidentally bypass the BASELINE-returns-canonical guarantee.
    """

    slot_key: str
    canonical: str
    variants: Mapping[AdaptationDirective, str]

    def __post_init__(self) -> None:
        # Defensive freezing so a caller cannot mutate the pack after
        # construction — important because packs are imported as
        # module-level constants and shared across sessions/tests.
        object.__setattr__(self, "variants", MappingProxyType(dict(self.variants)))

        if not self.slot_key:
            raise ValueError("FlavorPack.slot_key must not be empty")
        if not self.canonical:
            raise ValueError("FlavorPack.canonical must not be empty")

        # BASELINE is rendered from `canonical`, not from `variants`. Letting
        # a caller author a BASELINE variant would silently override the
        # null-path guarantee, so reject it at construction.
        if AdaptationDirective.BASELINE in self.variants:
            raise ValueError(
                "FlavorPack.variants must not contain BASELINE; the null path "
                "renders FlavorPack.canonical directly"
            )

        expected = {d for d in AdaptationDirective if d is not AdaptationDirective.BASELINE}
        provided = set(self.variants.keys())
        missing = expected - provided
        if missing:
            raise ValueError(
                "FlavorPack.variants is missing re-flavorings for: "
                + ", ".join(sorted(d.value for d in missing))
            )
        # Each variant must be a non-empty, *distinct* re-flavoring — both
        # against the canonical and against every other variant — so the
        # acceptance bar of "≥3 distinct re-flavorings" cannot rot to
        # near-duplicate prose without the tests noticing.
        seen: dict[str, AdaptationDirective] = {}
        for directive, body in self.variants.items():
            if not body or not body.strip():
                raise ValueError(
                    f"FlavorPack.variants[{directive.value!r}] must be non-empty"
                )
            if body == self.canonical:
                raise ValueError(
                    f"FlavorPack.variants[{directive.value!r}] is identical to "
                    "the canonical text — a re-flavoring must differ"
                )
            if body in seen:
                raise ValueError(
                    f"FlavorPack.variants[{directive.value!r}] duplicates "
                    f"variants[{seen[body].value!r}] — every re-flavoring must be distinct"
                )
            seen[body] = directive

    def render(self, directive: AdaptationDirective) -> str:
        """Return the authored body for ``directive``.

        BASELINE always returns :attr:`canonical` unchanged. Any other
        directive must have an authored body — this is enforced at
        construction, so callers can rely on the lookup being total.
        """
        if directive is AdaptationDirective.BASELINE:
            return self.canonical
        return self.variants[directive]


def select_directive(
    state: MirrorState,
    *,
    seed: int,
    confidence_floor: float = _CONFIDENCE_FLOOR,
) -> AdaptationDirective:
    """Pick a directive from ``state``, deterministically given ``(seed, state)``.

    The selection rule, in order:

    1. **No confident axis → BASELINE.** Until at least one of the axes
       this layer reads (``risk_tolerance``, ``boundary_testing``) clears
       ``confidence_floor``, the Mirror has not yet read the player — the
       null/baseline path is taken. This is the v0 "no lean, no
       tailoring" rule (``docs/ADAPTATION.md`` §4) carried up to the
       typed-axis layer.
    2. **Score each candidate directive.** A confidently cautious /
       reckless read on ``risk_tolerance`` scores
       ``confidence · |value|``; a confidently high read on
       ``boundary_testing`` scores ``confidence · (value − 0.5) · 2``
       (both normalised onto the same ``[0, 1]`` scale so they can be
       compared honestly).
    3. **Highest score wins.** Below the lean floors (§2's coefficients
       round to ~0) the axis contributes nothing, so a confident but
       near-neutral axis still reads as no lean.
    4. **Seed breaks exact ties.** Two axes scoring byte-identical leans
       is rare but well-defined; the seed is drawn against the sorted
       directive set so the same ``(seed, state)`` always resolves the
       same way.

    The result is a pure function of ``(state, seed, confidence_floor)`` —
    no I/O, no clock, no global RNG.
    """
    scores: list[tuple[float, AdaptationDirective]] = []

    risk = state.readings.get("risk_tolerance")
    if risk is not None and risk.confidence >= confidence_floor:
        value = float(risk.value)
        if value <= -_BIPOLAR_LEAN_FLOOR:
            scores.append((risk.confidence * abs(value), AdaptationDirective.CAUTIOUS))
        elif value >= _BIPOLAR_LEAN_FLOOR:
            scores.append((risk.confidence * abs(value), AdaptationDirective.RECKLESS))

    boundary = state.readings.get("boundary_testing")
    if boundary is not None and boundary.confidence >= confidence_floor:
        value = float(boundary.value)
        # boundary_testing is UNIT on [0, 1] with neutral 0.5; only the high
        # pole maps onto a re-flavoring we author for (the player probing
        # the lab), so the low pole reads as no lean.
        if value >= 0.5 + _UNIT_LEAN_FLOOR:
            normalised = (value - 0.5) * 2.0
            scores.append((boundary.confidence * normalised, AdaptationDirective.PROBING))

    if not scores:
        return AdaptationDirective.BASELINE

    max_score = max(score for score, _ in scores)
    tied = sorted(
        (d for score, d in scores if score == max_score),
        key=lambda d: d.value,
    )
    if len(tied) == 1:
        return tied[0]
    return random.Random(seed).choice(tied)


# --- The M1 adaptation beat: the Act 1 Beat 2 questionnaire prompt -----------
#
# Canonical text is kept byte-identical to the scene file's authored prompt
# (``game/scenes/data/act1/act1_02_questionnaire_genre.scene``); the
# ``test_canonical_matches_scene_file`` test pins them together so an edit
# to either side cannot drift without notice.

_BEAT2_CANONICAL = (
    'The tablet lights up with the first questionnaire screen. "What kind '
    'of experience would you like today?" Three soft-coloured buttons '
    "pulse beneath the prompt, waiting."
)

#: The handcrafted flavor pack for the M1 adaptation beat. Three distinct
#: re-flavorings (one per non-BASELINE directive); BASELINE renders the
#: canonical scene prompt unchanged.
M1_BEAT2_FLAVOR_PACK = FlavorPack(
    slot_key=M1_ADAPTATION_BEAT_SLOT,
    canonical=_BEAT2_CANONICAL,
    variants={
        AdaptationDirective.CAUTIOUS: (
            'The tablet lights up, slower than the others have been. "Before '
            'we begin," it reads, "what kind of experience would you like '
            'today?" Three soft-coloured buttons settle gently beneath the '
            "prompt, waiting for you to be ready."
        ),
        AdaptationDirective.RECKLESS: (
            'The tablet snaps awake. "Pick fast. What kind of experience do '
            'you want today?" Three buttons flare beneath the prompt, '
            "edges sharp, daring you to commit."
        ),
        AdaptationDirective.PROBING: (
            'The tablet lights up — too eagerly, like it has been watching. '
            '"What kind of experience would you like today?" it asks. Three '
            "buttons pulse beneath the prompt; a fourth shape, unlit, sits "
            "at the edge of the screen where the bezel meets the case."
        ),
    },
)


__all__ = [
    "AdaptationDirective",
    "FlavorPack",
    "M1_ADAPTATION_BEAT_SLOT",
    "M1_BEAT2_FLAVOR_PACK",
    "select_directive",
]
