"""The seeded baseline replay harness — the byte-identity acceptance gate.

This task's acceptance criteria, each pinned below:

* **runs end-to-end from a seed** — :func:`game.replay.run` takes ``(seed,
  input_log)`` and returns a completed, fully serializable session.
* **identical ``(seed, input log)`` reproduces byte-identical state across two
  runs** — two runs (and two *processes*, with different ``PYTHONHASHSEED``)
  produce an identical canonical snapshot; a committed golden fixture guards
  against drift across commits.
* **no wall-clock or unsynced randomness in game logic** — an AST scan of the
  runtime packages proves it: nothing reads the clock or the global RNG; the only
  randomness (the placebo arm) is a seeded ``random.Random``.
* **this build is the baseline arm** — the run goes through the ordinary
  :func:`game.session.play_session` with the seam toggled to a *baseline*
  variant (never a forked path), and its content is independent of the player.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from acceptance.predictability import evaluate
from game.replay import (
    BASELINE_VARIANT,
    CANONICAL_INPUT_LOG,
    DEFAULT_SEED,
    GOLDEN_FIXTURE,
    RunResult,
    canonical_run,
    load_golden,
    main,
    run,
)
from game.session import persona_policy, play_session, scripted_policy
from game.variants import build_variant
from game.world import DEFAULT_WORLD

REPO_ROOT = Path(__file__).resolve().parents[2]

# The non-adaptive arms this task ships as "the baseline arm": the seeded placebo
# and the identity transform. Both run through the same engine toggle.
BASELINE_ARMS = ("random", "fixed")

# A consistently *defiant* input log — one choice id per slot — used to show the
# baseline's content does not depend on how the player plays.
DEFIANT_INPUT_LOG = ("c_refuse", "c_breach", "c_doors", "c_walk", "c_break")


def _content(snapshot: dict) -> tuple:
    """The engine-produced part of a snapshot (everything except the recorded
    inputs), so seed/player independence can be compared without the ``run``
    block — which by design echoes the inputs back."""
    return (snapshot["loops"], snapshot["final_state"])


def _offered(snapshot: dict) -> list[tuple]:
    """The content the player was *shown* each loop: framing + choice order."""
    return [
        (loop["scene_id"], loop["branch_key"], tuple(loop["offered_order"]))
        for loop in snapshot["loops"]
    ]


# --- "runs end-to-end from a seed" ---------------------------------------------


def test_run_completes_the_full_spine_from_a_seed():
    result = run(DEFAULT_SEED, CANONICAL_INPUT_LOG)
    assert isinstance(result, RunResult)
    assert result.seed == DEFAULT_SEED
    assert result.session.loop_count == DEFAULT_WORLD.length == 5
    # Every input was consumed, in order, as the player's actual choice.
    assert [
        loop["actual_action"] for loop in result.snapshot()["loops"]
    ] == list(CANONICAL_INPUT_LOG)


def test_run_rejects_an_input_log_that_does_not_match_the_spine():
    with pytest.raises(ValueError, match="exactly one choice per loop"):
        run(DEFAULT_SEED, CANONICAL_INPUT_LOG[:3])
    with pytest.raises(ValueError, match="exactly one choice per loop"):
        run(DEFAULT_SEED, CANONICAL_INPUT_LOG + ("c_extra",))


def test_canonical_input_log_tracks_the_kind_persona():
    # The hand-written canonical log must equal what a "kind" player actually
    # chooses, so the constant can't silently drift from the authored world.
    played = play_session(
        persona_policy("kindness"),
        variant=build_variant(BASELINE_VARIANT, seed=DEFAULT_SEED),
    )
    assert tuple(r.result.actual_action for r in played.records) == CANONICAL_INPUT_LOG


# --- "identical (seed, input log) reproduces byte-identical state" --------------


@pytest.mark.parametrize("variant", BASELINE_ARMS)
@pytest.mark.parametrize("seed", [0, 1, 42, 9999])
def test_same_seed_and_log_are_byte_identical(variant, seed):
    first = run(seed, CANONICAL_INPUT_LOG, variant=variant).to_json()
    second = run(seed, CANONICAL_INPUT_LOG, variant=variant).to_json()
    assert first == second


def test_byte_identity_holds_across_processes_and_hash_seeds():
    # The strongest form of the claim: two *separate processes*, each with a
    # different PYTHONHASHSEED, must emit identical bytes. This proves the placebo
    # seed is hashed deterministically (not via the builtin, hash-randomised
    # `hash()`), so reproducibility never depends on the interpreter's entropy.
    def render(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        proc = subprocess.run(
            [sys.executable, "-m", "game.replay", "--seed", str(DEFAULT_SEED)],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    assert render("0") == render("1") == canonical_run().to_json()


# --- "this build is the baseline arm": seed load-bearing, player-independent -----


def test_placebo_seed_is_load_bearing():
    # The seeded baseline's *content* genuinely depends on the seed (otherwise the
    # "seeded" contract would be vacuous): different seeds, different rooms/orders.
    a = _content(run(1, CANONICAL_INPUT_LOG, variant="random").snapshot())
    b = _content(run(7, CANONICAL_INPUT_LOG, variant="random").snapshot())
    assert a != b


def test_fixed_baseline_content_is_seed_invariant():
    # The identity baseline has no randomness to seed, so its produced content is
    # identical across seeds (the seed only ever echoes into the `run` block).
    contents = [
        _content(run(seed, CANONICAL_INPUT_LOG, variant="fixed").snapshot())
        for seed in (0, 1, 42, 9999)
    ]
    assert all(content == contents[0] for content in contents[1:])


@pytest.mark.parametrize("variant", BASELINE_ARMS)
def test_baseline_content_is_independent_of_the_player(variant):
    # The defining property of a baseline arm: what the player is *shown* (framing
    # and choice order) does not track what they do. A kind player and a defiant
    # player, on the same seed, are offered byte-identical content.
    kind = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=variant).snapshot()
    defiant = run(DEFAULT_SEED, DEFIANT_INPUT_LOG, variant=variant).snapshot()
    assert _offered(kind) == _offered(defiant)


def test_canonical_run_uses_a_baseline_arm():
    result = canonical_run()
    assert result.variant == BASELINE_VARIANT
    assert result.variant in BASELINE_ARMS


# --- "no forked code path": replay only drives the shared engine ----------------


def test_replay_matches_the_shared_engine_entry_point():
    # The run must be the same engine as a direct play_session call (architecture
    # principle: the baseline is one toggle, never a fork). Drive both the same
    # way and assert the per-loop decision points are identical.
    arm = build_variant(BASELINE_VARIANT, seed=DEFAULT_SEED)
    direct = play_session(scripted_policy(CANONICAL_INPUT_LOG), variant=arm)
    replayed = canonical_run().session
    assert direct.decision_points() == replayed.decision_points()
    assert [r.branch_key for r in direct.records] == [
        r.branch_key for r in replayed.records
    ]


def test_snapshot_feeds_the_locked_acceptance_gate():
    # The serialized run carries gate-shaped decision points, so a baseline
    # playthrough drops into the locked predictability gate with no translation.
    result = canonical_run()
    points = result.session.decision_points()
    assert len(points) == result.session.loop_count
    assert evaluate(points).n == result.session.loop_count


# --- golden fixture: the byte-identity gate across commits -----------------------


def test_canonical_run_matches_the_committed_golden_fixture():
    # If this fails after an intended change, regenerate with
    # `python -m game.replay --write-fixture` and review the diff.
    assert canonical_run().to_json() == load_golden()


def test_golden_fixture_is_well_formed_and_self_describing():
    data = json.loads(load_golden())
    assert data["schema_version"] == 1
    assert data["run"] == {
        "seed": DEFAULT_SEED,
        "variant": BASELINE_VARIANT,
        "world": DEFAULT_WORLD.name,
        "input_log": list(CANONICAL_INPUT_LOG),
    }
    assert len(data["loops"]) == DEFAULT_WORLD.length


def test_snapshot_is_canonical_json_and_round_trips():
    text = canonical_run().to_json()
    # Canonical: sorted keys, trailing newline, and stable under a reparse.
    assert text.endswith("\n")
    reparsed = json.loads(text)
    assert json.dumps(reparsed, indent=2, sort_keys=True) + "\n" == text


# --- "no wall-clock or unsynced randomness in game logic" -----------------------
# An AST scan (not a text grep, so comments/docstrings can't cause false hits) of
# the runtime packages. It allows `import random` + `random.Random(...)` — the
# seeded RNG the placebo baseline uses — and forbids everything that would make a
# run depend on entropy or the clock.

_RUNTIME_PACKAGES = ("loop", "game", "mirror")
_BANNED_MODULES = frozenset({"time", "datetime", "secrets", "uuid"})


def _runtime_source_files() -> list[Path]:
    files: list[Path] = []
    for package in _RUNTIME_PACKAGES:
        for path in (REPO_ROOT / package).rglob("*.py"):
            parts = set(path.parts)
            if "tests" in parts or "__pycache__" in parts:
                continue
            files.append(path)
    return files


def _nondeterminism_findings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BANNED_MODULES:
                    findings.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in _BANNED_MODULES:
                findings.append(f"line {node.lineno}: from {module} import ...")
            if root == "random":
                # Force `import random; random.Random(...)`; importing names off
                # the module (e.g. `from random import random`) is banned.
                findings.append(f"line {node.lineno}: from random import ...")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base, attr = node.value.id, node.attr
            if base in _BANNED_MODULES:
                findings.append(f"line {node.lineno}: {base}.{attr}")
            elif base == "random" and attr != "Random":
                findings.append(f"line {node.lineno}: random.{attr}")
            elif base == "os" and attr == "urandom":
                findings.append(f"line {node.lineno}: os.urandom")
    return findings


def test_runtime_packages_have_no_clock_or_unsynced_randomness():
    offenders = {
        str(path.relative_to(REPO_ROOT)): findings
        for path in _runtime_source_files()
        if (findings := _nondeterminism_findings(path))
    }
    assert not offenders, (
        "game logic must not read the clock or use unsynced randomness "
        f"(only `random.Random(seed)` is allowed): {offenders}"
    )


def test_the_scan_actually_covers_the_runtime_and_can_catch_a_violation():
    # Guard the guard: it must inspect real files, and it must flag a known-bad
    # snippet (so a future no-op scan can't pass silently).
    files = {p.name for p in _runtime_source_files()}
    assert {"core.py", "session.py", "variants.py", "world.py"} <= files

    bad = REPO_ROOT / "game" / "__pycache__" / "_scan_probe.py"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(
        "import time\nimport random\nx = time.time() + random.random()\n",
        encoding="utf-8",
    )
    try:
        findings = _nondeterminism_findings(bad)
    finally:
        bad.unlink()
    assert any("time" in f for f in findings)
    assert any("random.random" in f for f in findings)


# --- CLI ------------------------------------------------------------------------


def test_cli_check_passes_against_the_committed_fixture(capsys):
    assert main(["--check"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_default_prints_the_canonical_snapshot(capsys):
    assert main([]) == 0
    assert capsys.readouterr().out == canonical_run().to_json()


def test_cli_accepts_a_seed_and_explicit_input_log(capsys):
    assert main(["--seed", "7", "--input", ",".join(CANONICAL_INPUT_LOG)]) == 0
    assert capsys.readouterr().out == run(7, CANONICAL_INPUT_LOG).to_json()


def test_cli_check_detects_drift(tmp_path, monkeypatch, capsys):
    # Point the gate at a stale fixture and confirm --check fails loudly.
    stale = tmp_path / "stale.json"
    stale.write_text("{\"schema_version\": 1}\n", encoding="utf-8")
    monkeypatch.setattr("game.replay.GOLDEN_FIXTURE", stale)
    assert main(["--check"]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_golden_fixture_path_is_tracked_and_present():
    assert GOLDEN_FIXTURE.exists()
    assert GOLDEN_FIXTURE.parent.name == "fixtures"
