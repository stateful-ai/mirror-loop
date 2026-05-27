"""Tests for ``python -m mirror play`` — the questionnaire-intake CLI.

These pin the acceptance contract for ``--answers <file>`` mode: it must run
with **no TTY prompt** and produce **the same log** as a scripted interactive
run on the same answers. Two paths through one encoder is the architectural
guarantee; these tests are how it stops being a guarantee on paper.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mirror import __main__ as cli
from mirror.intake import QUESTIONNAIRE, seed_log, seed_state
from mirror.log import EventLog
from mirror.play import load_answers, prompt_answers, run

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED42_FIXTURE = REPO_ROOT / "fixtures" / "seed42_answers.json"
SEED42_AGGRESSION_FIXTURE = REPO_ROOT / "fixtures" / "seed42_answers_aggression.json"


# --- the committed seed42 fixtures --------------------------------------------
#
# The pair documents the caution- vs aggression-leaning canonical inputs the
# M1 founder brief locks the Mirror axis to ("caution ↔ aggression"). Both
# fixtures answer the full questionnaire so a downstream consumer can pick
# either as a starting state and exercise the same intake path end-to-end.


def test_seed42_answers_fixture_exists_and_is_a_full_questionnaire():
    """The fixture exists, is JSON, and answers every catalog question."""
    assert SEED42_FIXTURE.exists(), (
        f"missing fixture {SEED42_FIXTURE}; this is the canonical answers file "
        f"the acceptance command line `python -m mirror play --seed 42 "
        f"--answers fixtures/seed42_answers.json` reads from"
    )
    answers = load_answers(SEED42_FIXTURE)
    assert set(answers) == {q.id for q in QUESTIONNAIRE}, (
        "the canonical fixture should answer every question so that CI exercises "
        "the full intake path, not a partial one"
    )


def test_seed42_answers_fixture_encodes_under_the_current_schema():
    """The fixture's answers are all valid under the live intake catalog."""
    # `seed_log` calls `encode`, which raises KeyError on any unknown question
    # or answer id — so this is the schema-validity assertion for the fixture.
    log = seed_log(load_answers(SEED42_FIXTURE))
    assert isinstance(log, EventLog)
    assert len(log.events) == len(QUESTIONNAIRE)


def test_seed42_aggression_fixture_exists_and_is_a_full_questionnaire():
    """The aggression-leaning sibling exists and answers every catalog question."""
    assert SEED42_AGGRESSION_FIXTURE.exists(), (
        f"missing fixture {SEED42_AGGRESSION_FIXTURE}; this is the aggression-"
        f"leaning canonical answers file the README 'Try it' block references "
        f"alongside the caution-leaning default at {SEED42_FIXTURE}"
    )
    answers = load_answers(SEED42_AGGRESSION_FIXTURE)
    assert set(answers) == {q.id for q in QUESTIONNAIRE}, (
        "the aggression-leaning canonical fixture should answer every question "
        "so it is a complete twin of the caution-leaning default"
    )


def test_seed42_aggression_fixture_encodes_under_the_current_schema():
    """The aggression-leaning fixture's answers are valid under the live catalog."""
    log = seed_log(load_answers(SEED42_AGGRESSION_FIXTURE))
    assert isinstance(log, EventLog)
    assert len(log.events) == len(QUESTIONNAIRE)


