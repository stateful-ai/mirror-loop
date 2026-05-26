"""The Mirror's pure reducer: ``events -> MirrorState``.

The locked Mirror Loop architecture (``docs/MIRROR_SCHEMA.md`` §6, the M1 brief
``docs/mirror_loop_m1_founder_brief.md``) is **append-only event log → pure
reducer → MirrorState → render**. This module is the *pure* link in that chain
and the only authoritative home of the fold. It has two responsibilities and no
others:

- :func:`reduce` — fold an iterable of :class:`~mirror.log.MirrorEvent` into a
  :class:`~mirror.state.MirrorState`, starting from a blank mirror.
- :func:`scan` — yield the running state after each event, so any past turn can
  be reconstructed verbatim.

Purity is a hard architectural rule, not a stylistic preference. The future
``mirror/loop.py`` will own all of the impure session machinery (IO, randomness,
scheduling). To keep the reducer falsifiably pure — and to keep replay
byte-identical under seed (``docs/mirror_loop_m1_founder_brief.md`` Definition
of Done §4) — **this module imports nothing from** ``mirror/loop.py``. The
acceptance criterion is enforced by a test that reads this file's source.

The event types themselves live in :mod:`mirror.log` (where the persisted log
container also lives). To avoid a runtime import cycle while still giving the
reducer a typed signature, the import is performed under ``TYPE_CHECKING``:
events only need to expose ``apply_to(state)`` at runtime, which both event
types already do.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

from mirror.state import MirrorState

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from mirror.log import MirrorEvent


def reduce(events: Iterable["MirrorEvent"]) -> MirrorState:
    """Fold an event log into a player-state, deterministically.

    Starts from a blank mirror (every axis at neutral, confidence 0) and applies
    each event in order. Pure with respect to its input: it never mutates the
    events and builds a fresh :class:`MirrorState`, so two reductions of the
    same log produce equal states with equal snapshots — the replay-determinism
    contract.

    A malformed event raises (exactly as :meth:`MirrorState.apply_choice` does)
    rather than being silently absorbed: a corrupt log fails loudly instead of
    yielding a quietly-wrong recomputation.

    This bare function does not check the schema version. Reduce through
    :meth:`mirror.log.EventLog.reduce` to also get the version/fingerprint guard.
    """
    state = MirrorState.new()
    for event in events:
        event.apply_to(state)
    return state


def scan(events: Iterable["MirrorEvent"]) -> Iterator[MirrorState]:
    """Yield the player-state after each event (the running reductions).

    The initial blank state is not yielded; the first item is the state after
    the first event, and the last equals :func:`reduce` of the whole log. Each
    yielded state is an independent deep copy, so holding on to an earlier one
    is safe — it is a true snapshot of the Mirror as of that turn, not a live
    reference into the final state.
    """
    state = MirrorState.new()
    for event in events:
        event.apply_to(state)
        yield copy.deepcopy(state)
