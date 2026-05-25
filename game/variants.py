"""Adaptation variants — the single seam the A/B feel-test toggles.

The prototype exists to answer one falsifiable question (``docs/THESIS.md``): does
content that *bends to the player* actually make the experience feel more like
"the system knows me," or is the dread carried by the rest of the shell alone?
Answering it honestly needs a **non-adaptive baseline** played through the *same*
engine, so the only thing that differs between arms is the adaptation itself.

That is what this module is. The Mirror visibly drives content in exactly two
places (``game/tests/test_session.py`` calls them out by name):

1. **across-scene branch selection** — which pre-authored framing a slot reveals
   (``game.world.Slot.pick``), and
2. **in-scene re-ordering** — surfacing the predicted choice first
   (``loop.core.Mirror.adapt``, the locked core-loop adaptation).

Together those two operations *are* the adaptation seam. A :class:`Variant`
parameterizes that one seam; the session runner calls
:meth:`Variant.select_scene` and :meth:`Variant.order_choices` **identically for
every variant** (no ``if variant == ...`` anywhere on the path), so parity
between arms is structural rather than something we remember to test in later:

* :data:`ADAPTIVE` — the real game: content is contingent on the player model.
* :data:`FIXED` — the canonical control: the seam is the **identity transform**.
  The neutral ("default") framing is always shown and choices keep their declared
  order, so nothing the player does changes the content they are offered.
* :func:`random_variant` — the **placebo**: content visibly varies (a random
  framing, a shuffled choice order) but the variation is *not driven by the
  player*. This is the blinding-grade control — if players cannot tell the
  adaptive arm from a placebo that merely changes things, the *contingency* (not
  the mere variation) is not what carries the feeling.

Crucially, what is **not** toggled here is the Reflection/legibility beat or the
Mirror's spoken observations: those are a *render* of the player model (a
reduction over logged behavior), not an adaptation, so they fire in every arm and
keep the shell UX-identical for blinding integrity. Removing them would leave the
A/B nothing to measure.

Every variant is deterministic and replayable with no LLM and no network: the
placebo's randomness is seeded with a process-stable seed
(``random.Random(str)``), so the same seed reproduces a session byte for byte.
"""

from __future__ import annotations

import random
from dataclasses import replace

from loop.core import Mirror, PlayerState, Scene

from .world import Slot

# The names a caller (CLI, playtest harness) can ask for. ``random`` additionally
# takes a seed; see :func:`build_variant`.
VARIANT_NAMES = ("adaptive", "fixed", "random")


class Variant:
    """The adaptation seam, as a strategy.

    The session runner calls both methods once per loop for whichever variant it
    was handed, never branching on the variant. Subclasses decide only whether
    the returned content depends on ``state`` (the player model). ``state`` is
    part of the uniform signature even where a baseline ignores it — that a
    baseline *does not look at it* is precisely the property under test.
    """

    name: str

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        """Choose which scene this slot reveals, plus the branch key chosen."""
        raise NotImplementedError

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        """Return the scene as it is offered to the player (choice order)."""
        raise NotImplementedError


class _Adaptive(Variant):
    """The real game: both seam operations are contingent on the player model."""

    name = "adaptive"

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        return slot.pick(state)

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        return mirror.adapt(state, scene)


class _Fixed(Variant):
    """The canonical control: the seam is the identity transform.

    The neutral framing is always revealed and the declared choice order is kept,
    so no choice the player makes ever changes the content they are offered.
    """

    name = "fixed"

    def select_scene(self, slot: Slot, state: PlayerState) -> tuple[Scene, str]:
        if slot.fixed is not None:
            return slot.fixed, "fixed"
        assert slot.variants is not None
        return slot.variants["default"], "default"

    def order_choices(self, mirror: Mirror, state: PlayerState, scene: Scene) -> Scene:
        return scene


class _Random(Variant):
    """The placebo: content varies, but the variation is not driven by the player.

    Branch framing and choice order are drawn from a seeded RNG keyed by the slot
    / scene (never by ``state``), so the experience *looks* like it is adapting
    while being entirely indifferent to how the player plays. Keying by identity
    rather than by a running RNG keeps it stateless and trivially replayable: the
    same seed yields the same session every time, in any process.
    """

    name = "random"

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

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


# The two stateless variants are singletons; the placebo is parameterized by seed.
ADAPTIVE: Variant = _Adaptive()
FIXED: Variant = _Fixed()


def random_variant(seed: int = 0) -> Variant:
    """A placebo baseline whose (player-independent) content is fixed by ``seed``."""
    return _Random(seed)


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
