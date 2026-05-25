"""The ``python -m game`` CLI contract.

The one promise the gate relies on: ``--log`` prints the session log as JSON and
*nothing else* on stdout, so a real playthrough pipes straight into the
acceptance scorer. Interactive prompts and the Mirror's live reactions belong on
stderr — never mixed into that machine-readable stream.
"""

from __future__ import annotations

import io
import json

from game.__main__ import main


def _stdout_is_session_log(out: str) -> dict:
    """Parse stdout as the gate-shaped session log, failing loudly if it isn't."""
    log = json.loads(out)
    assert set(log) >= {"session_id", "act", "decision_points"}
    return log


def test_log_without_input_emits_only_json_on_stdout(monkeypatch, capsys):
    # `python -m game --log </dev/null`: no input, so interactive play hits EOF
    # and falls back to the demo. stdout must still be parseable as JSON alone.
    monkeypatch.setattr("sys.stdin", io.StringIO(""))

    assert main(["--log"]) == 0

    captured = capsys.readouterr()
    _stdout_is_session_log(captured.out)


def test_log_with_interactive_choices_keeps_stdout_pure_json(monkeypatch, capsys):
    # A real player drives five choices; the prompts they see go to stderr while
    # stdout carries only the final JSON log.
    monkeypatch.setattr("sys.stdin", io.StringIO("1\n1\n1\n1\n1\n"))

    assert main(["--log"]) == 0

    captured = capsys.readouterr()
    log = _stdout_is_session_log(captured.out)
    assert len(log["decision_points"]) == 5
    assert "LOOP 1" in captured.err  # the prompts landed on stderr, not stdout


def test_log_with_persona_emits_only_json_on_stdout(capsys):
    assert main(["--log", "--persona", "kind"]) == 0

    captured = capsys.readouterr()
    _stdout_is_session_log(captured.out)
    assert captured.err == ""


def test_variant_toggle_labels_the_log_and_keeps_stdout_pure(capsys):
    # The A/B toggle is reflected in the (machine-readable) log; the seeded random
    # arm stays deterministic and still emits only JSON on stdout.
    assert main(["--log", "--persona", "kind", "--variant", "random", "--seed", "7"]) == 0

    captured = capsys.readouterr()
    log = _stdout_is_session_log(captured.out)
    assert log["variant"] == "random"
    assert captured.err == ""


def test_variant_defaults_to_adaptive(capsys):
    assert main(["--log", "--persona", "kind"]) == 0
    log = _stdout_is_session_log(capsys.readouterr().out)
    assert log["variant"] == "adaptive"
