"""The session runner — the acceptance criteria for this task, made executable.

Acceptance: *player completes 3–5 loops in one session; mirror visibly drives
content; runs with no LLM.* Each is pinned below:

* **3–5 loops** — :func:`play_session` returns a session whose ``loop_count`` is
  inside ``[MIN_LOOPS, MAX_LOOPS]``, and enforces that bound by raising.
* **mirror visibly drives content** — two distinct, observable effects: the
  in-scene re-ordering (``LoopRecord.reordered``) and the across-scene branch
  selection (``LoopRecord.branch_key``), both verified to differ by player.
* **no LLM** — the whole session is deterministic and reproducible: the same
  persona played twice yields a byte-identical transcript (no model, no
  randomness, no network on the path).
"""

from __future__ import annotations

import pytest

from acceptance.predictability import evaluate
from loop.core import Mirror

from game.session import (
    MAX_LOOPS,
    MIN_LOOPS,
    LoopRecord,
    erratic_policy,
    persona_policy,
    play_session,
    report_block,
    scripted_policy,
    transcript,
)
from game.world import DEFAULT_WORLD, World


# --- "player completes 3–5 loops in one session" -------------------------------


def test_session_completes_inside_the_three_to_five_loop_target():
    session = play_session(persona_policy("kindness"))
    assert MIN_LOOPS <= session.loop_count <= MAX_LOOPS
    assert session.loop_count == DEFAULT_WORLD.length == 5


def test_every_persona_completes_a_full_session():
    for target in ("kindness", "control", "defiance"):
        session = play_session(persona_policy(target))
        assert session.loop_count == 5


def test_session_outside_the_target_raises():
    # A two-slot world is below MIN_LOOPS; the runner must fail loudly, not ship
    # a trivial session.
    short = World(name="too-short", slots=DEFAULT_WORLD.slots[:2])
    with pytest.raises(ValueError, match="3-5 loops"):
        play_session(persona_policy("kindness"), world=short)


def test_each_loop_records_one_choice_along_a_real_tendency():
    session = play_session(persona_policy("control"))
    for record in session.records:
        chosen = record.offered.choice(record.result.actual_action)
        assert chosen.tendency == "control"


# --- "mirror visibly drives content": effect #1, in-scene re-ordering -----------


def test_consistent_player_sees_the_mirror_reorder_a_scene():
    # The confrontation scene declares the kind option last; a kind player has it
    # surfaced to the top — the single adaptation type, made visible.
    session = play_session(persona_policy("kindness"))
    reordered = [r for r in session.records if r.reordered]
    assert reordered, "the Mirror never re-ordered a scene for a consistent player"
    confront = next(r for r in session.records if r.offered.id == "confrontation")
    assert confront.declared.choices[-1].id == "c_wait"  # declared kindness-last
    assert confront.offered.choices[0].id == "c_wait"  # surfaced first
    assert confront.result.predicted_actions[0] == "c_wait"


def test_first_loop_is_not_reordered():
    # With no history the prediction equals the declared order: nothing to nudge.
    session = play_session(persona_policy("kindness"))
    assert session.records[0].reordered is False


# --- "mirror visibly drives content": effect #2, across-scene branch selection --


def test_consistent_player_is_revealed_their_own_framing():
    session = play_session(persona_policy("kindness"))
    branch_keys = {r.offered.id: r.branch_key for r in session.records}
    # The three branch slots reveal the kind framing once the lean is established.
    assert branch_keys["records"] == "kindness"
    assert branch_keys["corridor"] == "kindness"
    assert branch_keys["exit"] == "kindness"


def test_different_players_are_driven_to_different_content():
    kind = play_session(persona_policy("kindness"))
    control = play_session(persona_policy("control"))
    kind_prompts = [r.offered.prompt for r in kind.records]
    control_prompts = [r.offered.prompt for r in control.records]
    # Same world, same spine — but the Mirror reveals materially different rooms.
    assert kind_prompts != control_prompts


# --- The reflection / legibility beat fires for a consistent player ------------


def test_consistent_player_triggers_the_reflection_beat_once():
    session = play_session(persona_policy("kindness"))
    reflections = [r for r in session.records if r.result.reflection is not None]
    assert len(reflections) == 1, "the Mirror should notice a pattern exactly once"
    reflection = reflections[0].result.reflection
    assert reflection.tendency == "kindness"
    assert reflection.count == 3  # NOTICE_THRESHOLD
    # The reason cites only in-game evidence — pre-authored, in-fiction phrases.
    rendered = reflection.render()
    assert rendered.startswith("Mirror noticed")
    for ev in reflection.evidence:
        assert ev in rendered


def test_erratic_player_never_locks_the_model():
    # The escape archetype: cycling tendencies never reaches the notice threshold,
    # so no pattern is ever confirmed.
    session = play_session(erratic_policy())
    assert all(r.result.reflection is None for r in session.records)
    assert session.final_state.announced == frozenset()


# --- "runs with no LLM": full determinism / reproducibility --------------------


def test_same_persona_plays_byte_identical_twice():
    a = transcript(play_session(persona_policy("kindness")))
    b = transcript(play_session(persona_policy("kindness")))
    assert a == b, "a session with no LLM must be perfectly reproducible"


def test_scripted_policy_replays_an_exact_choice_sequence():
    # Hand-pick the offered choice each loop; nothing is generated.
    ids: list[str] = []
    mirror = Mirror()

    def recording_policy(scene, state, i):
        # Always take the defiance option, by tendency, regardless of order.
        choice = next(c for c in scene.choices if c.tendency == "defiance")
        ids.append(choice.id)
        return choice.id

    first = play_session(recording_policy, mirror=mirror)
    replay = play_session(scripted_policy(ids))
    assert [r.result.actual_action for r in first.records] == ids
    assert [r.result.actual_action for r in replay.records] == ids


# --- Feeds the locked acceptance gate without translation ----------------------


def test_session_log_is_gate_compatible():
    session = play_session(persona_policy("kindness"))
    log = session.session_log()
    assert log["decision_points"], "a session must emit decision points"
    assert len(log["decision_points"]) == session.loop_count
    # The decision points evaluate against the locked gate with no translation.
    result = evaluate(session.decision_points())
    assert result.n == session.loop_count


def test_predicted_hit_matches_top_prediction():
    session = play_session(persona_policy("kindness"))
    for record in session.records:
        expected = (
            bool(record.result.predicted_actions)
            and record.result.predicted_actions[0] == record.result.actual_action
        )
        assert record.predicted_hit == expected


# --- Closing report reflects how predictable the player actually was -----------


def test_report_reads_high_for_a_predictable_player_low_for_an_erratic_one():
    kind_report = report_block(play_session(persona_policy("kindness")))
    erratic_report = report_block(play_session(erratic_policy()))
    assert "MODEL CONFIDENCE     : HIGH" in kind_report
    assert "MODEL CONFIDENCE     : LOW" in erratic_report


def test_on_loop_hook_is_called_once_per_loop():
    seen: list[LoopRecord] = []
    session = play_session(persona_policy("control"), on_loop=seen.append)
    assert len(seen) == session.loop_count
    assert [r.loop_index for r in seen] == list(range(session.loop_count))


def test_loop_bounds_are_the_advertised_target():
    assert (MIN_LOOPS, MAX_LOOPS) == (3, 5)
