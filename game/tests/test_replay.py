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
    JSONL_SPEC_VERSION,
    M1_CANONICAL_FIXTURE,
    RunResult,
    canonical_dumps,
    canonical_run,
    load_golden,
    load_m1_canonical,
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


# --- m1_canonical.jsonl: the founder-brief event-stream fixture -----------------


def test_m1_canonical_fixture_lives_at_the_brief_declared_path():
    # The M1 founder brief names this file as `fixtures/m1_canonical.jsonl` at
    # the repo root (not under any package), so the byte-identity gate has a
    # single, locatable home that future contributors can find from the brief
    # alone.
    assert M1_CANONICAL_FIXTURE == REPO_ROOT / "fixtures" / "m1_canonical.jsonl"
    assert M1_CANONICAL_FIXTURE.exists()


def test_canonical_run_matches_the_committed_m1_jsonl_fixture():
    # The acceptance criterion for the fixture-capture task: re-running the
    # canonical seed-42 run produces a byte-identical `fixtures/m1_canonical.jsonl`.
    # If this fails after an intended change, regenerate with
    # `python -m game.replay --write-m1-fixture` and review the diff.
    assert canonical_run().to_jsonl() == load_m1_canonical()


def test_m1_jsonl_is_byte_identical_across_two_runs():
    # Two in-process runs of the canonical pair produce identical bytes — the
    # JSONL-level analogue of `test_same_seed_and_log_are_byte_identical`, so a
    # regression in JSONL serialization (key order, separators, line endings)
    # fails here rather than only showing up via the committed-fixture diff.
    assert canonical_run().to_jsonl() == canonical_run().to_jsonl()


