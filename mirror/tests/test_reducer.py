"""Property tests for :mod:`mirror.reducer` — the pure ``events → MirrorState``.

These pin down the contract the rest of Mirror Loop relies on:

- **Empty-log identity.** ``reduce([])`` is a blank mirror that knows nothing —
  every axis at neutral, confidence 0. The Mirror starts ignorant; the log is
  the only thing that can move it.
- **Determinism.** For any well-formed event sequence, repeated reductions
  produce equal states *and* byte-identical JSON snapshots. This is what makes
  the M1 "byte-identity replay under seed" gate
  (``docs/mirror_loop_m1_founder_brief.md`` §DoD-4) implementable at all.
- **Purity.** Reducing does not mutate its input; the events are frozen facts.
- **Fold law.** ``reduce(prefix + [event])`` equals applying ``event`` to a
  copy of ``reduce(prefix)`` — the reducer is a left fold over ``apply_to``.
- **Structural isolation.** The reducer module imports nothing from
  ``mirror/loop.py``. This is the architectural rule the M1 brief locks in,
  so the pure fold can't get quietly entangled with the future impure
  session/loop module.

There is no third-party property framework on the test runner, so the random
"property" cases are generated deterministically with :mod:`random` seeded per
test. Each test runs many cases over varied event sequences to give the
properties real coverage.
"""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

import mirror.reducer as reducer_module
from mirror.log import (
    ChoiceObserved,
    EventLog,
    TurnAdvanced,
    log_from_choices,
)
from mirror.reducer import reduce, scan
from mirror.schema import MIRROR_SCHEMA, AttributeKind, Dynamics
from mirror.state import Choice, MirrorState, Signal


# --- random event generation --------------------------------------------------
# A property test is only as good as the distribution it samples. We exercise
# every axis kind/dynamic, mixed turn boundaries, and varying weights — the
# axes the reducer's behavior actually depends on.


_SCALAR_AXES = tuple(
    name for name, spec in MIRROR_SCHEMA.items() if spec.kind is not AttributeKind.DISTRIBUTION
)
_DISTRIBUTION_AXES = tuple(
    name for name, spec in MIRROR_SCHEMA.items() if spec.kind is AttributeKind.DISTRIBUTION
)


def _random_signal(rng: random.Random) -> Signal:
    """One legal Signal for a randomly chosen axis."""
    if rng.random() < 0.7 or not _DISTRIBUTION_AXES:
        name = rng.choice(_SCALAR_AXES)
        spec = MIRROR_SCHEMA[name]
        low, high = (0.0, 1.0) if spec.kind is AttributeKind.UNIT else (-1.0, 1.0)
        # Cover the full legal range, including the endpoints.
        target = rng.choice([low, high, rng.uniform(low, high)])
        # Weight strictly inside (0, 1]; never zero or above one.
        weight = rng.choice([1.0, rng.uniform(0.05, 1.0)])
        return Signal.toward(name, target=target, weight=weight)
    name = rng.choice(_DISTRIBUTION_AXES)
    spec = MIRROR_SCHEMA[name]
    return Signal.spend(name, mode=rng.choice(spec.modes), weight=rng.uniform(0.1, 1.0))


def _random_choice_event(rng: random.Random) -> ChoiceObserved:
    n_signals = rng.randint(1, 4)
    return ChoiceObserved(
        choice_id=f"c_{rng.randrange(10_000)}",
        signals=tuple(_random_signal(rng) for _ in range(n_signals)),
    )


def _random_events(rng: random.Random, n: int) -> tuple:
    """A mix of ChoiceObserved and TurnAdvanced events of length ``n``."""
    events = []
    for _ in range(n):
        if rng.random() < 0.35:
            events.append(TurnAdvanced())
        else:
            events.append(_random_choice_event(rng))
    return tuple(events)


# --- architectural rule -------------------------------------------------------


def test_reducer_module_does_not_import_from_mirror_loop():
    """The reducer must be pure: no import of the (future) impure loop module.

    This is the acceptance criterion verbatim. Enforced by reading the source
    so a refactor can't accidentally re-introduce the coupling that the M1
    brief explicitly disallows.
    """
    src = Path(reducer_module.__file__).read_text()
    assert "from mirror.loop" not in src
    assert "import mirror.loop" not in src
    # And the actually-imported module set excludes ``mirror.loop``: a runtime
    # check, not just a textual one.
    import sys

    assert "mirror.loop" not in sys.modules or sys.modules["mirror.loop"] is None


