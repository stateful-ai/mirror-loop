"""Tests for within-session persistence — the proof that adaptations accumulate.

The acceptance criterion for this slice is: **loop-3 content provably reflects
loops 1-2**. "Content" is everything the player is shown on a loop — the adapted
choice order, the Mirror's ranked prediction, and the visible "Mirror noticed…"
reflection. These tests show that content on loop 3 is a function of loops 1 and
2, that it survives a serialize/restore boundary (true persistence, not just
in-memory threading), and — the falsifiable half — that without the accumulated
state the very same loop 3 reflects nothing.
"""

from __future__ import annotations

import pytest

from loop.core import NOTICE_THRESHOLD, Choice, Mirror, PlayerState, Scene
from loop.session import SCHEMA_VERSION, PlayedLoop, Session


# --- scenes: three loops, each offering the same three tendencies --------------
# Loop 3's scene declares kindness LAST on purpose, so the only way kindness can
# be offered first on loop 3 is if loops 1-2 moved the tendency — i.e. visible
# proof the adaptation accumulated.


def _choice(cid: str, tendency: str) -> Choice:
    return Choice(id=cid, text=f"do {cid}", tendency=tendency, evidence=f"chose {tendency} via {cid}")


LOOP1 = Scene(
    id="loop1",
    prompt="loop 1",
    choices=(_choice("a1", "kindness"), _choice("b1", "control"), _choice("c1", "defiance")),
)
LOOP2 = Scene(
    id="loop2",
    prompt="loop 2",
    choices=(_choice("a2", "kindness"), _choice("b2", "control"), _choice("c2", "defiance")),
)
# kindness declared LAST here.
LOOP3 = Scene(
    id="loop3",
    prompt="loop 3",
    choices=(_choice("c3", "defiance"), _choice("b3", "control"), _choice("a3", "kindness")),
)


def _play_first_two_kind(session: Session) -> None:
    session.play(LOOP1, "a1")  # kindness
    session.play(LOOP2, "a2")  # kindness


# --- basic accumulation --------------------------------------------------------


def test_play_accumulates_state_across_loops():
    session = Session()
    assert session.loop_count == 0
    session.play(LOOP1, "a1")
    session.play(LOOP2, "a2")
    assert session.loop_count == 2
    # the running tendency tally reflects both loops, not just the last
    assert session.state.tendency_counts == {"kindness": 2}


def test_each_play_returns_the_offered_content():
    session = Session()
    loop1 = session.play(LOOP1, "a1")
    assert isinstance(loop1, PlayedLoop)
    assert loop1.loop_number == 1
    # loop 1 has no history to adapt from, so it is offered as declared
    assert loop1.offered_order == loop1.declared_order
    assert loop1.adapted is False


# --- THE acceptance criterion: loop-3 content reflects loops 1-2 ---------------


def test_loop3_reflection_cites_the_acts_from_loops_1_and_2():
    """The legibility beat on loop 3 quotes the in-game evidence from loops 1-2."""
    session = Session()
    _play_first_two_kind(session)
    loop3 = session.play(LOOP3, "a3")  # third kind choice -> crosses NOTICE_THRESHOLD

    assert NOTICE_THRESHOLD == 3  # this proof is calibrated to a 3-loop threshold
    assert loop3.reflection is not None, "loop 3 should fire the legibility beat"
    # The reason cites the concrete acts the player took on loops 1 and 2.
    assert "chose kindness via a1" in loop3.reflection  # loop 1's act
    assert "chose kindness via a2" in loop3.reflection  # loop 2's act
    assert "3 of 3" in loop3.reflection


def test_loop3_choice_order_is_adapted_from_loops_1_and_2():
    """Loop 3 declares kindness last; the lean from loops 1-2 surfaces it first."""
    session = Session()
    _play_first_two_kind(session)
    loop3 = session.play(LOOP3, "a3")

    assert LOOP3.choices[-1].id == "a3"  # kindness really was declared last
    assert loop3.declared_order == ("c3", "b3", "a3")
    assert loop3.offered_order[0] == "a3"  # moved to the front by accumulated lean
    assert loop3.adapted is True
    # and the prediction the player is implicitly shown ranks kindness first
    assert loop3.predicted_actions[0] == "a3"


