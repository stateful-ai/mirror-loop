"""Within-session persistence — the proof that adaptations accumulate and survive
a reload *inside* one play-through.

The acceptance criteria for this slice, each pinned below:

* **Mirror and world deltas persist across a session and survive reload within
  it** — a :class:`~game.playsession.PlaySession` saved mid-play and resumed in a
  fresh object recomputes the same player model *and* world position from the
  stored log, and continuing from there is identical to never having reloaded.
* **A scripted session shows ≥2 adaptations compounding** — after a save/reload, a
  later loop is re-ordered in-scene *and* a later slot reveals a tailored framing,
  both driven by the loops persisted before the save.
* **Lost-on-quit is acceptable for v0** — nothing survives a process exit unless
  the caller explicitly :meth:`~game.playsession.PlaySession.save`\\d it; there is
  no durable cross-session store, and the tests encode that boundary rather than
  papering over it.

The falsifiable half is here too: the same scenes, offered without the
accumulated (persisted) state, show no adaptation — so the persistence is the
thing doing the work.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loop.core import Mirror, PlayerState

from game.playsession import SCHEMA_VERSION, PlaySession
from game.replay import RunResult
from game.session import (
    LoopRecord,
    offer_scene,
    persona_policy,
    play_session,
    transcript,
)
from game.variants import ADAPTIVE, FIXED, build_variant, random_variant
from game.world import CONFRONTATION, DEFAULT_WORLD, Slot, World

#: A committed snapshot of the adaptive arm driven *through* a save/reload. The
#: baseline (``random``) arm already has a golden byte-identity gate in
#: ``game/fixtures/baseline_seed42.json``, but that arm never adapts — so nothing
#: on disk pins the *adaptive* survives-reload behaviour. This fixture does, so a
#: code change that silently altered what a resumed loop shows fails loudly here.
ADAPTIVE_RESUMED_GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "adaptive_kind_resumed.json"
)

# A consistently kind player: one choice id per slot of DEFAULT_WORLD, each the
# kindness option. Loops: intake, records, corridor, confrontation, exit.
KIND_LOG = ("c_reassure", "c_close", "c_help", "c_wait", "c_accept")
# A consistently controlling player, for the falsifiable contrast.
CONTROL_LOG = ("c_measure", "c_read", "c_map", "c_log", "c_audit")
# Where the demo / persistence tests save and reload: after loop 3, before 4-5.
SAVE_AFTER = 3


def _play(session: PlaySession, choice_ids) -> None:
    for choice_id in choice_ids:
        session.play(choice_id)


# --- basic accumulation --------------------------------------------------------


def test_play_accumulates_state_and_position_across_loops():
    session = PlaySession()
    assert session.position == 0 and not session.is_complete
    session.play("c_reassure")  # intake (kindness)
    session.play("c_close")  # records (kindness)
    assert session.position == 2
    # both loops are in the running tally, not just the last
    assert session.state.tendency_counts == {"kindness": 2}
    assert session.input_log == ["c_reassure", "c_close"]


def test_each_play_returns_the_offered_content():
    session = PlaySession()
    loop1 = session.play("c_reassure")
    assert isinstance(loop1, LoopRecord)
    assert loop1.loop_index == 0
    # loop 1 has no history to adapt from: offered as declared, neutral framing
    assert loop1.reordered is False
    assert loop1.branch_key == "fixed"  # intake is a fixed slot


def test_current_offer_recomputes_from_accumulated_state():
    """The preview of the next loop reflects every loop played so far."""
    session = PlaySession()
    session.play("c_reassure")
    session.play("c_close")
    # next up is the corridor branch slot; one clear kindness lean already exists
    _declared, offered, branch_key = session.current_offer()
    assert offered.id == "corridor"
    assert branch_key == "kindness"  # the world reveals the kind framing


def test_current_offer_raises_when_complete():
    session = PlaySession()
    _play(session, KIND_LOG)
    assert session.is_complete
    with pytest.raises(ValueError, match="complete"):
        session.current_offer()


# --- THE acceptance criterion: ≥2 adaptations compounding across a reload -------


def test_two_adaptations_compound_across_a_save_reload():
    """Play loops 1-3 kind, persist, resume in a fresh session, play loops 4-5.

    Loops 4 and 5 are played *after* the reload, yet both adapt to the kind lean
    built in loops 1-3 — which only survived because the session was persisted:

    * loop 4 (confrontation) declares the kind option LAST, but the Mirror lifts
      it to the front (in-scene re-ordering), and
    * loop 5 (exit) reveals the kindness framing (across-scene branch selection).

    Two distinct adaptations, both compounding on history carried across the
    serialize/restore boundary.
    """
    live = PlaySession(session_id="compound")
    _play(live, KIND_LOG[:SAVE_AFTER])

    resumed = PlaySession.from_json(live.to_json())
    assert resumed is not live
    assert resumed.mirror is not live.mirror
    assert resumed.position == SAVE_AFTER  # the three loops came back

    loop4 = resumed.play(KIND_LOG[3])  # confrontation
    loop5 = resumed.play(KIND_LOG[4])  # exit

    # Adaptation #1 — in-scene re-ordering, on a scene that declared kindness last.
    assert loop4.offered.id == "confrontation"
    assert [c.id for c in loop4.declared.choices][-1] == "c_wait"  # declared last
    assert loop4.offered.choices[0].id == "c_wait"  # surfaced first
    assert loop4.result.predicted_actions[0] == "c_wait"
    assert loop4.reordered is True

    # Adaptation #2 — across-scene branch selection, the tailored reveal.
    assert loop5.offered.id == "exit"
    assert loop5.branch_key == "kindness"

    # …and the adaptation was already compounding *before* the save: every branch
    # slot up to the reload revealed the kind framing as the lean strengthened.
    branch_keys = {r.offered.id: r.branch_key for r in resumed.records}
    assert branch_keys["records"] == "kindness"  # loop 2 (1 lean)
    assert branch_keys["corridor"] == "kindness"  # loop 3 (2 leans)
    assert branch_keys["exit"] == "kindness"  # loop 5 (4 leans), post-reload


def test_reflection_beat_fires_after_a_reload_citing_pre_reload_loops():
    """The legibility beat on loop 4 cites in-game acts from loops 1-3."""
    live = PlaySession()
    _play(live, KIND_LOG[:SAVE_AFTER])  # 3 kind loops -> crosses NOTICE_THRESHOLD
    # The reflection fires when the 3rd kind choice lands (loop 3, pre-save).
    assert live.records[2].result.reflection is not None

    resumed = PlaySession.from_json(live.to_json())
    # The pattern was already announced; a resumed session must not re-notice it.
    assert resumed.state.announced == frozenset({"kindness"})
    loop4 = resumed.play(KIND_LOG[3])
    assert loop4.result.reflection is None  # not re-announced after the reload


def test_persistence_survives_a_round_trip_through_disk(tmp_path):
    live = PlaySession(session_id="disk")
    _play(live, KIND_LOG[:SAVE_AFTER])
    path = tmp_path / "session.json"
    live.save(path)

    resumed = PlaySession.load(path)
    assert resumed.position == SAVE_AFTER
    loop4 = resumed.play(KIND_LOG[3])
    loop5 = resumed.play(KIND_LOG[4])
    assert loop4.reordered is True and loop4.offered.choices[0].id == "c_wait"
    assert loop5.branch_key == "kindness"


# --- reload reconstructs derived state exactly (nothing lost, nothing invented) -


def test_reload_reconstructs_the_full_derived_state():
    """A resumed session's reduced state matches the live one byte for byte."""
    live = PlaySession(session_id="fidelity")
    _play(live, KIND_LOG)  # a whole session

    resumed = PlaySession.from_json(live.to_json())
    assert resumed.position == live.position
    assert resumed.state == live.state  # frozen dataclass: value equality
    assert resumed.state.announced == live.state.announced
    assert resumed.input_log == live.input_log
    # every loop's offered order, branch key and reflection comes back identical
    assert [r.branch_key for r in resumed.records] == [r.branch_key for r in live.records]
    assert [[c.id for c in r.offered.choices] for r in resumed.records] == [
        [c.id for c in r.offered.choices] for r in live.records
    ]
    assert [r.system_message.render() for r in resumed.records] == [
        r.system_message.render() for r in live.records
    ]


