"""Tests for the Act 1 scene graph (~12-16 scenes, single-branch linear spine).

Pins the M1 deliverable from
``docs/mirror_loop_m1_synthesis.md`` Phase B2 — every acceptance criterion is
asserted against the code/data, not just prose:

* the spine has 12-16 scenes (``ACT1_MIN_LOOPS``..``ACT1_MAX_LOOPS``);
* every scene is parsed by the frozen ``.scene`` loader (``docs/SCENE_FORMAT.md``)
  with no in-code authoring path;
* the spine is single-branch — every slot wraps exactly one fixed scene, no
  across-scene framing variants;
* the spine **loads under the frozen ``WorldState``** — a real input log
  reduces with :meth:`game.worldstate.WorldState.reduce` and the visited slots
  match the spine in order;
* the deterministic seed-42 walk drives the loop from Lab Intake through
  Recalibration to Act 2 entry, byte-identically across two runs;
* the mirror axis is exercised in **>= 3 scenes** — i.e. the in-scene
  re-ordering surface of tendency mirroring (``loop.core.Mirror.adapt``)
  visibly lifts the predicted choice to the front in three or more loops of
  the seeded walk.
"""

from __future__ import annotations

from collections import Counter

import pytest

from mirror.log import ChoiceObserved, EventLog

from game.act1 import (
    ACT1_DATA_DIR,
    ACT1_END_SLOT,
    ACT1_MAX_LOOPS,
    ACT1_MIN_LOOPS,
    ACT1_RECALIBRATION_SLOT,
    ACT1_START_SLOT,
    ACT1_WORLD_NAME,
    DEFAULT_SEED,
    load_act1_scenes,
    load_act1_world,
    play_act1,
    seeded_input_log,
    seeded_policy,
)
from game.scenes import load_scene
from game.session import play_session
from game.worldstate import WorldState
from loop.core import Mirror, PlayerState, Scene

_V0_TENDENCIES = frozenset({"kindness", "control", "defiance"})


# --- The spine: shape, count, single-branch -----------------------------------


def test_spine_size_lands_in_the_authored_window():
    scenes = load_act1_scenes()
    assert ACT1_MIN_LOOPS <= len(scenes) <= ACT1_MAX_LOOPS


def test_world_loads_via_the_frozen_scene_loader():
    # Every Scene the world ships came through game.scenes.load_scene; building
    # twice yields equal objects, so the build is a pure function of the data.
    direct = load_act1_scenes()
    via_world = tuple(slot.fixed for slot in load_act1_world().slots)
    assert direct == via_world
    assert via_world == tuple(slot.fixed for slot in load_act1_world().slots)


def test_every_slot_is_a_single_fixed_scene():
    # Single-branch contract: no slot may declare across-scene variants. The
    # only adaptation surface engaged in Act 1 is the in-scene re-ordering.
    world = load_act1_world()
    for slot in world.slots:
        assert isinstance(slot.fixed, Scene), (slot.key, slot.fixed)
        assert slot.variants is None, slot.key


def test_slot_keys_equal_scene_ids_in_authored_order():
    # The slot key / scene id identity is what makes the WorldState reduction
    # honest (a recorded ChoiceObserved's scene_id must match the slot it
    # lands on or the reduction raises) and what makes the seeded input log
    # interchangeable with the world walk.
    world = load_act1_world()
    keys = [slot.key for slot in world.slots]
    ids = [slot.fixed.id for slot in world.slots]
    assert keys == ids
    assert keys[0] == ACT1_START_SLOT
    assert keys[-1] == ACT1_END_SLOT
    assert ACT1_RECALIBRATION_SLOT in keys
    # Recalibration must precede Act 2 entry; the brief is "Recalibration ->
    # Act 2 entry", not the other way round.
    assert keys.index(ACT1_RECALIBRATION_SLOT) < keys.index(ACT1_END_SLOT)


def test_world_is_named_and_registered_for_reduction():
    world = load_act1_world()
    assert world.name == ACT1_WORLD_NAME
    # A WorldState reduced against this world labels itself with the same name,
    # so a persisted snapshot self-describes which spine it tracks.
    assert WorldState.reduce(world, []).world_name == ACT1_WORLD_NAME


def test_every_scene_carries_the_v0_tendency_vocabulary():
    # Tendency mirroring reads the dominant tendency. Every Act 1 choice must
    # carry one of the v0 axis labels (docs/ADAPTATION.md §2), and every scene
    # must offer all three so a kind/control/defiant player can play any scene.
    for scene in load_act1_scenes():
        tendencies = [c.tendency for c in scene.choices]
        assert set(tendencies) == _V0_TENDENCIES, (scene.id, tendencies)
        # Exactly one choice per tendency keeps the seeded policy's draw map
        # injective into the choice space, so a draw is always realisable.
        assert Counter(tendencies) == Counter(_V0_TENDENCIES), scene.id