def test_seed42_caution_and_aggression_diverge_on_the_mirror_axis():
    """The pair seeds opposite leans on caution ↔ aggression.

    The M1 brief locks the Mirror axis to ``caution ↔ aggression`` and the
    DoD requires that two distinct answer sets produce a *visibly* divergent
    run. The intake-only contract is the weaker, deterministic-from-answers
    half of that: the two fixtures must reduce to MirrorStates whose
    ``risk_tolerance`` and ``authority_trust`` signs are *opposite*, so any
    downstream consumer that reads those axes sees two genuinely different
    starting players rather than two paraphrases of the same one.
    """
    caution = seed_state(load_answers(SEED42_FIXTURE))
    aggression = seed_state(load_answers(SEED42_AGGRESSION_FIXTURE))

    caution_risk = float(caution.readings["risk_tolerance"].value)
    aggression_risk = float(aggression.readings["risk_tolerance"].value)
    assert caution_risk < 0.0 < aggression_risk, (
        f"caution should seed risk_tolerance below 0 (cautious pole) and "
        f"aggression above 0 (reckless pole); got "
        f"{caution_risk=}, {aggression_risk=}"
    )

    caution_trust = float(caution.readings["authority_trust"].value)
    aggression_trust = float(aggression.readings["authority_trust"].value)
    assert aggression_trust < 0.0 < caution_trust, (
        f"caution should seed authority_trust above 0 (deferential) and "
        f"aggression below 0 (defiant); got "
        f"{caution_trust=}, {aggression_trust=}"
    )


# --- load_answers: shape + error messages -------------------------------------


def test_load_answers_round_trips_the_seed42_fixture():
    assert load_answers(SEED42_FIXTURE) == json.loads(
        SEED42_FIXTURE.read_text(encoding="utf-8")
    )


def test_load_answers_rejects_non_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_answers(bad)