def test_resumed_session_completes_identically_to_the_one_shot_runner():
    """Parity: the resumable path produces exactly what play_session produces.

    Same world, same variant, same choices — so a session built loop-by-loop
    through PlaySession (across a reload) yields a transcript byte-identical to the
    one the one-shot runner produces for the equivalent persona.
    """
    live = PlaySession()
    _play(live, KIND_LOG[:SAVE_AFTER])
    resumed = PlaySession.from_json(live.to_json())
    _play(resumed, KIND_LOG[SAVE_AFTER:])

    one_shot = play_session(persona_policy("kindness"))
    assert transcript(resumed.completed()) == transcript(one_shot)


def test_resumed_adaptive_run_is_byte_identical_to_a_committed_golden():
    """A committed determinism gate for the *adaptive* survives-reload path.

    The in-process equality tests above prove a resumed session matches the live
    one — but under a code change both sides drift together, so they cannot catch a
    change that silently alters what a resumed loop shows. The baseline golden in
    :mod:`game.replay` does pin output to disk, but only for the non-adaptive arm.
    This pins the adaptive arm, driven through a real save/reload, to a committed
    snapshot (serialized by the same determinism-audited :class:`RunResult`), so
    any nondeterminism or unintended change in the adaptation fails loudly.

    If a change here is intended, regenerate the fixture with
    ``python -m game.playsession --write-golden``.
    """
    live = PlaySession()
    _play(live, KIND_LOG[:SAVE_AFTER])
    resumed = PlaySession.from_json(live.to_json())
    _play(resumed, KIND_LOG[SAVE_AFTER:])

    snapshot = RunResult(
        seed=0,  # adaptive ignores the seed; the input log fully determines it
        variant="adaptive",
        world_name=DEFAULT_WORLD.name,
        input_log=KIND_LOG,
        session=resumed.completed(),
    ).to_json()

    assert snapshot == ADAPTIVE_RESUMED_GOLDEN.read_text(encoding="utf-8"), (
        "the resumed adaptive run drifted from its committed golden; if this change "
        "was intended, regenerate game/fixtures/adaptive_kind_resumed.json"
    )


