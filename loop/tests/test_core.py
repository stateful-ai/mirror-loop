"""Unit tests for the Mirror Loop core: scene/choice resolution, the immutable
state update, the single adaptation type, and the legibility beat."""

from __future__ import annotations

import pytest

from loop.core import (
    NOTICE_THRESHOLD,
    Choice,
    Mirror,
    PlayerState,
    Reflection,
    Scene,
)


def _choice(cid: str, tendency: str) -> Choice:
    return Choice(id=cid, text=f"do {cid}", tendency=tendency, evidence=f"did {cid}")


def _scene(sid: str, *pairs: tuple[str, str]) -> Scene:
    return Scene(id=sid, prompt=sid, choices=tuple(_choice(c, t) for c, t in pairs))


# --- scene / choice ------------------------------------------------------------


def test_scene_resolves_choice_by_id():
    scene = _scene("s", ("a", "kindness"), ("b", "control"))
    assert scene.choice("b").tendency == "control"


def test_scene_unknown_choice_raises():
    scene = _scene("s", ("a", "kindness"))
    with pytest.raises(KeyError):
        scene.choice("nope")


# --- state update (stage 2) ----------------------------------------------------


def test_record_is_immutable_and_accumulates():
    scene = _scene("s", ("a", "kindness"))
    s0 = PlayerState()
    s1 = s0.record(scene, scene.choice("a"))
    # original untouched, new state advanced
    assert s0.turn_count == 0
    assert s1.turn_count == 1
    assert s1.tendency_counts == {"kindness": 1}


def test_tendency_counts_tally_across_turns():
    scene = _scene("s", ("a", "kindness"), ("b", "control"))
    state = PlayerState()
    for cid in ("a", "a", "b"):
        state = state.record(scene, scene.choice(cid))
    assert state.tendency_counts == {"kindness": 2, "control": 1}


# --- prediction / adaptation (the single adaptation type) ----------------------


def test_predict_with_no_history_is_declared_order():
    mirror = Mirror()
    scene = _scene("s", ("a", "kindness"), ("b", "control"), ("c", "defiance"))
    assert mirror.predict(PlayerState(), scene) == ("a", "b", "c")


def test_predict_ranks_by_running_tendency():
    mirror = Mirror()
    scene = _scene("s", ("a", "kindness"), ("b", "control"), ("c", "defiance"))
    state = PlayerState()
    # establish a control lean
    for _ in range(2):
        state = state.record(scene, scene.choice("b"))
    assert mirror.predict(state, scene)[0] == "b"


def test_predict_breaks_ties_by_declared_order():
    mirror = Mirror()
    scene = _scene("s", ("a", "kindness"), ("b", "control"), ("c", "defiance"))
    # all tendencies tied at zero -> declared order preserved
    assert mirror.predict(PlayerState(), scene) == ("a", "b", "c")


def test_adapt_moves_predicted_choice_to_front():
    mirror = Mirror()
    # declared order puts kindness last
    scene = _scene("s", ("d", "defiance"), ("c", "control"), ("k", "kindness"))
    state = PlayerState()
    for _ in range(NOTICE_THRESHOLD):
        state = state.record(scene, scene.choice("k"))
    adapted = mirror.adapt(state, scene)
    assert adapted.choices[0].id == "k"
    # adaptation only reorders — it never invents or drops options
    assert {c.id for c in adapted.choices} == {"d", "c", "k"}


def test_adapt_is_noop_when_already_in_predicted_order():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    state = PlayerState().record(scene, scene.choice("k"))
    adapted = mirror.adapt(state, scene)
    assert [c.id for c in adapted.choices] == [c.id for c in scene.choices]


# --- the legibility beat (stage 3) ---------------------------------------------


def test_no_reflection_before_threshold():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    state = PlayerState()
    for _ in range(NOTICE_THRESHOLD - 1):
        state = state.record(scene, scene.choice("k"))
    assert mirror.reflect(state) is None


def test_reflection_fires_at_threshold_with_evidence():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    state = PlayerState()
    for _ in range(NOTICE_THRESHOLD):
        state = state.record(scene, scene.choice("k"))
    reflection = mirror.reflect(state)
    assert reflection is not None
    assert reflection.tendency == "kindness"
    assert reflection.count == NOTICE_THRESHOLD
    assert reflection.total == NOTICE_THRESHOLD
    # the reason cites one piece of in-game evidence per contributing choice
    assert len(reflection.evidence) == NOTICE_THRESHOLD
    assert all(ev == "did k" for ev in reflection.evidence)


def test_reflection_does_not_repeat_once_announced():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    state = PlayerState()
    for _ in range(NOTICE_THRESHOLD):
        state = state.record(scene, scene.choice("k"))
    first = mirror.reflect(state)
    assert first is not None
    state = state.mark_announced(first.tendency)
    # another kind choice should not re-announce the same pattern
    state = state.record(scene, scene.choice("k"))
    assert mirror.reflect(state) is None


def test_reflection_render_is_a_visible_mirror_noticed_reason():
    reflection = Reflection(
        tendency="kindness",
        count=3,
        total=3,
        evidence=("reassured the technician", "left the file closed", "helped the stranger"),
    )
    rendered = reflection.render()
    assert rendered.startswith("Mirror noticed")
    assert "kindness in 3 of 3" in rendered
    assert "reason:" in rendered
    # every cited reason is an in-game act we passed in (fiction boundary)
    for ev in reflection.evidence:
        assert ev in rendered


# --- one full turn through step() ----------------------------------------------


def test_step_predicts_before_choice_and_records_after():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    result = mirror.step(PlayerState(), scene, "c")
    # prediction was made against the empty prior state -> declared order
    assert result.predicted_actions == ("k", "c")
    assert result.actual_action == "c"
    assert result.state.turn_count == 1
    assert result.reflection is None


def test_step_emits_gate_compatible_decision_point():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    dp = mirror.step(PlayerState(), scene, "k").decision_point()
    assert set(dp) == {"scene_id", "predicted_actions", "actual_action"}
    assert dp["actual_action"] == "k"
    assert isinstance(dp["predicted_actions"], list)


def test_step_fires_reflection_on_the_noticing_turn():
    mirror = Mirror()
    scene = _scene("s", ("k", "kindness"), ("c", "control"))
    state = PlayerState()
    reflections = []
    for _ in range(NOTICE_THRESHOLD):
        result = mirror.step(state, scene, "k")
        state = result.state
        reflections.append(result.reflection)
    # only the final (threshold-crossing) turn reflects
    assert reflections[:-1] == [None] * (NOTICE_THRESHOLD - 1)
    assert reflections[-1] is not None
    assert reflections[-1].tendency == "kindness"
