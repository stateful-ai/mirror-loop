"""The single adaptation seam — one pipeline, with the adaptation as an *injected
layer* so the baseline is the adaptive game minus that layer, by construction.

The prototype exists to answer one falsifiable question (``docs/THESIS.md``): does
content that *bends to the player* actually make the experience feel more like
"the system knows me," or is the dread carried by the rest of the shell alone?
Answering it honestly needs a **non-adaptive baseline** played through the *same*
engine, so the only thing that differs between arms is the adaptation itself.

The architecture principle this module enforces is therefore:

    *Baseline and adaptive share one adaptation seam where baseline is the
    identity transform, so parity is structural rather than tested-in after the
    fact — never a forked code path.*

To make that **structural** (not a property two parallel classes happen to
share), the seam and the adaptation are split:

* :class:`Variant` is the seam — the single pipeline the session runner drives.
  There is exactly one implementation of :meth:`~Variant.select_scene` and
  :meth:`~Variant.order_choices`; every arm runs the *same* code.
* :class:`AdaptationLayer` is the one thing injected into that seam — the layer.
  An arm *is* the seam plus a layer, so two arms can differ only in their layer.

The Mirror visibly drives content in exactly two places (the two surfaces of the
one adaptation type, ``docs/ADAPTATION.md`` §1), and the layer owns both:

1. **across-scene branch selection** — which pre-authored framing a slot reveals
   (``game.world.Slot.pick``), and
2. **in-scene re-ordering** — surfacing the predicted choice first
   (``loop.core.Mirror.adapt``, the locked core-loop adaptation).

The shipped layers are:

* :data:`TENDENCY_MIRRORING` — the real adaptation: content is contingent on the
  player model (the :data:`ADAPTIVE` arm).
* :data:`NO_LAYER` — the **off switch**: the identity transform. The neutral
  ("default") framing is always shown and choices keep their declared order, so
  nothing the player does changes the content they are offered. This *is* the
  canonical control (the :data:`FIXED` arm), and it is what
  :meth:`Variant.without_layer` injects — so ``ADAPTIVE.without_layer()`` is the
  baseline, byte-for-byte, for the same ``(seed, inputs)``.
* a **placebo** layer (:func:`random_variant`): content visibly varies (a random
  framing, a shuffled choice order) but the variation is *not driven by the
  player*. This is the blinding-grade control — if players cannot tell the
  adaptive arm from a placebo that merely changes things, the *contingency* (not
  the mere variation) is not what carries the feeling.

Because the runner calls :meth:`Variant.select_scene` and
:meth:`Variant.order_choices` **identically for every variant** (no
``if variant == ...`` anywhere on the path) and those methods simply delegate to
the injected layer, ``baseline == adaptive minus the layer`` holds by
construction — pinned end to end in ``game/tests/test_seam.py``.

Crucially, what is **not** part of the layer is the Reflection/legibility beat or
the Mirror's spoken observations: those are a *render* of the player model (a
reduction over logged behavior), not an adaptation, so they fire in every arm and
keep the shell UX-identical for blinding integrity. Removing them would leave the
A/B nothing to measure.

Every variant is deterministic and replayable with no LLM and no network: the
placebo's randomness is seeded with a process-stable seed
(``random.Random(str)``), so the same seed reproduces a session byte for byte.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from loop.core import Mirror, PlayerState, Scene

from .world import Slot

# The names a caller (CLI, playtest harness) can ask for. ``random`` additionally
# takes a seed; see :func:`build_variant`.
VARIANT_NAMES = ("adaptive", "fixed", "random")


class AdaptationLayer:
    """The adaptation, as an injectable layer — the *only* per-arm difference.

    A layer owns both surfaces of the one adaptation type: which framing a slot
    reveals (:meth:`select_scene`) and the order a scene's choices are offered in
    (:meth:`order_choices`). The seam (:class:`Variant`) holds the shared
    pipeline; injecting a different layer is the whole of what makes one arm
    differ from another. ``state`` is part of both signatures even where a
    baseline ignores it — that a baseline *does not look at it* is precisely the
    property under test.
    """

    name: str

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        """Choose which scene this slot reveals, plus the branch key chosen."""
        raise NotImplementedError

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        """Return the scene as it is offered to the player (choice order)."""
        raise NotImplementedError


@dataclass(frozen=True)
class _TendencyMirroring(AdaptationLayer):
    """The real adaptation: both surfaces are contingent on the player model."""

    name = "tendency-mirroring"

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        return slot.pick(state)

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        return mirror.adapt(state, scene)


@dataclass(frozen=True)
class _NoLayer(AdaptationLayer):
    """The off switch: the identity transform — the adaptive game *minus* the layer.

    The neutral framing is always revealed and the declared choice order is kept,
    so no choice the player makes ever changes the content they are offered. This
    is the canonical baseline, and what :meth:`Variant.without_layer` injects.
    """

    name = "off"

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        if slot.fixed is not None:
            return slot.fixed, "fixed"
        assert slot.variants is not None
        return slot.variants["default"], "default"

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        return scene


@dataclass(frozen=True)
class _Placebo(AdaptationLayer):
    """The placebo: content varies, but the variation is not driven by the player.

    Branch framing and choice order are drawn from a seeded RNG keyed by the slot
    / scene (never by ``state``), so the experience *looks* like it is adapting
    while being entirely indifferent to how the player plays. Keying by identity
    rather than by a running RNG keeps it stateless and trivially replayable: the
    same seed yields the same session every time, in any process.
    """

    name = "placebo"
    seed: int = 0

    def _rng(self, *parts: object) -> random.Random:
        # A string seed is hashed deterministically (sha512-based), so this is
        # stable across processes regardless of PYTHONHASHSEED.
        return random.Random(":".join(str(p) for p in (self.seed, *parts)))

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        if slot.fixed is not None:
            return slot.fixed, "fixed"
        assert slot.variants is not None
        # Draw from the same authored framings the adaptive arm could reveal (the
        # tendency variants), so the placebo is indistinguishable in surface from
        # real adaptation — just decoupled from the player.
        keys = sorted(k for k in slot.variants if k != "default")
        if not keys:
            return slot.variants["default"], "default"
        key = self._rng("scene", slot.key).choice(keys)
        return slot.variants[key], key

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        choices = list(scene.choices)
        self._rng("order", scene.id).shuffle(choices)
        return replace(scene, choices=tuple(choices))


# The two stateless layers are singletons; the placebo is parameterized by seed.
#: The real adaptation type (``docs/ADAPTATION.md``), powering the adaptive arm.
TENDENCY_MIRRORING: AdaptationLayer = _TendencyMirroring()
#: The off switch / identity transform — the baseline is the seam with this layer.
NO_LAYER: AdaptationLayer = _NoLayer()


@dataclass(frozen=True)
class Variant:
    """The adaptation seam: one shared pipeline plus the injected layer.

    The session runner calls :meth:`select_scene` then :meth:`order_choices` once
    per loop for whichever variant it was handed, *never branching on the
    variant*. Both methods simply delegate to :attr:`layer`, so the seam is the
    same code for every arm and an arm differs from another only in its layer.
    That is what makes ``baseline == adaptive minus the layer`` a structural
    guarantee rather than something to remember to test.
    """

    name: str
    layer: AdaptationLayer

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        """Choose which scene this slot reveals, plus the branch key chosen."""
        return self.layer.select_scene(slot, state)

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        """Return the scene as it is offered to the player (choice order)."""
        return self.layer.order_choices(mirror, state, scene)

    @property
    def seed(self) -> int:
        """The seed needed to reconstruct this arm via :func:`build_variant`.

        Only the placebo layer varies on a seed; every other layer ignores it, so
        this is ``0`` for them. It is the inverse of ``build_variant(name,
        seed=...)``, letting a caller persist a complete description of the arm.
        """
        return int(getattr(self.layer, "seed", 0))

    def without_layer(self) -> "Variant":
        """This arm with the adaptation layer removed — the structural baseline.

        Returns the *same seam* with :data:`NO_LAYER` (the identity transform)
        injected. ``ADAPTIVE.without_layer()`` is therefore the non-adaptive
        control by construction: same pipeline, layer set to the no-op, so its
        output is byte-identical to :data:`FIXED` for the same ``(seed, inputs)``
        (differing only in the cosmetic arm :attr:`name`).
        """
        return replace(self, layer=NO_LAYER)


#: The real game: content is contingent on the player model.
ADAPTIVE: Variant = Variant(name="adaptive", layer=TENDENCY_MIRRORING)
#: The canonical control: the seam with the layer turned off (identity transform).
FIXED: Variant = Variant(name="fixed", layer=NO_LAYER)


def random_variant(seed: int = 0) -> Variant:
    """A placebo baseline whose (player-independent) content is fixed by ``seed``."""
    return Variant(name="random", layer=_Placebo(seed))


def build_variant(name: str, *, seed: int = 0) -> Variant:
    """Resolve a variant name (the single A/B toggle) to a :class:`Variant`.

    ``seed`` is used only by ``"random"``. Raises ``ValueError`` for any other
    name so a typo fails loudly rather than silently picking an arm.
    """
    if name == "adaptive":
        return ADAPTIVE
    if name == "fixed":
        return FIXED
    if name == "random":
        return random_variant(seed)
    raise ValueError(
        f"unknown variant {name!r}; choose one of: {', '.join(VARIANT_NAMES)}"
    )