def test_every_choice_carries_distinct_id_text_and_evidence():
    for scene in load_act1_scenes():
        ids = [c.id for c in scene.choices]
        assert len(ids) == len(set(ids)), (scene.id, ids)
        for choice in scene.choices:
            assert choice.text.strip(), (scene.id, choice.id)
            # Evidence is what the Reflection beat cites; an empty phrase would
            # quietly mean the Mirror's reason line shows nothing for this turn.
            assert choice.evidence.strip(), (scene.id, choice.id)


def test_loader_module_unaware_of_file_layout():
    # The Act 1 module owns the spine layout; the frozen loader only knows how
    # to parse one ``.scene`` file. Pin that the scene files load through the
    # public game.scenes.load_scene entry point and nothing else.
    for path in sorted(ACT1_DATA_DIR.glob("*.scene")):
        scene = load_scene(path)
        assert scene.id == path.stem


# --- Loads under the frozen WorldState ---------------------------------------


def test_input_log_reduces_under_frozen_worldstate():
    # The acceptance criterion: the spine "loads under frozen WorldState". We
    # build the event log a real seeded session would produce, reduce it via
    # the frozen reducer, and assert the position walks every slot in order.
    world = load_act1_world()
    log = seeded_input_log(DEFAULT_SEED)
    events = [
        ChoiceObserved(choice_id=cid, scene_id=slot.key)
        for cid, slot in zip(log, world.slots)
    ]
    state = WorldState.reduce(world, events)

    assert state.is_complete(world)
    assert state.position == world.length
    assert [v.slot_key for v in state.visited] == [slot.key for slot in world.slots]
    assert [v.choice_id for v in state.visited] == list(log)


def test_reduce_also_accepts_an_eventlog_container():
    # The same EventLog container the Mirror reduces from drives the world
    # position — the spine doesn't need its own log type.
    world = load_act1_world()
    log = seeded_input_log(DEFAULT_SEED)
    events = tuple(
        ChoiceObserved(choice_id=cid, scene_id=slot.key)
        for cid, slot in zip(log, world.slots)
    )
    eventlog = EventLog(events=events)
    state = WorldState.reduce(world, eventlog.events)
    assert state.position == world.length


def test_worldstate_snapshot_round_trips_through_json():
    world = load_act1_world()
    log = seeded_input_log(DEFAULT_SEED)
    events = [
        ChoiceObserved(choice_id=cid, scene_id=slot.key)
        for cid, slot in zip(log, world.slots)
    ]
    state = WorldState.reduce(world, events)
    restored = WorldState.from_json(state.to_json())
    assert restored == state


# --- The deterministic seed-42 walk -------------------------------------------


def test_seeded_walk_runs_intake_to_act_2_entry():
    # The north-star path: Lab Intake -> ... -> Recalibration -> Act 2 entry,
    # driven by the seeded policy without any human input.
    session = play_act1()
    keys = [r.declared.id for r in session.records]
    assert keys[0] == ACT1_START_SLOT
    assert keys[-1] == ACT1_END_SLOT
    assert ACT1_RECALIBRATION_SLOT in keys
    # The recalibration scene precedes the Act 2 entry in the walked order
    # (defence against an authoring re-order that breaks the brief's beat).
    assert keys.index(ACT1_RECALIBRATION_SLOT) < keys.index(ACT1_END_SLOT)
    assert session.loop_count == load_act1_world().length


def test_seeded_walk_is_byte_identical_across_two_runs():
    # The seed-42 walk must be deterministic — that is the M1 reproducibility
    # contract this spine inherits from game.replay. Two runs produce identical
    # input logs and identical per-loop offered/predicted/actual content.
    a = play_act1()
    b = play_act1()
    assert [r.result.actual_action for r in a.records] == [
        r.result.actual_action for r in b.records
    ]
    assert [
        (r.declared.id, tuple(c.id for c in r.offered.choices), r.result.predicted_actions)
        for r in a.records
    ] == [
        (r.declared.id, tuple(c.id for c in r.offered.choices), r.result.predicted_actions)
        for r in b.records
    ]
    assert a.final_state.tendency_counts == b.final_state.tendency_counts
    assert a.final_state.announced == b.final_state.announced


def test_seeded_input_log_matches_what_the_seeded_walk_actually_plays():
    # seeded_input_log is the byte-identical projection of play_act1 onto its
    # choice ids; the two must never drift.
    session = play_act1()
    assert tuple(r.result.actual_action for r in session.records) == seeded_input_log(
        DEFAULT_SEED
    )


