"""``python -m mirror validate-fixture`` — shape-check an intake fixture file.

A fixture (e.g. ``fixtures/seed42_answers.json``) is the input ``--answers``
mode reads: a flat JSON object mapping ``question_id -> answer_id``. The
canonical play path validates the fixture *implicitly* by trying to encode it,
which is the right behavior at runtime but is awkward when a contributor wants
to ask, ahead of time, "is this fixture I just edited well-formed against the
current schema?" — they shouldn't have to capture an event log to find out.

This module makes that question first-class. It walks the same two-layer
contract the runtime relies on:

1. **Shape** — the file is valid JSON and a flat ``dict[str, str]``.
   Delegates to :func:`mirror.play.load_answers` so the structural rule has one
   definition.
2. **Semantics** — every key is a known
   :class:`~mirror.intake.QuestionnaireQuestion` id and every value is a known
   answer id for *that* question, against the live ``QUESTIONNAIRE`` catalog.
   No silent coercion, no "we'll absorb it."

Validation reports the *first* error so the caller can fix one thing and
re-run, exactly like a compiler's first-error mode. The CLI exit code is ``0``
on success and ``1`` on the first failure — the contract a CI fixture lint can
rely on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mirror.intake import QUESTIONNAIRE_BY_ID
from mirror.play import load_answers


@dataclass(frozen=True)
class FixtureValidation:
    """The outcome of validating one fixture file.

    ``ok`` is true when no error was found. ``error`` is the human-readable
    first-error message when ``ok`` is false, and ``None`` otherwise — there
    is never a non-empty error on a successful validation, so callers can
    safely branch on either field.
    """

    ok: bool
    error: str | None = None

    @classmethod
    def success(cls) -> "FixtureValidation":
        return cls(ok=True, error=None)

    @classmethod
    def failure(cls, message: str) -> "FixtureValidation":
        return cls(ok=False, error=message)


def validate_answers_mapping(
    answers: Mapping[str, str], *, strict: bool = False
) -> FixtureValidation:
    """Validate an already-loaded ``{question_id: answer_id}`` mapping.

    Checks each entry against :data:`~mirror.intake.QUESTIONNAIRE_BY_ID`:
    unknown question ids and unknown answer ids each produce a precise
    first-error message that names the offending id and lists the valid set.
    Iteration order matches the input mapping's iteration order so two runs on
    the same dict report the same first error.

    A partially-completed questionnaire is *valid* — :func:`mirror.intake.encode`
    skips absent questions on purpose, and this validator mirrors that rule so
    it never flags a fixture the runtime would happily accept.

    ``strict`` is currently equivalent to the default behavior: the
    "every option the answers reference exists in the schema today" check is
    already unconditional, because an unknown answer id is rejected at intake
    time. The flag is accepted so the CLI surface stays stable as the intake
    catalog grows additional stricter-only checks (e.g. requiring a complete
    questionnaire). Callers can pass ``strict=True`` today as a "future-proof"
    no-op without their code breaking when stricter checks land.
    """
    del strict  # see docstring — currently unconditional, kept for API stability.

    for question_id, answer_id in answers.items():
        question = QUESTIONNAIRE_BY_ID.get(question_id)
        if question is None:
            valid = sorted(QUESTIONNAIRE_BY_ID)
            return FixtureValidation.failure(
                f"unknown question id {question_id!r}; valid: {valid!r}"
            )
        valid_answers = question.answer_ids()
        if answer_id not in valid_answers:
            return FixtureValidation.failure(
                f"unknown answer {answer_id!r} for question {question_id!r}; "
                f"valid: {list(valid_answers)!r}"
            )
    return FixtureValidation.success()


#: Sentinel error message produced when ``validate_fixture`` is handed a path
#: that doesn't exist. The CLI matches on it to promote "missing file" to its
#: own exit code (2), without library code needing a second return channel.
#: Kept in module scope so tests can match against it without scraping the
#: error string.
MISSING_FILE_MARKER = "fixture file not found"


def validate_fixture(path: str | Path, *, strict: bool = False) -> FixtureValidation:
    """Validate a fixture file end-to-end (shape + semantics).

    Returns the first error encountered (file missing, not JSON, wrong root
    shape, non-string entry, unknown question, unknown answer) or
    :meth:`FixtureValidation.success` if the file is a well-formed answer set
    against the live questionnaire. Never raises for a validation failure —
    a failing fixture is data, not an exception. Other I/O errors (e.g. a
    permission denied) propagate as themselves, since they are not "this
    fixture is invalid", they are "we couldn't read the file at all".

    A missing file is still a *validation* failure — the returned error
    message begins with :data:`MISSING_FILE_MARKER`, which the CLI matches on
    to map to a dedicated exit code so a CI lint can branch on "fixture
    wrong" vs "fixture not found" without parsing the rest of the message.

    ``strict`` is forwarded to :func:`validate_answers_mapping`; see its
    docstring for what it enables.
    """
    fixture_path = Path(path)
    if not fixture_path.exists():
        return FixtureValidation.failure(
            f"{MISSING_FILE_MARKER}: {str(fixture_path)!r}"
        )
    try:
        answers = load_answers(fixture_path)
    except ValueError as exc:
        return FixtureValidation.failure(str(exc))
    return validate_answers_mapping(answers, strict=strict)