def test_seeded_placebo_variant_round_trips_exactly():
    """The placebo arm's seed is part of the saved log, so it replays identically."""
    live = PlaySession(variant=random_variant(7))
    _play(live, KIND_LOG)
    data = live.to_dict()
    assert data["variant"] == "random"
    assert data["seed"] == 7

    resumed = PlaySession.from_json(live.to_json())
    assert resumed.variant.name == "random"
    assert transcript(resumed.completed()) == transcript(live.completed())


# --- falsifiability: WITHOUT the accumulated state, the same scene adapts nothing


def test_without_persisted_history_the_same_scene_is_not_adapted():
    """The control. Offer the confrontation scene from a blank (un-persisted)
    state: it keeps its declared order (kindness last), no re-ordering.

    This is what makes the positive claim meaningful — it is the *persisted* kind
    history, not the engine alone, that lifts the kind option in
    :func:`test_two_adaptations_compound_across_a_save_reload`.
    """
    slot = Slot("confrontation", fixed=CONFRONTATION)
    _declared, offered, _branch = offer_scene(ADAPTIVE, Mirror(), PlayerState(), slot)
    assert [c.id for c in offered.choices] == [c.id for c in CONFRONTATION.choices]
    assert offered.choices[-1].id == "c_wait"  # kindness stays where declared: last


def test_adaptation_tracks_what_was_persisted_not_merely_that_loops_happened():
    """A controlling player's persisted history drives a *different* adaptation.

    Same number of persisted loops as the kind run, but the content reflects the
    control lean: confrontation surfaces the control option, and branch slots
    reveal the control framing — so it is the persisted *behavior*, not the act of
    persisting, that the later loops adapt to.
    """
    live = PlaySession()
    _play(live, CONTROL_LOG[:SAVE_AFTER])
    resumed = PlaySession.from_json(live.to_json())

    _declared, offered, _branch = resumed.current_offer()  # confrontation
    assert offered.id == "confrontation"
    assert offered.choices[0].id == "c_log"  # control surfaced first, not c_wait
    assert offered.choices[0].id != "c_wait"
    branch_keys = {r.offered.id: r.branch_key for r in resumed.records}
    assert branch_keys["records"] == "control"
    assert branch_keys["corridor"] == "control"


