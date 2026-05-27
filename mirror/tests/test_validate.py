"""Tests for ``python -m mirror validate-fixture`` and :mod:`mirror.validate`.

The validator is meant to be the *ahead-of-time* version of the implicit
"try to encode this and see what blows up" check the runtime does at intake
time. These tests pin that contract: anything :func:`mirror.intake.encode`
would accept must validate ``OK``, and the kinds of malformations a
contributor is most likely to introduce (typo'd question id, typo'd answer
id, wrong root shape, junk JSON) must each surface as the first error with
a precise, fix-by-reading message.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mirror import __main__ as cli
from mirror.intake import QUESTIONNAIRE
from mirror.validate import (
    FixtureValidation,
    validate_answers_mapping,
    validate_fixture,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED42_FIXTURE = REPO_ROOT / "fixtures" / "seed42_answers.json"


# --- validate_answers_mapping (the pure semantic check) -----------------------


def test_validate_answers_accepts_committed_seed42_fixture():
    """The canonical fixture is the contract the runtime already accepts.

    If the validator ever flags it, either the fixture drifted or the
    validator got stricter than the runtime — both are bugs.
    """
    answers = json.loads(SEED42_FIXTURE.read_text(encoding="utf-8"))
    result = validate_answers_mapping(answers)
    assert result == FixtureValidation.success()


def test_validate_answers_accepts_partial_questionnaire():
    """A partial questionnaire is valid — encode() skips absent questions.

    Pins that the validator does not over-reach: "incomplete" is not the same
    as "malformed", and the runtime is happy to seed from a partial intake.
    """
    first_question = QUESTIONNAIRE[0]
    first_answer_id = first_question.answer_ids()[0]
    result = validate_answers_mapping({first_question.id: first_answer_id})
    assert result.ok, result.error


def test_validate_answers_rejects_unknown_question_id():
    """A typo'd question id surfaces as the first error with the valid set."""
    result = validate_answers_mapping({"preferred_xperience": "personal_growth"})
    assert not result.ok
    assert result.error is not None
    assert "unknown question id" in result.error
    assert "preferred_xperience" in result.error
    # The error must enumerate the valid set so the reader can spot the typo.
    assert "preferred_experience" in result.error


def test_validate_answers_rejects_unknown_answer_id():
    """An invalid answer for a *known* question names the question + valid set."""
    result = validate_answers_mapping({"preferred_experience": "definitely_not_a_real_answer"})
    assert not result.ok
    assert result.error is not None
    assert "unknown answer" in result.error
    assert "preferred_experience" in result.error
    assert "definitely_not_a_real_answer" in result.error


# --- validate_fixture (file-level shape + semantics) --------------------------


def test_validate_fixture_ok_on_committed_seed42(tmp_path):
    """End-to-end: shape + semantics OK on the canonical committed file."""
    result = validate_fixture(SEED42_FIXTURE)
    assert result == FixtureValidation.success()


def test_validate_fixture_reports_missing_file(tmp_path):
    """A missing file is a validation failure, not a stray FileNotFoundError.

    We promise the CLI does not crash on a typo'd path — it prints the first
    error and exits 1. The function-level contract is the same.
    """
    missing = tmp_path / "no_such_fixture.json"
    result = validate_fixture(missing)
    assert not result.ok
    assert result.error is not None
    assert "not found" in result.error


def test_validate_fixture_reports_invalid_json(tmp_path):
    """Junk JSON is reported as not-valid-JSON, not as a missing question."""
    bad = tmp_path / "broken.json"
    bad.write_text("{not json at all", encoding="utf-8")
    result = validate_fixture(bad)
    assert not result.ok
    assert result.error is not None
    assert "not valid JSON" in result.error


def test_validate_fixture_reports_wrong_root_shape(tmp_path):
    """A list at the root is shape-rejected (intake answers must be an object)."""
    listish = tmp_path / "list_root.json"
    listish.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    result = validate_fixture(listish)
    assert not result.ok
    assert result.error is not None
    assert "JSON object" in result.error


# --- CLI integration ----------------------------------------------------------


def test_cli_validate_fixture_prints_ok_on_seed42(capsys):
    """`python -m mirror validate-fixture <seed42>` → "OK" on stdout, exit 0."""
    rc = cli.main(["validate-fixture", str(SEED42_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out.strip() == "OK"


def test_cli_validate_fixture_exits_nonzero_on_bad_answer(tmp_path, capsys):
    """Invalid answer → error on stderr, "OK" never printed, exit 1."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"preferred_experience": "definitely_not_a_real_answer"}),
        encoding="utf-8",
    )
    rc = cli.main(["validate-fixture", str(bad)])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "unknown answer" in captured.err


def test_cli_validate_fixture_subprocess_end_to_end():
    """Full `python -m mirror validate-fixture` smoke against the real file.

    Matches the spirit of test_play.py's subprocess smoke: the wired CLI must
    actually work, not just the in-process handler.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "mirror", "validate-fixture", str(SEED42_FIXTURE)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "OK"
