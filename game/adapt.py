"""The templated adaptation layer — one toggleable transform over the loop.

The prototype ships exactly one adaptation *type*, **tendency mirroring**
(``docs/ADAPTATION.md``): the Mirror reads the player's dominant behavioral
tendency and reflects it back by *selecting and ordering* pre-authored content so
the content matching that tendency leads — never inventing, dropping, or
rewriting anything. That type has two *surfaces*, both already implemented:

* **across-scene branch selection** — which authored framing a slot reveals
  (``game.world.Slot.pick``), and
* **in-scene re-ordering** — surfacing the predicted choice first
  (``loop.core.Mirror.adapt``).

This module is the missing *producer*: it composes those two surfaces into a
single function — :func:`adapt` — that presents a whole :class:`~game.world.World`
under one read of the player model and, crucially, **emits the auditable record**
the :mod:`game.adaptation` schema was built to hold but nothing yet wrote. Every
content decision the layer makes becomes an :class:`~game.adaptation.Adaptation`
carrying the *trigger Mirror snapshot* it was a function of, and every presented
scene is run through the engine's invariant check before it is returned.

It is a *layer over the loop* in the literal sense: it sits on top of
``loop.core`` (it reads a :class:`~loop.core.PlayerState`, reorders
:class:`~loop.core.Scene` choices, never touches the engine), and it is
*toggleable* — :func:`adapt` with ``enabled=False`` is the identity layer (neutral
framing, declared order, an empty log), so a caller can flip the adaptation off
without forking a code path.

Three properties hold by construction and are pinned in
``game/tests/test_adapt.py``:

1. **Templates only, no LLM.** Content is *selected* from hand-authored framings
   and *re-ordered*; nothing is generated. The layer is pure and deterministic —
   the same ``(world, mirror)`` yields a byte-identical log.
2. **Two contrasting play styles diverge.** Because every decision is a function
   of the dominant tendency, two mirrors leaning different ways are revealed
   materially different rooms and orderings (and different logs).
3. **Every adaptation logs its trigger and passes the invariant check.** Each
   :class:`~game.adaptation.Adaptation` records its :class:`MirrorSnapshot`
   provenance, and every presented scene is validated reorder-only
   (``guardrails.invariants.validate_adaptation``) and agency-preserving before
   it leaves the layer; a violation raises rather than ships.
"""

from __future__ import annotations

from dataclasses import dataclass

from guardrails.invariants import (
    GuardrailViolation,
    Severity,
    ValidationReport,
    Violation,
    validate_adaptation,
)
from loop.core import Mirror, PlayerState, Scene

from .adaptation import Adaptation, AdaptationLog
from .variants import ADAPTIVE, FIXED
from .world import Slot, World


@dataclass(frozen=True)
class AdaptedSlot:
    """One slot, as the layer chose to present it, plus the decisions it logged.

    ``declared`` is the framing the layer *selected* (after branch selection, before
    re-ordering); ``offered`` is that scene as presented to the player (after
    re-ordering). Keeping both makes the in-scene re-ordering checkable as
    reorder-only and lets a caller see exactly what changed.
    """

    slot_key: str
    declared: Scene  # the selected framing, pre re-ordering
    offered: Scene  # as presented to the player, post re-ordering
    branch_key: str  # "fixed" / "default" / a tendency
    adaptations: tuple[Adaptation, ...]  # the records this slot produced (may be empty)

    @property
    def reordered(self) -> bool:
        """True if the layer re-ordered this scene's choices (a visible adaptation)."""
        return [c.id for c in self.offered.choices] != [c.id for c in self.declared.choices]

    @property
    def reframed(self) -> bool:
        """True if the layer revealed a tendency-tailored framing (not the neutral one)."""
        return self.branch_key not in ("fixed", "default")


@dataclass(frozen=True)
class AdaptedWorld:
    """A whole world presented under one read of the player model.

    This is what :func:`adapt` returns: the per-slot presentation plus, via
    :attr:`log`, the ordered :class:`~game.adaptation.AdaptationLog` of every
    decision the layer made — the separate "log of what the Mirror did" the
    architecture keeps beside the player's event log.
    """

    world_name: str
    slots: tuple[AdaptedSlot, ...]

    @property
    def log(self) -> AdaptationLog:
        """Every adaptation made across the world, in slot order, as one log."""
        out = AdaptationLog()
        for adapted in self.slots:
            out = out.append(*adapted.adaptations)
        return out

    def slot(self, key: str) -> AdaptedSlot:
        for adapted in self.slots:
            if adapted.slot_key == key:
                return adapted
        raise KeyError(f"no slot {key!r} in adapted world {self.world_name!r}")