# --- empty-log identity -------------------------------------------------------


def test_empty_log_reduces_to_blank_mirror():
    state = reduce([])
    assert state == MirrorState.new()
    # Every axis sits at its neutral with zero confidence — nothing is "known".
    for name, reading in state.readings.items():
        assert reading.evidence_count == 0.0, name
        assert reading.confidence == 0.0, name
    assert state.known() == {}


def test_empty_log_identity_is_idempotent_and_independent():
    a = reduce([])
    b = reduce([])
    # Equal value, but independent objects: mutating one must not touch the
    # other. This is what makes the "blank mirror" identity safe to rely on.
    assert a == b
    assert a is not b
    a.readings[next(iter(a.readings))].evidence_count = 99.0
    assert b.readings[next(iter(b.readings))].evidence_count == 0.0


def test_empty_log_identity_holds_for_every_iterable_shape():
    blank = MirrorState.new()
    assert reduce([]) == blank
    assert reduce(()) == blank
    assert reduce(iter([])) == blank
    assert reduce(e for e in ()) == blank


# --- determinism (the property heart of the test file) -----------------------


@pytest.mark.parametrize("seed", list(range(40)))
def test_reduce_is_deterministic_across_repeated_invocations(seed: int):
    """``reduce(events) == reduce(events)`` for arbitrary well-formed inputs."""
    rng = random.Random(seed)
    events = _random_events(rng, n=rng.randint(0, 30))

    first = reduce(events)
    # Run it several more times — repeated reduction must be value-equal AND
    # produce byte-identical JSON snapshots (the byte-identity replay gate).
    snapshot = json.dumps(first.snapshot(), sort_keys=True)
    for _ in range(4):
        again = reduce(events)
        assert again == first
        assert json.dumps(again.snapshot(), sort_keys=True) == snapshot


@pytest.mark.parametrize("seed", list(range(20)))
def test_two_independently_built_identical_logs_reduce_to_equal_states(seed: int):
    """Determinism is about the event sequence, not the object identity."""
    rng_a = random.Random(seed)
    rng_b = random.Random(seed)
    events_a = _random_events(rng_a, 20)
    events_b = _random_events(rng_b, 20)

    assert events_a == events_b  # the generators agree at the data level
    assert reduce(events_a) == reduce(events_b)
    assert reduce(events_a).snapshot() == reduce(events_b).snapshot()


@pytest.mark.parametrize("seed", list(range(20)))
def test_reduction_does_not_mutate_the_input_events(seed: int):
    rng = random.Random(seed)
    events = _random_events(rng, 25)
    before = tuple(copy.deepcopy(e) for e in events)
    reduce(events)
    assert events == before  # frozen dataclasses; assert it nonetheless


# --- fold law: reduce(prefix + [e]) == apply(e, reduce(prefix)) --------------


@pytest.mark.parametrize("seed", list(range(20)))
def test_reduce_is_a_left_fold_over_apply_to(seed: int):
    """Stepwise: appending an event composes with the reducer the way a fold does.

    This is the algebraic property that lets ``scan`` exist and lets a session
    persist mid-stream and resume by appending — without that property the
    "as of turn t" snapshots would not be a function of the prefix alone.
    """
    rng = random.Random(seed)
    events = _random_events(rng, rng.randint(1, 20))
    prefix, tail = events[:-1], events[-1]

    stepped = reduce(prefix)
    tail.apply_to(stepped)

    assert reduce(events) == stepped


# --- scan: running reductions ------------------------------------------------


@pytest.mark.parametrize("seed", list(range(15)))
def test_scan_yields_one_state_per_event_and_ends_at_reduce(seed: int):
    rng = random.Random(seed)
    events = _random_events(rng, rng.randint(0, 15))
    states = list(scan(events))
    assert len(states) == len(events)
    if events:
        assert states[-1] == reduce(events)


