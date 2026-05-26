"""Tests for the questionnaire intake → seed-event encoding.

These pin the contract documented in ``docs/INTAKE.md``: the mapping is
deterministic and documented, the reducer turns the events into a starting
MirrorState, and corrupt input fails loudly rather than being absorbed.
"""

from __future__ import annotations

import pytest

from mirror.intake import (
    INTAKE_CHOICE_PREFIX,
    INTAKE_SCENE_ID,
    QUESTIONNAIRE,
    QUESTIONNAIRE_BY_ID,
    encode,
    seed_log,
    seed_state,
)
from mirror.log import ChoiceObserved, EventLog, reduce
from mirror.schema import MIRROR_SCHEMA, AttributeKind
from mirror.state import MirrorState, Signal


# --- catalog sanity: every answer maps to schema-legal signals ----------------


def test_catalog_questions_have_stable_ids():
    ids = [q.id for q in QUESTIONNAIRE]
    assert ids == sorted(set(ids), key=ids.index)  # no duplicates
    assert set(QUESTIONNAIRE_BY_ID) == set(ids)


def test_every_catalog_answer_signal_is_schema_legal():
    # Catch a mush-shaped catalog entry at test time: every signal must name a
    # real axis, with a legal target/mode/weight. We do this by feeding each
    # answer's signals through MirrorState.apply_choice, which is the same
    # validation path the reducer uses.
    for question in QUESTIONNAIRE:
        for answer_id, signals in question.answers:
            state = MirrorState.new()
            state.apply_choice(
                # Choice ctor is irrelevant; we only care apply_choice accepts
                # the signal payload.
                _make_choice(answer_id, signals)
            )


def test_every_seeded_axis_exists_and_has_sane_dynamics():
    # The questionnaire deliberately does NOT seed `frustration` (STATE) or
    # `boundary_testing` (only observable from behavior). Anything else seeded
    # must point at a TRAIT axis in the schema.
    seeded: set[str] = set()
    for question in QUESTIONNAIRE:
        for _, signals in question.answers:
            for signal in signals:
                seeded.add(signal.attribute)
    assert seeded.issubset(MIRROR_SCHEMA)
    assert "frustration" not in seeded, "frustration is STATE — seeding it is mush"
    assert "boundary_testing" not in seeded, "boundary_testing is observed, not declared"


# --- the encoding contract ----------------------------------------------------


def test_empty_answers_emit_no_events_and_reduce_to_blank_mirror():
    assert encode({}) == ()
    assert seed_state({}) == MirrorState.new()


def test_event_order_is_catalog_order_not_input_dict_order():
    # Two dicts with the same content but different iteration order must
    # produce byte-identical event tuples.
    a = {
        "preferred_experience": "mystery",
        "problem_solving": "talk",
        "preferred_difficulty": "relax",
    }
    b = {
        "preferred_difficulty": "relax",
        "preferred_experience": "mystery",
        "problem_solving": "talk",
    }
    events_a = encode(a)
    events_b = encode(b)
    assert events_a == events_b
    # And the order matches the catalog (preferred_experience precedes
    # preferred_difficulty precedes problem_solving in QUESTIONNAIRE).
    qids = [q.id for q in QUESTIONNAIRE]
    emitted_qids = [_qid_from_choice_id(e.choice_id) for e in events_a]
    assert emitted_qids == [q for q in qids if q in a]


def test_each_event_has_self_describing_choice_id_and_intake_scene():
    events = encode({
        "preferred_experience": "mystery",
        "authority_disposition": "refuse",
    })
    assert all(e.scene_id == INTAKE_SCENE_ID for e in events)
    assert events[0].choice_id == "intake:preferred_experience:mystery"
    assert events[1].choice_id == "intake:authority_disposition:refuse"
    assert all(e.choice_id.startswith(INTAKE_CHOICE_PREFIX + ":") for e in events)


def test_skipping_a_question_is_allowed_and_emits_nothing_for_it():
    events = encode({"preferred_experience": "mystery"})
    assert len(events) == 1
    assert events[0].choice_id == "intake:preferred_experience:mystery"


def test_unknown_question_id_is_rejected():
    with pytest.raises(KeyError, match="unknown questionnaire question"):
        encode({"favorite_color": "blue"})


def test_unknown_answer_id_is_rejected_with_helpful_message():
    with pytest.raises(KeyError, match="unknown answer 'space_opera'"):
        encode({"preferred_experience": "space_opera"})


# --- the reducer turns intake events into a starting MirrorState --------------


def test_seed_state_reduces_the_same_events_encode_emits():
    answers = {
        "preferred_experience": "mystery",
        "preferred_difficulty": "relax",
        "problem_solving": "talk",
        "authority_disposition": "question",
        "avoid_in_experience": "nothing",
    }
    # seed_state is exactly: reduce(encode(answers)). Pin both paths agree.
    assert seed_state(answers) == reduce(encode(answers))


def test_worked_example_yields_a_differentiated_starting_state():
    """The 'curious, cautious, talker' example from docs/INTAKE.md §4."""
    answers = {
        "preferred_experience": "mystery",
        "preferred_difficulty": "relax",
        "problem_solving": "talk",
        "authority_disposition": "question",
        "avoid_in_experience": "nothing",
    }
    state = seed_state(answers)

    # Curiosity above its 0.5 neutral, with non-zero confidence.
    assert state.readings["curiosity"].value > 0.5
    assert state.readings["curiosity"].confidence > 0.0

    # Risk_tolerance below its 0.0 neutral (cautious).
    assert state.readings["risk_tolerance"].value < 0.0
    assert state.readings["risk_tolerance"].confidence > 0.0

    # Authority_trust below its 0.0 neutral (mildly defiant).
    assert state.readings["authority_trust"].value < 0.0

    # Playstyle: conversation share above the uniform 0.25 prior.
    mix = state.readings["playstyle_mix"].value
    spec = MIRROR_SCHEMA["playstyle_mix"]
    assert mix[spec.modes.index("conversation")] > 0.25
    assert sum(mix) == pytest.approx(1.0)

    # boundary_testing and frustration are NOT seeded by the questionnaire.
    assert state.readings["boundary_testing"].value == 0.5  # unit neutral
    assert state.readings["boundary_testing"].confidence == 0.0
    assert state.readings["frustration"].value == 0.0
    assert state.readings["frustration"].confidence == 0.0