def adapt(
    world: World,
    mirror: PlayerState,
    *,
    enabled: bool = True,
    engine: Mirror | None = None,
) -> AdaptedWorld:
    """Present ``world`` under the Mirror's read of the player, ``mirror``.

    The single templated adaptation, applied as one toggleable layer:

    * ``mirror`` is the Mirror's model of the player — a :class:`~loop.core.PlayerState`
      whose dominant tendency drives every decision. The read is taken *as of*
      ``mirror`` (a frozen snapshot): this answers "given the player model as it
      stands, how does the Mirror bend each room?", which is exactly the projection
      the audit log records.
    * ``enabled`` is the toggle. ``True`` runs the adaptation (branch selection +
      re-ordering, contingent on ``mirror``); ``False`` is the identity layer — the
      neutral framing and declared order, with an empty log — so the same call site
      plays the adaptation or turns it off.
    * ``engine`` is the (stateless) :class:`~loop.core.Mirror` that performs the
      re-ordering; one is created if omitted.

    Returns an :class:`AdaptedWorld`. Raises
    ``guardrails.invariants.GuardrailViolation`` if any presented scene fails the
    invariant check (reorder-only / agency-preserving) — the layer refuses to ship
    an adaptation that steps outside the type's safety contract.
    """
    engine = engine or Mirror()
    slots = tuple(
        adapt_slot(slot, mirror, enabled=enabled, engine=engine) for slot in world.slots
    )
    return AdaptedWorld(world_name=world.name, slots=slots)


def adapt_slot(
    slot: Slot,
    mirror: PlayerState,
    *,
    enabled: bool = True,
    engine: Mirror | None = None,
) -> AdaptedSlot:
    """Apply the layer to a single slot: select, re-order, check, and log.

    The per-slot primitive :func:`adapt` maps over the spine. The toggle reuses the
    canonical adaptation seam (:mod:`game.variants`) so there is one decision path,
    not a parallel one: ``enabled`` picks :data:`~game.variants.ADAPTIVE` (the read
    is a function of ``mirror``) or :data:`~game.variants.FIXED` (the identity).
    """
    engine = engine or Mirror()
    variant = ADAPTIVE if enabled else FIXED

    declared, branch_key = variant.select_scene(slot, mirror)
    offered = variant.order_choices(engine, mirror, declared)

    # Invariant check — run on *every* presentation, not only when something
    # changed, so "always passes the invariant check" is enforced, not incidental.
    _check_invariants(slot, declared, offered)

    # Log only the decisions that actually bent content to the player: a revealed
    # tendency framing and/or a re-ordering. A neutral framing in declared order is
    # the no-lean identity — the layer made no adaptation, so it records none.
    adaptations: list[Adaptation] = []
    source_event_seq = mirror.turn_count
    if branch_key not in ("fixed", "default"):
        adaptations.append(
            Adaptation.branch_selection(
                slot.key, branch_key, state=mirror, source_event_seq=source_event_seq
            )
        )
    if [c.id for c in offered.choices] != [c.id for c in declared.choices]:
        adaptations.append(
            Adaptation.choice_reordering(
                slot.key,
                (c.id for c in offered.choices),
                state=mirror,
                source_event_seq=source_event_seq,
            )
        )

    return AdaptedSlot(
        slot_key=slot.key,
        declared=declared,
        offered=offered,
        branch_key=branch_key,
        adaptations=tuple(adaptations),
    )


def _check_invariants(slot: Slot, declared: Scene, offered: Scene) -> None:
    """Raise unless this presentation obeys the adaptation type's safety contract.

    Two bounds, the two halves of "select and order, never invent/drop/rewrite":

    * **Re-ordering is reorder-only** — ``offered`` must be ``declared`` with its
      choices merely re-ordered (``guardrails.invariants.validate_adaptation``).
    * **Branch selection preserves agency** — the framing the layer revealed must
      offer the exact same set of choices as the slot's neutral framing, so the
      Mirror reframes the room without ever removing a door (``docs/ADAPTATION.md``
      §4.2).
    """
    report = validate_adaptation(declared, offered)
    report = report.merge(_check_agency_preserved(slot, declared))
    report.raise_if_failed()


def _check_agency_preserved(slot: Slot, selected: Scene) -> ValidationReport:
    """Branch selection must not drop a door: the revealed framing offers the same
    choice set as the slot's neutral framing. A fixed slot has a single authored
    scene, so there is nothing to compare."""
    if slot.variants is None:
        return ValidationReport()
    default_ids = {c.id for c in slot.variants["default"].choices}
    selected_ids = {c.id for c in selected.choices}
    if selected_ids != default_ids:
        return ValidationReport(
            (
                Violation(
                    "ADAPTATION_PRESERVES_AGENCY",
                    Severity.ERROR,
                    f"revealed framing offers {sorted(selected_ids)}, not the slot's "
                    f"authored choice set {sorted(default_ids)}; branch selection must "
                    "reframe the room, never remove a door",
                    where=f"slot {slot.key!r}",
                ),
            )
        )
    return ValidationReport()


__all__ = [
    "AdaptedSlot",
    "AdaptedWorld",
    "GuardrailViolation",
    "adapt",
    "adapt_slot",
]
