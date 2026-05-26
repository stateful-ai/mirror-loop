"""Tests for the two M1 CI gates and their dry-run determinism-break harness.

These pin the contract the acceptance bar requires:

1. **The two required checks exist, are named consistently across the
   workflow YAML, the gates module, and `docs/CI.md`, and their pytest
   selections are real (collect-only resolves them).**
2. **On a clean tree both gate runners exit 0** — pure smoke, but it
   guarantees the runner modules themselves do not have an import-time bug
   that would red the required check before any test ran.
3. **The dry-run flips both gates red** — for each break the targeted gate
   exits non-zero and the other stays green, the working tree is restored
   byte-for-byte afterwards, and the CLI ``--break`` selector behaves.

Together those pins are what makes "two GH Actions jobs both required in
branch protection; deliberate determinism break flips them red in a dry run"
mechanically true on every commit.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from ci import dry_run
from ci.gates import (
    ALL_GATES,
    BASELINE_ADAPTIVE_PARITY,
    BASELINE_ADAPTIVE_PARITY_CHECK,
    BYTE_IDENTITY_REPLAY,
    BYTE_IDENTITY_REPLAY_CHECK,
    REPO_ROOT,
    Gate,
)

WORKFLOWS = REPO_ROOT / ".github" / "workflows"


# --- Gate names: one source of truth across YAML / Python / docs ----------------


def test_both_gates_have_distinct_stable_names():
    assert BYTE_IDENTITY_REPLAY_CHECK == BYTE_IDENTITY_REPLAY.name == "byte-identity-replay"
    assert (
        BASELINE_ADAPTIVE_PARITY_CHECK
        == BASELINE_ADAPTIVE_PARITY.name
        == "baseline-adaptive-parity"
    )
    assert ALL_GATES == (BYTE_IDENTITY_REPLAY, BASELINE_ADAPTIVE_PARITY)


@pytest.mark.parametrize("gate", ALL_GATES, ids=lambda g: g.name)
def test_every_gate_has_a_workflow_with_a_matching_job_id(gate: Gate):
    # The branch-protection check name == workflow `jobs.<id>`. The YAMLs do
    # both: the file is named after the check, and the job id matches. We do
    # a substring check so we do not need a YAML dependency in test deps.
    workflow_path = WORKFLOWS / f"{gate.name}.yml"
    assert workflow_path.exists(), (
        f"missing workflow for required check {gate.name!r}: {workflow_path}"
    )
    body = workflow_path.read_text(encoding="utf-8")
    assert f"name: {gate.name}\n" in body
    assert f"  {gate.name}:\n" in body, (
        f"workflow {workflow_path} must declare a job id matching the "
        f"required check name {gate.name!r}"
    )
    # Each workflow must invoke the corresponding runner module so the test
    # selection in ci/gates.py is what CI actually runs.
    module = {
        BYTE_IDENTITY_REPLAY.name: "ci.byte_identity_replay",
        BASELINE_ADAPTIVE_PARITY.name: "ci.baseline_adaptive_parity",
    }[gate.name]
    assert f"python -m {module}" in body


@pytest.mark.parametrize("gate", ALL_GATES, ids=lambda g: g.name)
def test_every_gate_pytest_selection_resolves(gate: Gate):
    # ``pytest --collect-only`` returns 0 only when every node id resolves.
    # If we ever delete or rename a test that the gate selects by name, this
    # test fails before CI does.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *gate.pytest_nodes],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"gate {gate.name!r} selects unknown pytest nodes:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def test_docs_ci_md_names_both_required_checks():
    # The docs page is normative for branch-protection setup; the check names
    # must be reachable from it verbatim so a repo admin can copy-paste.
    docs = (REPO_ROOT / "docs" / "CI.md").read_text(encoding="utf-8")
    assert BYTE_IDENTITY_REPLAY_CHECK in docs
    assert BASELINE_ADAPTIVE_PARITY_CHECK in docs


# --- Clean-tree smoke: both runners exit 0 ---------------------------------------


@pytest.mark.parametrize(
    "module",
    ["ci.byte_identity_replay", "ci.baseline_adaptive_parity"],
)
def test_runner_module_exits_zero_on_clean_tree(module: str):
    proc = subprocess.run(
        [sys.executable, "-m", module],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"clean-tree {module} unexpectedly red:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


# --- The dry-run: deliberate determinism breaks flip the gates red ---------------


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_break_a_flips_only_byte_identity_red():
    [outcome] = dry_run.run(["A"])
    assert outcome.label == "A"
    assert outcome.ok, outcome
    # Spell it out: red is *non-zero*, green is exactly zero.
    assert outcome.red_exit_code != 0
    assert outcome.green_exit_code == 0


def test_dry_run_break_b_flips_only_parity_red():
    [outcome] = dry_run.run(["B"])
    assert outcome.label == "B"
    assert outcome.ok, outcome
    assert outcome.red_exit_code != 0
    assert outcome.green_exit_code == 0


def test_dry_run_default_runs_both_breaks_and_overall_passes():
    outcomes = dry_run.run()
    labels = [o.label for o in outcomes]
    assert labels == ["A", "B"]
    assert all(o.ok for o in outcomes), outcomes


@pytest.mark.parametrize(
    "spec",
    dry_run.BREAKS,
    ids=[b.label for b in dry_run.BREAKS],
)
def test_dry_run_restores_each_target_file_byte_for_byte(spec):
    # Run *just* this break and verify the file the break mutates is
    # byte-identical afterwards. The dry-run wraps the mutation in
    # try/finally, and we trust-but-verify here.
    before = _file_digest(spec.target_path)
    dry_run.run([spec.label])
    after = _file_digest(spec.target_path)
    assert before == after, (
        f"dry-run did not restore {spec.target_path}; the working tree is "
        "left dirty, which would corrupt subsequent runs"
    )


def test_dry_run_restores_files_even_when_a_break_outcome_is_unexpected(monkeypatch):
    # Force the gate-runner subprocess call to claim "expected-red gate was
    # actually green" (i.e. a meta-failure of the break). The dry-run must
    # still restore the mutated file — the cleanup is in a `finally`, not
    # an `else`.
    spec = next(b for b in dry_run.BREAKS if b.label == "A")
    before = _file_digest(spec.target_path)
    monkeypatch.setattr(dry_run, "_run_gate_silently", lambda _gate: 0)
    outcomes = dry_run.run(["A"])
    assert not outcomes[0].ok  # red gate did not go red — meta-failure surfaced
    assert _file_digest(spec.target_path) == before


def test_dry_run_rejects_unknown_break_label():
    with pytest.raises(ValueError, match="unknown break"):
        dry_run.run(["Z"])


def test_dry_run_cli_runs_and_reports(capsys):
    code = dry_run.main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "Overall: PASS" in out
    # The report names both breaks so a CI log reader can confirm both ran.
    assert "Break A" in out and "Break B" in out


def test_dry_run_cli_selects_a_single_break(capsys):
    code = dry_run.main(["--break", "A"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Break A" in out
    assert "Break B" not in out


def test_dry_run_cli_rejects_unknown_break(capsys):
    with pytest.raises(SystemExit) as exc:
        dry_run.main(["--break", "Z"])
    # argparse exits with code 2 on a usage error; the report is never printed.
    assert exc.value.code == 2
    assert "Break A" not in capsys.readouterr().out