def test_load_answers_rejects_non_object_root(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_answers(bad)


def test_load_answers_rejects_non_string_value(tmp_path):
    bad = tmp_path / "wrongtype.json"
    bad.write_text(
        json.dumps({"preferred_experience": ["mystery"]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="string answer_id"):
        load_answers(bad)


# --- prompt_answers: interactive flow without a real TTY ----------------------


def _scripted_lines(*lines: str):
    """A fake ``read_line`` that yields lines as if the user typed them."""
    queue = iter(line + ("\n" if not line.endswith("\n") else "") for line in lines)

    def read_line() -> str:
        return next(queue)

    return read_line


def test_prompt_answers_collects_a_full_questionnaire_from_stdin():
    # Picking option 1 for every question — the first answer of each is a real
    # one in the catalog so this exercises every prompt.
    read_line = _scripted_lines(*(["1"] * len(QUESTIONNAIRE)))
    buf = io.StringIO()
    answers = prompt_answers(read_line=read_line, write=buf.write)
    assert set(answers) == {q.id for q in QUESTIONNAIRE}
    for question in QUESTIONNAIRE:
        first_answer_id = question.answers[0][0]
        assert answers[question.id] == first_answer_id
    # Every question's prompt rendered to stderr (here, the StringIO buffer).
    rendered = buf.getvalue()
    for question in QUESTIONNAIRE:
        assert question.prompt in rendered


def test_prompt_answers_treats_blank_as_skip():
    read_line = _scripted_lines(*(["" for _ in QUESTIONNAIRE]))
    answers = prompt_answers(read_line=read_line, write=lambda _s: None)
    assert answers == {}  # nothing recorded; intake reduces to the blank mirror


def test_prompt_answers_reprompts_on_invalid_input_then_accepts_a_valid_one():
    # First two questions answered cleanly, third gets a typo before a valid pick.
    n = len(QUESTIONNAIRE)
    lines = ["1"] * (n - 1) + ["banana", "2"]
    read_line = _scripted_lines(*lines)
    buf = io.StringIO()
    answers = prompt_answers(read_line=read_line, write=buf.write)
    assert len(answers) == n
    # The reprompt nudge was rendered exactly once.
    assert buf.getvalue().count("enter the number of a listed answer") == 1


def test_prompt_answers_raises_eof_when_stdin_closes_mid_questionnaire():
    # Returning "" simulates EOF. A non-interactive caller that forgot to pass
    # --answers must fail loudly rather than silently produce an empty log.
    def read_line() -> str:
        return ""

    with pytest.raises(EOFError, match="--answers"):
        prompt_answers(read_line=read_line, write=lambda _s: None)


# --- the two paths produce the SAME log (the acceptance contract) -------------


def test_answers_file_log_equals_scripted_interactive_log():
    """``--answers FILE`` yields the same log as a scripted interactive run."""
    answers = load_answers(SEED42_FIXTURE)

    # Path A — the non-interactive file mode (no TTY, no stdin).
    from_file = run(seed=42, answers_path=SEED42_FIXTURE)

    # Path B — a scripted interactive run that types the same answers. Pick the
    # option number that matches each fixture answer so the prompt loop ends up
    # collecting the same dict.
    typed_lines: list[str] = []
    for question in QUESTIONNAIRE:
        answer_id = answers[question.id]
        option_index = next(
            i + 1 for i, (aid, _s) in enumerate(question.answers) if aid == answer_id
        )
        typed_lines.append(str(option_index))
    from_stdin = run(
        seed=42,
        read_line=_scripted_lines(*typed_lines),
        write=lambda _s: None,
    )

    assert from_file == from_stdin
    # And both equal the direct intake encoding — the engine is the same one.
    assert from_file == seed_log(answers).to_json()


def test_run_rejects_both_answers_and_path():
    with pytest.raises(ValueError, match="not both"):
        run(answers_path=SEED42_FIXTURE, answers={"preferred_experience": "mystery"})


def test_run_seed_does_not_affect_the_emitted_log():
    """Intake is deterministic from the answers alone — the seed is forward-compat."""
    answers = load_answers(SEED42_FIXTURE)
    assert run(seed=0, answers=answers) == run(seed=999_999, answers=answers)


# --- end-to-end: invoking `python -m mirror play` via cli.main ----------------


def test_cli_play_with_answers_writes_log_to_stdout_only(capsys):
    rc = cli.main(["play", "--seed", "42", "--answers", str(SEED42_FIXTURE)])
    captured = capsys.readouterr()
    assert rc == 0
    # Nothing went to stderr — the --answers mode is silent (no TTY prompts).
    assert captured.err == ""
    # Stdout is the EventLog as JSON, round-trips to the same log.
    log = EventLog.from_json(captured.out)
    assert log == seed_log(load_answers(SEED42_FIXTURE))


def test_cli_default_still_prints_the_schema(capsys):
    """The historical no-arg behavior is preserved (README, founder brief)."""
    rc = cli.main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Mirror player-state schema" in captured.out
    assert "fingerprint:" in captured.out


def test_cli_play_rejects_missing_answers_file(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError):
        cli.main(["play", "--answers", str(missing)])


def test_cli_play_rejects_malformed_answers_file(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        cli.main(["play", "--answers", str(bad)])


def test_cli_play_propagates_intake_validation_errors(tmp_path):
    """Unknown question/answer ids must surface the intake KeyError unchanged."""
    bad = tmp_path / "wrong_answer.json"
    bad.write_text(
        json.dumps({"preferred_experience": "space_opera"}), encoding="utf-8"
    )
    with pytest.raises(KeyError, match="unknown answer 'space_opera'"):
        cli.main(["play", "--answers", str(bad)])


# --- a true "no TTY" subprocess run, the way CI invokes the command -----------


def test_subprocess_invocation_runs_with_no_tty_input():
    """Smoke: the documented acceptance command line works under closed stdin.

    Runs ``python -m mirror play --seed 42 --answers fixtures/seed42_answers.json``
    with stdin closed (``stdin=DEVNULL``) — the *literal* "no TTY" condition the
    acceptance criterion names — and verifies the stdout payload round-trips
    through :meth:`EventLog.from_json` to the same log the direct encoder
    produces. This is the closest analogue to how CI / fixture capture invokes
    the command.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mirror",
            "play",
            "--seed",
            "42",
            "--answers",
            str(SEED42_FIXTURE),
        ],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert result.stderr == b""  # no TTY prompts went to stderr
    log = EventLog.from_json(result.stdout.decode("utf-8"))
    assert log == seed_log(load_answers(SEED42_FIXTURE))
