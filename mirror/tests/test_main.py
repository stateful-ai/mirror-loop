"""The ``python -m mirror`` CLI contract.

Two pinned promises:

1. ``--help`` works on a clean checkout (no subcommand or argument can be
   needed to discover the CLI), and the default action (no subcommand) keeps
   running the schema gate the module always exposed.
2. ``play`` emits the gate-shaped session log as JSON on stdout, and
   ``--baseline`` toggles the **single shared adaptation seam** to the identity
   transform — same engine, same code path, only the variant differs. The
   non-baseline default plays the adaptive arm. The same ``--seed`` reproduces
   the same session byte-for-byte, in either arm.
"""

from __future__ import annotations

import json

import pytest

from mirror.__main__ import main


def test_help_runs_and_lists_play_subcommand(capsys):
    # `python -m mirror --help` is the discovery surface; it must not require a
    # subcommand or any prior setup. argparse exits 0 on --help.
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    assert "play" in out
    assert "schema" in out


def test_default_runs_schema_gate(capsys):
    # No subcommand keeps the prior contract: print the schema and report 0
    # iff the coherence review passes. We don't assert the body; the schema
    # tests cover that. We assert the gate succeeds and that *something*
    # schema-shaped was printed so a regression to a different default is loud.
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Mirror player-state schema" in out


def test_explicit_schema_subcommand_matches_default(capsys):
    assert main(["schema"]) == 0
    out = capsys.readouterr().out
    assert "Mirror player-state schema" in out


def _stdout_is_session_log(out: str) -> dict:
    log = json.loads(out)
    assert set(log) >= {"session_id", "act", "variant", "decision_points"}
    return log


def test_play_emits_adaptive_session_log_by_default(capsys):
    assert main(["play"]) == 0
    log = _stdout_is_session_log(capsys.readouterr().out)
    assert log["variant"] == "adaptive"
    # The default world is the five-loop spine; the session runner enforces
    # the 3-5 loop target, so we just sanity-check the range.
    assert 3 <= len(log["decision_points"]) <= 5


def test_play_baseline_flips_seam_to_identity(capsys):
    # --baseline must land on the "fixed" variant (the identity-transform arm
    # of game.variants); that is the whole point of the seam-as-strategy
    # design — no forked code path. The log self-labels the arm so a future
    # regression is visible.
    assert main(["play", "--baseline"]) == 0
    log = _stdout_is_session_log(capsys.readouterr().out)
    assert log["variant"] == "fixed"
    assert 3 <= len(log["decision_points"]) <= 5


def test_play_seed_is_reproducible(capsys):
    assert main(["play", "--seed", "7"]) == 0
    first = capsys.readouterr().out
    assert main(["play", "--seed", "7"]) == 0
    second = capsys.readouterr().out
    # Byte-identical: same seed → same scripted persona → same engine trace.
    assert first == second
    _stdout_is_session_log(first)


def test_play_baseline_with_seed_is_reproducible(capsys):
    assert main(["play", "--baseline", "--seed", "3"]) == 0
    first = capsys.readouterr().out
    assert main(["play", "--baseline", "--seed", "3"]) == 0
    second = capsys.readouterr().out
    assert first == second
    log = _stdout_is_session_log(first)
    assert log["variant"] == "fixed"


def test_play_uses_shared_seam_no_forked_path():
    # Pins the structural property the task and the docs both call out: the
    # mirror CLI builds its variant through the shared seam factory
    # (game.variants.build_variant) and hands it to play_session — there is no
    # second baseline-only code path. Asserted by inspecting the source of
    # _run_play so a future refactor that adds an `if baseline: ...` branch on
    # top of a forked runner gets caught by the test, not by review.
    import inspect

    from mirror.__main__ import _run_play

    source = inspect.getsource(_run_play)
    assert "play_session(" in source
    assert "build_variant(" in source
    # The only conditional on `baseline` is the variant-name selection: a
    # bare `if baseline` block (a second code path) would show up as more
    # `baseline` references than the single conditional expression.
    assert source.count("baseline") <= 3  # signature, comment, conditional