def test_seeded_walk_is_independent_of_v0_session_runner_bound():
    # The Act 1 spine is 14 loops, outside the v0 3-5-loop bound enforced by
    # game.session.play_session. Pin that play_session would refuse this world,
    # so the parallel act1 runner is genuinely required (not a forked code path
    # introduced casually).
    world = load_act1_world()
    with pytest.raises(ValueError, match="3-5 loops"):
        play_session(seeded_policy(DEFAULT_SEED), world=world)


def test_seeded_policy_is_deterministic_across_independent_instances():
    # Two fresh Random(42)-backed policies produce identical sequences across
    # the same scenes, so the seed alone fixes the walk (no hidden state).
    from game.session import offer_scene
    from game.variants import ADAPTIVE

    world = load_act1_world()
    p1 = seeded_policy(DEFAULT_SEED)
    p2 = seeded_policy(DEFAULT_SEED)
    state = PlayerState()
    mirror = Mirror()
    a: list[str] = []
    b: list[str] = []
    for i, slot in enumerate(world.slots):
        _, offered, _ = offer_scene(ADAPTIVE, mirror, state, slot)
        a.append(p1(offered, state, i))
        b.append(p2(offered, state, i))
    assert a == b


# --- Mirror axis exercised in >= 3 scenes -------------------------------------


def test_seed_42_walk_reorders_at_least_three_scenes():
    # "Exercises the mirror axis" = the in-scene re-ordering surface of
    # tendency mirroring (loop.core.Mirror.adapt) visibly lifts the predicted
    # choice to the front of a scene. Authoring varies declared choice order
    # across scenes so a dominant-tendency player sees several of these.
    session = play_act1()
    reordered = [r for r in session.records if r.reordered]
    assert len(reordered) >= 3, (
        f"only {len(reordered)} scenes were re-ordered by the Mirror; the "
        "acceptance bar is >= 3 scenes exercising the mirror axis"
    )


def test_reflection_beat_fires_inside_act1():
    # The legibility beat (docs/CORE_LOOP.md §3) is the human-facing proof
    # that the mirror axis is being read. With 14 loops the dominant tendency
    # must cross the notice threshold somewhere in the walk; if it never
    # fired, the axis isn't really being exercised.
    session = play_act1()
    reflections = [r for r in session.records if r.result.reflection is not None]
    assert reflections, "the Mirror never reflected during the Act 1 walk"
    assert reflections[0].result.reflection.tendency in _V0_TENDENCIES


def test_predicted_action_leads_the_offered_order_when_reordered():
    # When the Mirror re-orders a scene, the predicted top action must be the
    # first offered choice. Pinning the invariant the adaptation seam promises.
    session = play_act1()
    for record in session.records:
        if not record.reordered:
            continue
        assert record.result.predicted_actions, record.declared.id
        assert record.offered.choices[0].id == record.result.predicted_actions[0]


# --- Authoring-drift defences ------------------------------------------------


def test_unexpected_scene_file_in_directory_raises():
    # If a future authoring change drops a non-act1 file into the data dir,
    # the spine builder must fail loudly rather than silently load it.
    intruder = ACT1_DATA_DIR / "intruder.scene"
    intruder.write_text(
        "id: intruder\nprompt:\n  hi\nchoice c:\n  tendency: kindness\n"
        "  text: x\n  evidence: y\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(ValueError, match="act1_"):
            load_act1_world()
    finally:
        intruder.unlink()


def test_scene_missing_a_tendency_is_rejected_at_load(tmp_path, monkeypatch):
    # The seeded policy draws a tendency per loop and looks up the matching
    # choice. If an authored scene ever drops a tendency, the loader must
    # refuse the world rather than let the policy silently degrade.
    scratch = tmp_path / "act1"
    scratch.mkdir()
    for path in sorted(ACT1_DATA_DIR.glob("*.scene")):
        (scratch / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    # Rewrite one scene so two choices share a tendency (and one is missing).
    target = scratch / "act1_06_optional_lore.scene"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("tendency: defiance", "tendency: kindness"), encoding="utf-8")

    monkeypatch.setattr("game.act1.ACT1_DATA_DIR", scratch)
    with pytest.raises(ValueError, match="one choice per v0 tendency"):
        load_act1_world()


def test_filename_must_match_scene_id(tmp_path, monkeypatch):
    # The "filename == scene id" invariant: if it ever drifts (an authoring
    # rename in one place but not the other), the world build fails loudly.
    scratch = tmp_path / "act1"
    scratch.mkdir()
    for path in sorted(ACT1_DATA_DIR.glob("*.scene")):
        (scratch / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    # Rename one file so its name no longer matches the id it declares.
    first = sorted(scratch.glob("*.scene"))[0]
    first.rename(scratch / "act1_99_renamed.scene")

    monkeypatch.setattr("game.act1.ACT1_DATA_DIR", scratch)
    with pytest.raises(ValueError, match="disagrees with filename"):
        load_act1_world()
