"""Ahead-of-time validation for intake-answers fixtures.

This module is the static counterpart to the implicit "try to encode this and
see what blows up" check :func:`mirror.intake.encode` performs at intake time.
A fixture (``fixtures/seed42_answers.json`` and friends) is just a JSON map of
``{question_id: answer_id}``; the runtime is happy to consume an incomplete
intake but loud about a malformed one. The validator pins that contract so a
contributor can catch the easy malformations — typo'd question id, typo'd
answer id, wrong root shape, junk JSON, missing file — *before* trying to play
the fixture.

The semantic rules live in one place: :data:`mirror.intake.QUESTIONNAIRE_BY_ID`
and each :class:`~mirror.intake.QuestionnaireQuestion`'s answer set. The
validator reads them, it does not redefine them. The same applies to the
fixture file shape — see :func:`mirror.play.load_answers` for the matching
runtime check; this module re-implements only the *checks* (not the loader)
so it can produce one structured, fix-by-reading :class:`FixtureValidation`
without coupling to the play CLI's exception-style error path.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mirror.intake import QUESTIONNAIRE_BY_ID


@dataclass(frozen=True)
class FixtureValidation:
    """The result of validating one fixture.

    A single ``error`` string is intentional: the validator reports the
    *first* problem it finds and stops, mirroring how a contributor would
    fix a fixture (one error at a time). ``ok=True`` always has
    ``error is None``.
    """

    ok: bool
    error: str | None = None

    @classmethod
    def success(cls) -> "FixtureValidation":
        return cls(ok=True, error=None)

    @classmethod
    def failure(cls, error: str) -> "FixtureValidation":
        return cls(ok=False, error=error)


def validate_answers_mapping(
    answers: Mapping[str, str],
    *,
    strict: bool = False,
) -> FixtureValidation:
    """Check a decoded ``{question_id: answer_id}`` mapping against the schema.

    Every question id must exist in :data:`~mirror.intake.QUESTIONNAIRE_BY_ID`
    and every answer id must be a valid answer for its question. A partial
    questionnaire is accepted — :func:`mirror.intake.encode` skips absent
    questions on purpose, so the validator must too.

    ``strict`` is currently equivalent to the default behavior: the option-set
    check ("every option the answers reference exists in the schema today") is
    already an unconditional rule, because an unknown answer id is rejected at
    intake time. The flag is accepted so the CLI surface stays stable as the
    intake catalog grows additional, weaker checks that *only* run under
    ``--strict`` (e.g. requiring a complete questionnaire).
    """
    del strict  # see docstring — currently unconditional, kept for API stability.

    for question_id, answer_id in answers.items():
        question = QUESTIONNAIRE_BY_ID.get(question_id)
        if question is None:
            valid = sorted(QUESTIONNAIRE_BY_ID)
            return FixtureValidation.failure(
                f"unknown question id {question_id!r}; valid question ids: {valid!r}"
            )
        valid_answers = list(question.answer_ids())
        if answer_id not in valid_answers:
            return FixtureValidation.failure(
                f"unknown answer {answer_id!r} for question {question_id!r}; "
                f"valid answers: {valid_answers!r}"
            )
    return FixtureValidation.success()


def validate_fixture(path: str | Path, *, strict: bool = False) -> FixtureValidation:
    """Validate the fixture file at ``path``.

    The checks, in order:

    1. The file must exist (a missing file is a validation failure with a
       precise message, never a stray :class:`FileNotFoundError`).
    2. Its contents must be valid JSON.
    3. The root must be a JSON object (intake answers are a map, not a list).
    4. Each key and value must be a string.
    5. Semantically, the answers must satisfy
       :func:`validate_answers_mapping`.
    """
    fixture_path = Path(path)
    if not fixture_path.exists():
        return FixtureValidation.failure(f"fixture file {str(fixture_path)!r} not found")
    try:
        text = fixture_path.read_text(encoding="utf-8")
    except OSError as exc:  # unreadable but present
        return FixtureValidation.failure(
            f"fixture file {str(fixture_path)!r} could not be read: {exc}"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return FixtureValidation.failure(
            f"fixture file {str(fixture_path)!r} is not valid JSON: {exc}"
        )
    if not isinstance(data, dict):
        return FixtureValidation.failure(
            f"fixture file {str(fixture_path)!r} must be a JSON object mapping "
            f"question_id -> answer_id; got {type(data).__name__}"
        )
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return FixtureValidation.failure(
                f"fixture file {str(fixture_path)!r} must map string question_id "
                f"-> string answer_id; got {key!r} -> {value!r}"
            )
    return validate_answers_mapping(data, strict=strict)
