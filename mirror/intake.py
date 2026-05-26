"""Questionnaire intake → seed-event encoding.

The Mirror Loop opens with a short questionnaire (``docs/game_design.md`` §5),
diegetically a lab "personalized experience" intake. Mechanically it is the
first place the Mirror gets to seed its player model — before the player has
made an in-fiction choice the system can observe.

This module is the **deterministic** bridge between a questionnaire JSON blob
and the event log the Mirror reduces. Same answers in → same events out, in a
fixed catalog order, regardless of the input dict's iteration order. The events
are real :class:`~mirror.log.ChoiceObserved` records, so the existing reducer
turns them into a starting :class:`~mirror.state.MirrorState` with no special
case: the questionnaire is just the first chapter of the same append-only log.

The architecture rule stays intact: the **event log is the source of truth** and
the Mirror is a pure reduction over it (``docs/MIRROR_SCHEMA.md`` §6). A
questionnaire is a content-layer detail; the engine sees only events.

See :data:`QUESTIONNAIRE` for the answer→signal catalog (the documented mapping)
and ``docs/INTAKE.md`` for the rationale behind each answer's signals.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mirror.log import ChoiceObserved, EventLog, reduce
from mirror.state import MirrorState, Signal


#: Provenance ``scene_id`` stamped onto every intake event. Lets a downstream
#: reader separate the questionnaire prelude from in-fiction play in one filter.
INTAKE_SCENE_ID = "intake_questionnaire"

#: Prefix on the synthetic ``choice_id`` for an intake event. The full id is
#: ``intake:<question_id>:<answer_id>`` so it is self-describing in the log and
#: collision-free with any real in-fiction choice id.
INTAKE_CHOICE_PREFIX = "intake"


@dataclass(frozen=True)
class QuestionnaireQuestion:
    """One question + its closed set of answers and their evidence.

    Each answer is paired with the tuple of :class:`~mirror.state.Signal` it
    emits. Keeping the answer order tuple-stable (not dict-keyed) is what makes
    the encoding deterministic: the catalog defines both *which* answers are
    valid and *in what order* events are emitted.
    """

    id: str
    prompt: str
    #: ``(answer_id, signals)`` pairs, ordered as authored.
    answers: tuple[tuple[str, tuple[Signal, ...]], ...]

    def answer_ids(self) -> tuple[str, ...]:
        return tuple(aid for aid, _ in self.answers)

    def signals_for(self, answer_id: str) -> tuple[Signal, ...]:
        """Return the signals for ``answer_id`` or raise ``KeyError``."""
        for aid, signals in self.answers:
            if aid == answer_id:
                return signals
        raise KeyError(
            f"unknown answer {answer_id!r} for question {self.id!r}; "
            f"valid answers: {list(self.answer_ids())}"
        )


# --- The catalog: the documented mapping --------------------------------------
#
# Anti-mush discipline: declared preference is *softer* evidence than observed
# behavior, so most signals carry ``weight=0.5`` rather than the in-fiction
# default of 1.0. This means a single in-game action overrides a single
# questionnaire prior, which is the design intent ("dual interpretation" in
# game_design.md §5.2: stated preference is a seed, not the truth).
#
# The schema's STATE axis (frustration) and the boundary_testing axis are NOT
# seeded from the questionnaire on purpose:
#
# - frustration is fast affect ("how do they feel right now") and decays each
#   turn; seeding it pre-play would relax to noise before the first scene.
# - boundary_testing is "do they actually poke the system" — only observable
#   from in-fiction behavior, not a thing you can sincerely self-declare.

_WEIGHT = 0.5

QUESTIONNAIRE: tuple[QuestionnaireQuestion, ...] = (
    QuestionnaireQuestion(
        id="preferred_experience",
        prompt="What kind of experience would you like today?",
        answers=(
            ("mystery", (
                Signal.toward("curiosity", 1.0, _WEIGHT),
            )),
            ("adventure", (
                Signal.toward("risk_tolerance", 1.0, _WEIGHT),
                Signal.spend("playstyle_mix", "exploration", _WEIGHT),
            )),
            ("strategy", (
                Signal.spend("playstyle_mix", "optimization", _WEIGHT),
            )),
            ("survival", (
                Signal.toward("risk_tolerance", -1.0, _WEIGHT),
                Signal.toward("failure_recovery", 1.0, _WEIGHT),
            )),
            ("personal_growth", (
                Signal.toward("moral_consistency", 1.0, _WEIGHT),
            )),
            ("moral_dilemmas", (
                Signal.toward("moral_consistency", 1.0, _WEIGHT),
                Signal.spend("playstyle_mix", "conversation", _WEIGHT),
            )),
            ("power_fantasy", (
                Signal.toward("authority_trust", -1.0, _WEIGHT),
                Signal.spend("playstyle_mix", "combat", _WEIGHT),
            )),
            ("social_drama", (
                Signal.spend("playstyle_mix", "conversation", _WEIGHT),
            )),
        ),
    ),
    QuestionnaireQuestion(
        id="preferred_difficulty",
        prompt="How much resistance do you want?",
        answers=(
            ("relax", (
                Signal.toward("risk_tolerance", -1.0, _WEIGHT),
            )),
            ("some_resistance", (
                Signal.toward("risk_tolerance", -1.0, _WEIGHT / 2),
            )),
            ("tested", (
                Signal.toward("risk_tolerance", 1.0, _WEIGHT),
                Signal.toward("failure_recovery", 1.0, _WEIGHT),
            )),
            ("consequences", (
                Signal.toward("risk_tolerance", 1.0, _WEIGHT),
                Signal.toward("moral_consistency", 1.0, _WEIGHT),
            )),
        ),
    ),
    QuestionnaireQuestion(
        id="problem_solving",
        prompt="How do you usually solve problems?",
        answers=(
            ("talk", (
                Signal.spend("playstyle_mix", "conversation", _WEIGHT),
            )),
            ("fight", (
                Signal.spend("playstyle_mix", "combat", _WEIGHT),
                Signal.toward("risk_tolerance", 1.0, _WEIGHT / 2),
            )),
            ("explore", (
                Signal.spend("playstyle_mix", "exploration", _WEIGHT),
                Signal.toward("curiosity", 1.0, _WEIGHT / 2),
            )),
            ("outsmart", (
                Signal.spend("playstyle_mix", "optimization", _WEIGHT),
            )),
            ("avoid", (
                Signal.toward("risk_tolerance", -1.0, _WEIGHT),
            )),
            ("experiment", (
                Signal.spend("playstyle_mix", "exploration", _WEIGHT),
                Signal.toward("curiosity", 1.0, _WEIGHT),
            )),
        ),
    ),
    QuestionnaireQuestion(
        id="authority_disposition",
        prompt="When someone in charge tells you what to do, you tend to…",
        answers=(
            ("comply", (
                Signal.toward("authority_trust", 1.0, _WEIGHT),
            )),
            ("question", (
                Signal.toward("authority_trust", -1.0, _WEIGHT / 2),
                Signal.toward("curiosity", 1.0, _WEIGHT / 2),
            )),
            ("refuse", (
                Signal.toward("authority_trust", -1.0, _WEIGHT),
            )),
        ),
    ),
    QuestionnaireQuestion(
        id="avoid_in_experience",
        prompt="What should the experience avoid?",
        answers=(
            # An empty-signal answer is the "nothing in particular" choice. It
            # is still recorded as an event (so the log faithfully reflects what
            # the player answered) but is inert at reduce time.
            ("nothing", ()),
            ("failure", (
                # failure_recovery is UNIT [0, 1] — "tilts / disengages" is 0.
                Signal.toward("failure_recovery", 0.0, _WEIGHT),
            )),
            ("loss", (
                Signal.toward("risk_tolerance", -1.0, _WEIGHT),
            )),
            ("confusion", (
                # curiosity is UNIT [0, 1] — "incurious" is 0.
                Signal.toward("curiosity", 0.0, _WEIGHT / 2),
            )),
            ("helplessness", (
                Signal.toward("authority_trust", -1.0, _WEIGHT),
            )),
        ),
    ),
)


#: Index from question id to question, for cheap lookup. The canonical order is
#: always :data:`QUESTIONNAIRE`'s tuple order; this map is for validation only.
QUESTIONNAIRE_BY_ID: dict[str, QuestionnaireQuestion] = {q.id: q for q in QUESTIONNAIRE}


def encode(answers: Mapping[str, str]) -> tuple[ChoiceObserved, ...]:
    """Encode a questionnaire answer set as a deterministic event sequence.

    ``answers`` maps question id → answer id. Iteration order of the input is
    irrelevant: events are always emitted in :data:`QUESTIONNAIRE`'s declared
    order, and each event's ``choice_id`` is the self-describing
    ``intake:<question>:<answer>``.

    Questions absent from ``answers`` are skipped (the questionnaire may be
    partially completed). An *unknown* question id or an *invalid* answer id is
    rejected loudly — a malformed questionnaire is a bug, not "we'll absorb it."
    """
    unknown_questions = set(answers) - set(QUESTIONNAIRE_BY_ID)
    if unknown_questions:
        raise KeyError(
            f"unknown questionnaire question(s): {sorted(unknown_questions)!r}; "
            f"valid: {sorted(QUESTIONNAIRE_BY_ID)!r}"
        )

    events: list[ChoiceObserved] = []
    for question in QUESTIONNAIRE:
        if question.id not in answers:
            continue
        answer_id = answers[question.id]
        signals = question.signals_for(answer_id)
        events.append(
            ChoiceObserved(
                choice_id=f"{INTAKE_CHOICE_PREFIX}:{question.id}:{answer_id}",
                signals=signals,
                scene_id=INTAKE_SCENE_ID,
            )
        )
    return tuple(events)


def seed_log(answers: Mapping[str, str]) -> EventLog:
    """Build a fresh :class:`EventLog` whose only contents are the intake events.

    Stamped with the current schema version/fingerprint so it round-trips and
    refuses replay under a drifted schema like any other log.
    """
    return EventLog(events=encode(answers))


def seed_state(answers: Mapping[str, str]) -> MirrorState:
    """Reduce the intake events to the starting :class:`MirrorState`.

    The reducer is the regular one in ``mirror/log.py`` — the questionnaire is
    not a special case in the engine. With no answers this returns the blank
    mirror (every axis unknown), so passing ``{}`` is a valid "skip intake".
    """
    return reduce(encode(answers))