def test_intake_state_is_not_mush():
    # Three different questionnaires should produce three meaningfully different
    # starting states: a defiant power-fantasy player, a cautious survivor, and
    # an optimizer who likes consequences.
    defiant = seed_state({
        "preferred_experience": "power_fantasy",
        "authority_disposition": "refuse",
        "preferred_difficulty": "tested",
    })
    cautious = seed_state({
        "preferred_experience": "survival",
        "preferred_difficulty": "relax",
        "avoid_in_experience": "loss",
        "problem_solving": "avoid",
    })
    optimizer = seed_state({
        "preferred_experience": "strategy",
        "problem_solving": "outsmart",
        "preferred_difficulty": "consequences",
    })

    # Authority_trust separates defiant from optimizer (who didn't answer it).
    assert defiant.readings["authority_trust"].value < -0.1
    assert optimizer.readings["authority_trust"].value == 0.0

    # Risk_tolerance separates cautious from defiant.
    assert cautious.readings["risk_tolerance"].value < -0.1
    assert defiant.readings["risk_tolerance"].value > 0.0

    # Playstyle_mix points at different modes for each archetype.
    mix_spec = MIRROR_SCHEMA["playstyle_mix"]
    assert _dominant_mode(defiant, mix_spec.modes) == "combat"
    assert _dominant_mode(optimizer, mix_spec.modes) == "optimization"


# --- determinism: same input → byte-identical output --------------------------


def test_encode_is_deterministic():
    answers = {
        "preferred_experience": "moral_dilemmas",
        "problem_solving": "experiment",
    }
    first = encode(answers)
    second = encode(answers)
    assert first == second
    # And the underlying signal tuples (frozen dataclasses) are equal too.
    assert all(a.signals == b.signals for a, b in zip(first, second))


def test_seed_log_round_trips_through_json_to_identical_state():
    answers = {
        "preferred_experience": "mystery",
        "preferred_difficulty": "relax",
        "problem_solving": "talk",
        "authority_disposition": "question",
        "avoid_in_experience": "nothing",
    }
    log = seed_log(answers)
    assert isinstance(log, EventLog)
    restored = EventLog.from_json(log.to_json())
    assert restored.events == log.events
    assert restored.reduce() == log.reduce()
    assert log.reduce() == seed_state(answers)


def test_full_intake_followed_by_play_extends_the_same_log():
    # The intake events are real events: appending in-fiction events after them
    # is just append-only log growth, with no special "promote intake to state"
    # step. This is the architectural promise the doc makes.
    intake_log = seed_log({"preferred_experience": "mystery"})
    after_play = intake_log.append(
        ChoiceObserved(
            choice_id="inspect_exit",
            signals=(Signal.toward("boundary_testing", 1.0),),
            scene_id="lab_observation_room",
        )
    )
    state = after_play.reduce()
    # Both the intake seed (curiosity > 0.5) and the in-fiction nudge
    # (boundary_testing > 0.5) are present, with no axis mush in between.
    assert state.readings["curiosity"].value > 0.5
    assert state.readings["boundary_testing"].value > 0.5
    # Unsignaled axes are still at their neutrals with confidence 0.
    assert state.readings["moral_consistency"].value == 0.5
    assert state.readings["moral_consistency"].confidence == 0.0


# --- the encoding is total over every catalog answer --------------------------


def test_every_answer_can_be_encoded_and_reduced():
    # Pick each answer in turn, encode it as a single-answer questionnaire,
    # and confirm both encode() and the reducer accept it.
    for question in QUESTIONNAIRE:
        for answer_id, _signals in question.answers:
            events = encode({question.id: answer_id})
            assert len(events) == 1
            assert events[0].choice_id == (
                f"{INTAKE_CHOICE_PREFIX}:{question.id}:{answer_id}"
            )
            # The reducer must accept every catalog answer without raising.
            state = reduce(events)
            # And at least one axis has moved off neutral unless the answer is
            # explicitly inert (signals == ()).
            signaled_axes = {s.attribute for s in events[0].signals}
            for name, reading in state.readings.items():
                if name in signaled_axes:
                    continue
                spec = MIRROR_SCHEMA[name]
                if spec.kind is AttributeKind.DISTRIBUTION:
                    assert reading.value == spec.neutral_value()
                else:
                    assert reading.value == spec.neutral
                assert reading.confidence == 0.0


# --- helpers ------------------------------------------------------------------


def _make_choice(choice_id: str, signals: tuple[Signal, ...]):
    from mirror.state import Choice
    return Choice(id=choice_id, signals=signals)


def _qid_from_choice_id(choice_id: str) -> str:
    # "intake:<question_id>:<answer_id>" -> "<question_id>"
    _, qid, _ = choice_id.split(":", 2)
    return qid


def _dominant_mode(state: MirrorState, modes: tuple[str, ...]) -> str:
    mix = state.readings["playstyle_mix"].value
    return modes[max(range(len(modes)), key=lambda i: mix[i])]
