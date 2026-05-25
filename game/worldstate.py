"""WorldState — where the player is in the world spine, as a pure reduction.

Locked architecture (company memory ``mem_20260524T231037Z_73efd2``;
``docs/MIRROR_SCHEMA.md`` §6): the append-only event log is the **only** source of
truth, and *both* the Mirror and the world-state are **pure reductions** over it,
never persisted as authoritative derived state. ``mirror/state.py`` +
``mirror/log.py`` reduce the log into the player *model*; this module reduces the
**same** log into the player's *position* in the handcrafted spine
(``game/world.py``): how many loops are done, which slot comes next, and which
scene was actually played at each completed loop.

It folds over the existing :class:`~mirror.log.ChoiceObserved` events — one
recorded choice advances the world by exactly one slot, in spine order.
:class:`~mirror.log.TurnAdvanced` events are decay boundaries for the Mirror and
carry no world position (a turn can pass with no choice), so they are skipped.

Like the Mirror schema, the serialized shape is a contract a recorded log is
replayed against, so it is **versioned**: :data:`WORLDSTATE_SCHEMA_VERSION` bumps
on any incompatible change, and a snapshot written under another version is
refused at load rather than silently mis-restored.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from mirror.log import ChoiceObserved, MirrorEvent

from .world import World

#: Bump on any incompatible change to the serialized :class:`WorldState` shape.
#: A persisted snapshot stamped with a different version is rejected at
#: :meth:`WorldState.from_dict` rather than silently mis-restored.
WORLDSTATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VisitedSlot:
    """One completed loop: the slot the player played and the choice they made.

    Recorded per :class:`~mirror.log.ChoiceObserved` so a reduced world-state
    lists, in order, exactly which rooms the player walked and what they did
    there — the spine's audit trail, derived (never stored as authority).
    """

    #: The world-spine slot key this loop resolved to (``world.slots[i].key``).
    #: Equal to the event's ``scene_id`` when the log recorded one.
    slot_key: str
    #: The id of the choice the player made in this slot.
    choice_id: str


@dataclass(frozen=True)
class WorldState:
    """The player's position in a :class:`~game.world.World`, as of some log.

    Pure reduction, never authoritative: hold it only as a *view* of the event
    log, recomputed with :meth:`reduce`. Two reductions of the same log against
    the same world are byte-identical.
    """

    #: Which world this is a position within (``World.name``); carried so a
    #: serialized snapshot is self-describing and a mismatched world is caught.
    world_name: str
    #: Number of loops completed = number of slots advanced. ``0`` means the
    #: player is at the first slot and has not chosen yet. Also the index of the
    #: *next* slot to play.
    position: int = 0
    #: One :class:`VisitedSlot` per completed loop, in play order. Always
    #: ``len(visited) == position``.
    visited: tuple[VisitedSlot, ...] = ()

    def is_complete(self, world: World) -> bool:
        """True once every slot in ``world`` has been played."""
        return self.position >= world.length

    def next_slot_key(self, world: World) -> str | None:
        """The key of the slot to play next, or ``None`` if the spine is done."""
        if self.is_complete(world):
            return None
        return world.slots[self.position].key

    # --- the reduction -------------------------------------------------------

    @classmethod
    def reduce(cls, world: World, events: Iterable[MirrorEvent]) -> "WorldState":
        """Fold an event log into a world position, deterministically.

        Each :class:`~mirror.log.ChoiceObserved` advances the spine by one slot,
        in declared order; :class:`~mirror.log.TurnAdvanced` events are skipped
        (they move the Mirror, not the world). The fold fails loudly rather than
        silently producing a wrong position:

        * a choice event past the last slot raises (the log overran the spine);
        * a choice whose recorded ``scene_id`` disagrees with the slot it landed
          on raises (the log was recorded against a different world).
        """
        position = 0
        visited: list[VisitedSlot] = []
        for event in events:
            if not isinstance(event, ChoiceObserved):
                continue
            if position >= world.length:
                raise ValueError(
                    f"event log overran the {world.name!r} spine: a choice was "
                    f"recorded after all {world.length} slots were played"
                )
            slot = world.slots[position]
            if event.scene_id is not None and event.scene_id != slot.key:
                raise ValueError(
                    f"choice event scene_id {event.scene_id!r} does not match "
                    f"slot {position} ({slot.key!r}) of world {world.name!r}: the "
                    "log was recorded against a different world spine"
                )
            visited.append(VisitedSlot(slot_key=slot.key, choice_id=event.choice_id))
            position += 1
        return cls(world_name=world.name, position=position, visited=tuple(visited))

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict:
        """A JSON-serializable snapshot, stamped with the schema version."""
        return {
            "schema_version": WORLDSTATE_SCHEMA_VERSION,
            "world_name": self.world_name,
            "position": self.position,
            "visited": [
                {"slot_key": v.slot_key, "choice_id": v.choice_id}
                for v in self.visited
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldState":
        """Rebuild a snapshot from :meth:`to_dict` output, guarding the version."""
        version = data.get("schema_version")
        if version != WORLDSTATE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported world-state schema version {version!r} "
                f"(this build reads v{WORLDSTATE_SCHEMA_VERSION})"
            )
        visited = tuple(
            VisitedSlot(slot_key=v["slot_key"], choice_id=v["choice_id"])
            for v in data["visited"]
        )
        position = data["position"]
        if position != len(visited):
            raise ValueError(
                f"corrupt world-state: position {position} != "
                f"{len(visited)} visited slots"
            )
        return cls(
            world_name=data["world_name"],
            position=position,
            visited=visited,
        )

    def to_json(self) -> str:
        """Serialize to an indented, key-sorted JSON string."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "WorldState":
        """Rebuild from a JSON string written by :meth:`to_json`."""
        return cls.from_dict(json.loads(text))