# --- persistence: loop-3 content survives a save/restore boundary --------------


def test_loop3_reflects_loops_1_2_even_after_serialize_restore():
    """Persist after loop 2, restore into a fresh Session, then play loop 3.

    This is the "within-session persistence" claim proper: loops 1-2 are played
    in one object, dropped to JSON, and loop 3 is played in a *different* object
    with a *different* Mirror — yet it still reflects loops 1-2.
    """
    live = Session(session_id="s")
    _play_first_two_kind(live)

    resumed = Session.from_json(live.to_json())
    assert resumed is not live
    assert resumed.mirror is not live.mirror
    assert resumed.loop_count == 2  # the two loops came back

    loop3 = resumed.play(LOOP3, "a3")
    assert loop3.reflection is not None
    assert "chose kindness via a1" in loop3.reflection  # loop 1, restored
    assert "chose kindness via a2" in loop3.reflection  # loop 2, restored
    assert loop3.offered_order[0] == "a3"  # adaptation accumulated across the boundary


def test_loop3_reflects_loops_1_2_after_round_trip_through_disk(tmp_path):
    live = Session(session_id="disk")
    _play_first_two_kind(live)
    path = tmp_path / "session.json"
    live.save(path)

    resumed = Session.load(path)
    loop3 = resumed.play(LOOP3, "a3")
    assert loop3.reflection is not None
    assert "chose kindness via a1" in loop3.reflection
    assert "chose kindness via a2" in loop3.reflection


# --- falsifiability: WITHOUT the accumulated state, loop 3 reflects nothing -----


def test_without_persistence_the_same_loop3_reflects_nothing():
    """The control. Play loop 3 with no accumulated history (a blank mirror).

    Same scene, same choice, same Mirror logic — but because loops 1-2 were not
    persisted, loop 3 fires no reflection and keeps its declared order. This is
    what makes the positive claim meaningful: the accumulated state is the thing
    doing the work.
    """
    mirror = Mirror()
    blank = PlayerState()
    offered = mirror.adapt(blank, LOOP3)
    result = mirror.step(blank, offered, "a3")

    assert result.reflection is None  # nothing to notice from a single loop
    # declared order preserved: with no history, kindness stays where declared (last)
    assert [c.id for c in offered.choices] == [c.id for c in LOOP3.choices]
    assert offered.choices[-1].id == "a3"


def test_fresh_session_each_loop_never_accumulates():
    """Concretely: re-loading a *fresh* session before each loop loses history."""
    last_loop3 = None
    for _ in range(NOTICE_THRESHOLD):
        amnesiac = Session()  # no restore -> no memory of prior loops
        last_loop3 = amnesiac.play(LOOP3, "a3")
    assert last_loop3 is not None
    assert last_loop3.reflection is None  # never reaches the threshold
    assert last_loop3.adapted is False  # never adapts


# --- round-trip fidelity -------------------------------------------------------


def test_round_trip_preserves_state_and_loops_exactly():
    live = Session(session_id="fidelity")
    live.play(LOOP1, "a1")
    live.play(LOOP2, "b2")  # a control choice, to vary the tally

    restored = Session.from_dict(live.to_dict())
    assert restored.session_id == live.session_id
    assert restored.state == live.state  # frozen dataclasses compare by value
    assert restored.state.tendency_counts == {"kindness": 1, "control": 1}
    assert restored.loops == live.loops
    assert restored.mirror.notice_threshold == live.mirror.notice_threshold


def test_restore_preserves_announced_so_it_does_not_re_notice():
    """A pattern announced before the save must not be re-announced after it."""
    live = Session()
    _play_first_two_kind(live)
    live.play(LOOP3, "a3")  # fires the reflection -> kindness now 'announced'
    assert live.state.announced == frozenset({"kindness"})

    resumed = Session.from_json(live.to_json())
    # a fourth kind choice must NOT re-notice the already-announced pattern
    loop4 = resumed.play(LOOP1, "a1")
    assert loop4.reflection is None


def test_from_dict_rejects_unknown_schema_version():
    live = Session()
    data = live.to_dict()
    data["schema_version"] = SCHEMA_VERSION + 99
    with pytest.raises(ValueError, match="unsupported session schema version"):
        Session.from_dict(data)