def test_fixed_baseline_persists_but_never_adapts():
    """The identity arm accumulates history too, but the seam is a no-op.

    Persistence is orthogonal to adaptation: a saved/resumed FIXED session has the
    same tally, yet shows neither re-ordering nor a tailored framing — proving the
    contingency, not the persistence, is what produces the adaptations above.
    """
    live = PlaySession(variant=FIXED)
    _play(live, KIND_LOG[:SAVE_AFTER])
    resumed = PlaySession.from_json(live.to_json())
    assert resumed.state.tendency_counts == {"kindness": 3}  # history persisted

    loop4 = resumed.play(KIND_LOG[3])
    loop5 = resumed.play(KIND_LOG[4])
    assert loop4.reordered is False  # identity seam: no re-ordering
    assert loop5.branch_key == "default"  # identity seam: neutral framing


# --- lost-on-quit is acceptable for v0: nothing survives without an explicit save


def test_unsaved_sessions_share_no_hidden_state():
    """Two independently constructed sessions start blank — there is no implicit,
    process-global or on-disk store carrying a previous run forward. Within-session
    persistence is opt-in via save/load; quitting without saving loses the run,
    which is the documented v0 boundary (cross-session persistence is M2+)."""
    a = PlaySession()
    _play(a, KIND_LOG)
    b = PlaySession()  # a brand-new session, no load
    assert b.position == 0
    assert b.state == PlayerState()


def test_save_writes_nothing_until_called(tmp_path):
    path = tmp_path / "session.json"
    session = PlaySession()
    _play(session, KIND_LOG[:SAVE_AFTER])
    assert not path.exists()  # in-memory only; a quit here loses the session
    session.save(path)
    assert path.exists()


# --- the saved form is the log, not derived state ------------------------------


def test_saved_form_stores_only_the_authoritative_log():
    """Derived state (the Mirror model, world position, adaptations) is never the
    persisted authority — only the run config and input log are stored."""
    session = PlaySession(session_id="audit")
    _play(session, KIND_LOG[:SAVE_AFTER])
    data = session.to_dict()
    assert set(data) == {
        "schema_version",
        "session_id",
        "world",
        "variant",
        "seed",
        "input_log",
    }
    assert data["input_log"] == list(KIND_LOG[:SAVE_AFTER])
    assert data["world"] == DEFAULT_WORLD.name
    assert data["variant"] == "adaptive"


# --- fail-loud guards ----------------------------------------------------------


def test_from_dict_rejects_unknown_schema_version():
    data = PlaySession().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 99
    with pytest.raises(ValueError, match="unsupported session schema version"):
        PlaySession.from_dict(data)


def test_from_dict_rejects_an_unknown_world():
    data = PlaySession().to_dict()
    data["world"] = "no-such-world"
    with pytest.raises(ValueError, match="unknown world"):
        PlaySession.from_dict(data)


def test_from_dict_rejects_a_world_mismatch_when_one_is_supplied():
    data = PlaySession().to_dict()
    data["world"] = "ghost-spine"
    with pytest.raises(ValueError, match="world mismatch"):
        PlaySession.from_dict(data, world=DEFAULT_WORLD)


def test_construction_rejects_a_world_outside_the_loop_target():
    short = World(name="too-short", slots=DEFAULT_WORLD.slots[:2])
    with pytest.raises(ValueError, match="3-5 loops"):
        PlaySession(world=short)


def test_playing_past_the_end_of_the_spine_raises():
    session = PlaySession()
    _play(session, KIND_LOG)
    assert session.is_complete
    with pytest.raises(ValueError, match="complete"):
        session.play("c_reassure")


def test_completed_requires_a_finished_spine():
    session = PlaySession()
    _play(session, KIND_LOG[:SAVE_AFTER])
    with pytest.raises(ValueError, match="not complete"):
        session.completed()


def test_a_custom_world_round_trips_when_supplied_explicitly():
    """from_dict accepts an ad-hoc world when its name matches the snapshot — so a
    spine that isn't in the registry (e.g. a test world) still resumes."""
    world = World(name="mirror-lab", slots=DEFAULT_WORLD.slots)  # same name
    live = PlaySession(world=world, variant=build_variant("adaptive"))
    _play(live, KIND_LOG[:SAVE_AFTER])
    resumed = PlaySession.from_dict(live.to_dict(), world=world)
    assert resumed.position == SAVE_AFTER