def test_scan_snapshots_are_independent_deep_copies():
    # Same shape used in test_log, but exercised against the reducer module
    # directly so we know the contract belongs to the reducer, not the log.
    log = log_from_choices([
        Choice("question", signals=(Signal.toward("authority_trust", -1.0),)),
        Choice("challenge", signals=(Signal.toward("authority_trust", -1.0),)),
    ])
    states = list(scan(log.events))
    first_snapshot = copy.deepcopy(states[0].snapshot())
    # Drive the final state further by mutating its readings; the earlier
    # snapshot must be unaffected.
    states[-1].readings["authority_trust"].value = 0.99
    assert states[0].snapshot() == first_snapshot


# --- structural invariants of any reduced state ------------------------------


@pytest.mark.parametrize("seed", list(range(20)))
def test_only_signaled_axes_can_gain_confidence(seed: int):
    """Anti-mush guarantee: confidence > 0 implies the axis had evidence.

    Property: for every axis in the reduced state, ``confidence > 0`` only if
    that axis appears as a signal target in at least one ChoiceObserved event.
    This isn't merely a state.py contract — the reducer must not invent
    evidence as it folds.
    """
    rng = random.Random(seed)
    events = _random_events(rng, 30)
    state = reduce(events)

    signaled = {
        s.attribute
        for e in events
        if isinstance(e, ChoiceObserved)
        for s in e.signals
    }
    for name, reading in state.readings.items():
        if reading.confidence > 0.0:
            assert name in signaled, name


@pytest.mark.parametrize("seed", list(range(20)))
def test_scalar_values_stay_within_legal_range(seed: int):
    """No reduction sequence can drive a scalar axis outside its declared range."""
    rng = random.Random(seed)
    events = _random_events(rng, 50)
    state = reduce(events)
    for name, spec in MIRROR_SCHEMA.items():
        reading = state.readings[name]
        if spec.kind is AttributeKind.UNIT:
            assert 0.0 <= reading.value <= 1.0, name
        elif spec.kind is AttributeKind.BIPOLAR:
            assert -1.0 <= reading.value <= 1.0, name
        else:
            # Distribution: every component in [0,1] and they sum to ~1.
            assert all(0.0 <= p <= 1.0 for p in reading.value), name
            assert abs(sum(reading.value) - 1.0) < 1e-9, name


def test_only_turn_advanced_leaves_traits_at_neutral():
    """TRAIT axes don't self-relax. A log of pure TurnAdvanced events touches
    only STATE axes — TRAITs stay at neutral with zero evidence."""
    events = (TurnAdvanced(),) * 25
    state = reduce(events)
    for name, spec in MIRROR_SCHEMA.items():
        reading = state.readings[name]
        if spec.dynamics is Dynamics.TRAIT:
            assert reading.value == spec.neutral_value(), name
            assert reading.evidence_count == 0.0, name
            assert reading.confidence == 0.0, name


# --- malformed inputs fail loudly --------------------------------------------


def test_malformed_signal_in_log_raises_during_reduction():
    """A corrupt log must not silently produce a "different but plausible"
    state — the reducer raises, matching the contract of ``apply_choice``."""
    events = (ChoiceObserved("bad", signals=(Signal.toward("not_an_axis", 1.0),)),)
    with pytest.raises(KeyError):
        reduce(events)


def test_out_of_range_target_in_log_raises_during_reduction():
    events = (ChoiceObserved("bad", signals=(Signal.toward("curiosity", 2.0),)),)
    with pytest.raises(ValueError):
        reduce(events)


# --- log.py still re-exports the reducer (no caller is broken) ---------------


def test_log_module_reexports_reducer_for_backward_compatibility():
    """``mirror.log.reduce`` is the same function object as ``mirror.reducer.reduce``.

    Existing callers (``mirror/intake.py``, ``mirror/__init__.py``,
    ``mirror/log.py``'s :meth:`EventLog.reduce`) keep working after the split.
    """
    from mirror import log as log_module

    assert log_module.reduce is reducer_module.reduce
    assert log_module.scan is reducer_module.scan


def test_eventlog_reduce_goes_through_the_pure_reducer():
    log = EventLog(events=(TurnAdvanced(),))
    # The container reduce adds the schema guard but otherwise must defer to
    # the pure reducer for the actual fold — verified by behavioral equality.
    assert log.reduce() == reduce(log.events)