def test_m1_jsonl_holds_byte_identity_across_processes_and_hash_seeds():
    # Same claim as the JSON gate, but for the JSONL form: a separate process
    # under a different PYTHONHASHSEED must emit the same bytes. This catches
    # any silent dependency on dict-iteration order or interpreter entropy in
    # the new serializer.
    def render(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "game.replay",
                "--format",
                "jsonl",
                "--seed",
                str(DEFAULT_SEED),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    assert render("0") == render("1") == canonical_run().to_jsonl()


def test_m1_jsonl_fixture_is_well_formed_and_self_describing():
    text = load_m1_canonical()
    # Canonical: trailing newline, no leading/trailing blank lines.
    assert text.endswith("\n")
    lines = text.rstrip("\n").split("\n")
    # 1 header + one record per slot + 1 trailer.
    assert len(lines) == 1 + DEFAULT_WORLD.length + 1

    records = [json.loads(line) for line in lines]
    head, *loops, tail = records

    # Every record carries the canonical-spec stamps (`event_seq` logical
    # clock, `event_id` content hash). Compare the run header by the fields
    # the header is *responsible for*; the stamps are pinned by their own
    # tests below so the assertion here stays specific.
    head_body = {k: v for k, v in head.items() if k not in {"event_seq", "event_id"}}
    assert head_body == {
        "type": "run",
        "jsonl_spec_version": JSONL_SPEC_VERSION,
        "seed": DEFAULT_SEED,
        "variant": BASELINE_VARIANT,
        "world": DEFAULT_WORLD.name,
        "input_log": list(CANONICAL_INPUT_LOG),
    }
    assert [r["type"] for r in loops] == ["loop"] * DEFAULT_WORLD.length
    assert [r["loop_index"] for r in loops] == list(range(DEFAULT_WORLD.length))
    assert [r["actual_action"] for r in loops] == list(CANONICAL_INPUT_LOG)
    assert tail["type"] == "final_state"
    # The trailer matches the in-process final state — the JSONL is a faithful
    # serialization of the same run the JSON snapshot covers, not a parallel
    # universe with its own data path.
    expected_final = canonical_run().snapshot()["final_state"]
    tail_body = {
        k: v for k, v in tail.items() if k not in {"type", "event_seq", "event_id"}
    }
    assert tail_body == expected_final


def test_m1_jsonl_lines_are_compact_canonical_json():
    # Each JSONL line is a single JSON object with sorted keys and no extra
    # whitespace; this is what makes line-by-line diffs informative and keeps
    # the file from carrying serialization-only churn.
    text = load_m1_canonical()
    for line in text.rstrip("\n").split("\n"):
        record = json.loads(line)
        assert canonical_dumps(record) == line


def test_cli_check_m1_passes_against_the_committed_fixture(capsys):
    assert main(["--check-m1"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_format_jsonl_emits_the_canonical_event_stream(capsys):
    assert main(["--format", "jsonl"]) == 0
    assert capsys.readouterr().out == canonical_run().to_jsonl()


def test_cli_check_m1_detects_drift(tmp_path, monkeypatch, capsys):
    stale = tmp_path / "stale.jsonl"
    stale.write_text("{\"type\":\"run\"}\n", encoding="utf-8")
    monkeypatch.setattr("game.replay.M1_CANONICAL_FIXTURE", stale)
    assert main(["--check-m1"]) == 1
    assert "FAIL" in capsys.readouterr().err


# --- JSONL spec: logical clock, deterministic ids, pinned serialization --------
# The three properties folded into the canonical JSONL spec
# (:data:`JSONL_SPEC_VERSION`). Each test below is the byte-identity claim
# expressed against one of those properties in isolation, so a regression in
# (e.g.) the id derivation fails here rather than only through the committed
# m1_canonical.jsonl diff.


def test_every_jsonl_record_carries_event_seq_and_event_id():
    # The two determinism-load-bearing stamps are present on every line —
    # header, every loop, and the trailer alike. The clock is monotonic
    # 0..N-1 across the whole stream (a single logical clock, not per-type).
    records = canonical_run().jsonl_records()
    assert [r["event_seq"] for r in records] == list(range(len(records)))
    assert all(isinstance(r["event_id"], str) and len(r["event_id"]) == 16 for r in records)


def test_event_ids_are_unique_per_run():
    # Two records with identical bodies but different positions get distinct
    # ids because event_seq is part of the hash input. In a real run every
    # record's body is already unique; this is the defensive property.
    records = canonical_run().jsonl_records()
    ids = [r["event_id"] for r in records]
    assert len(ids) == len(set(ids))


def test_event_ids_are_deterministic_across_runs():
    # The headline same-seed property *for ids*: two runs of the same
    # ``(seed, input_log, variant, world)`` produce per-line-identical ids.
    # A drift in any single field would localize to the one line whose id moved.
    a = [r["event_id"] for r in canonical_run().jsonl_records()]
    b = [r["event_id"] for r in canonical_run().jsonl_records()]
    assert a == b


def test_event_id_is_a_content_hash_of_the_rest_of_the_record():
    # The id is derivable from the record itself — not from external state,
    # not from a clock, not from a counter we have to trust. A third party
    # reading a line can verify it.
    from game.replay import _event_id_for

    for record in canonical_run().jsonl_records():
        body = {k: v for k, v in record.items() if k != "event_id"}
        assert record["event_id"] == _event_id_for(body)


def test_perturbing_a_single_field_moves_only_that_lines_event_id():
    # The point of a per-line content hash: drift in one field is localized
    # to one id. This is the "any single bit-flip in the canonical bytes is
    # detectable, and *localized*" property.
    from game.replay import _event_id_for

    records = canonical_run().jsonl_records()
    perturbed = [dict(r) for r in records]
    # Flip a single character in one loop record's actual_action.
    perturbed[2]["actual_action"] = perturbed[2]["actual_action"] + "_x"
    body = {k: v for k, v in perturbed[2].items() if k != "event_id"}
    new_id = _event_id_for(body)
    assert new_id != records[2]["event_id"]
    # The other lines' ids are independent of that mutation.
    for i, (orig, mod) in enumerate(zip(records, perturbed)):
        if i == 2:
            continue
        assert orig["event_id"] == _event_id_for(
            {k: v for k, v in mod.items() if k != "event_id"}
        )


def test_canonical_dumps_is_insensitive_to_dict_insertion_order():
    # The headline acceptance criterion: "insertion-order perturbation leaves
    # canonical bytes unchanged". Two dicts built in opposite orders, with
    # nested mappings whose keys are also inserted out of order, produce
    # byte-identical output.
    forward = {"a": 1, "b": {"x": 10, "y": 20}, "c": [1, 2, 3]}
    reverse = {}
    reverse["c"] = [1, 2, 3]
    reverse["b"] = {}
    reverse["b"]["y"] = 20
    reverse["b"]["x"] = 10
    reverse["a"] = 1
    assert canonical_dumps(forward) == canonical_dumps(reverse)


def test_canonical_dumps_pins_compact_separators_and_sorted_keys():
    # The two visible knobs of the spec: no incidental whitespace, and
    # alphabetical key order. Asserted on a small dict so a future drift in
    # `canonical_dumps` (e.g. someone re-introducing `indent=`) is caught
    # without re-running the full canonical pipeline.
    assert canonical_dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_dumps_refuses_nan_and_infinity():
    # NaN/Infinity have no canonical JSON encoding; emitting them would
    # produce JS-only tokens that aren't roundtrip-required. Refuse at
    # serialization time so a future field that accidentally produced one
    # fails loudly here rather than silently breaking the byte-identity gate.
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("inf")})
    with pytest.raises(ValueError):
        canonical_dumps({"x": float("-inf")})


def test_canonical_dumps_finite_floats_use_shortest_round_trip():
    # Finite floats serialize with Python's shortest-round-trip repr — the
    # same number on any platform produces the same string. This is what
    # keeps a future field that *does* carry a float (e.g. a confidence
    # value) byte-identical across hosts.
    s1 = canonical_dumps({"v": 0.1 + 0.2})
    s2 = canonical_dumps({"v": 0.1 + 0.2})
    assert s1 == s2
    # The shortest-round-trip property: parsing it back yields exactly the
    # same float (and so the same string a second time).
    assert canonical_dumps(json.loads(s1)) == s1


def test_jsonl_run_header_uses_the_jsonl_spec_version_not_the_snapshot_version():
    # The JSONL spec and the JSON snapshot are two independent
    # serializations. The wire field is `jsonl_spec_version` (not
    # `schema_version`) precisely so the bytes a consumer reads disambiguate
    # which constant they refer to — otherwise the JSON snapshot's
    # `schema_version` and the JSONL spec's would name-collide on the wire.
    head = canonical_run().jsonl_records()[0]
    assert head["jsonl_spec_version"] == JSONL_SPEC_VERSION
    assert "schema_version" not in head
