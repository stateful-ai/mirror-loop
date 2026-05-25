"""Instrumentation, replay logging, and the determinism guardrail.

This task's acceptance criteria, each pinned below:

* **every input, Mirror transition, and fired adaptation is logged against the
  seed** — :func:`game.instrumentation.record_session` returns a seed-anchored
  :class:`~game.instrumentation.SessionTrace` whose per-loop log carries the
  player's input, the before/after Mirror snapshots plus the ranked forecast, and
  the fired :class:`~game.adaptation.Adaptation` records with their provenance.
* **a recorded session replays and the Reflection-beat moment is locatable from
  logs** — a trace serialised to JSON and reloaded replays to a byte-identical
  trace, and :meth:`SessionTrace.reflection_beats` locates the "Mirror noticed…"
  moment from the log alone.
* **an automated test asserts an identical state hash across N repeated runs of
  the same seed+inputs** — :func:`test_identical_state_hash_across_n_runs`, plus
  a cross-process check that the digest never depends on interpreter entropy.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from game.adaptation import AdaptationKind
from game.instrumentation import (
    SCHEMA_VERSION,
    LoopTrace,
    SessionTrace,
    canonical_trace,
    main,
    record_session,
    state_hash,
)
from game.replay import CANONICAL_INPUT_LOG, DEFAULT_SEED
from game.world import DEFAULT_WORLD

REPO_ROOT = Path(__file__).resolve().parents[2]

# How many repeats the determinism guardrail demands agree.
N_RUNS = 8

# A deliberately balanced player: two choices each across three tendencies (max
# count 2 < the notice threshold of 3), so the model never locks and no Reflection
# beat ever fires. One valid choice id per slot of the default world.
BALANCED_INPUT_LOG = ("c_measure", "c_breach", "c_help", "c_log", "c_break")


# --- "every input ... is logged against the seed" ------------------------------


def test_every_input_is_logged_against_the_seed():
    trace = canonical_trace()
    assert trace.seed == DEFAULT_SEED
    assert trace.variant == "adaptive"
    assert trace.world_name == DEFAULT_WORLD.name
    assert trace.input_log == CANONICAL_INPUT_LOG
    # One logged loop per input, each recording the choice that was made.
    assert len(trace.loops) == len(CANONICAL_INPUT_LOG)
    assert tuple(loop.input for loop in trace.loops) == CANONICAL_INPUT_LOG
    assert tuple(loop.loop_index for loop in trace.loops) == (0, 1, 2, 3, 4)


# --- "... Mirror transition ... is logged" -------------------------------------


def test_every_mirror_transition_is_logged_and_chains():
    trace = canonical_trace()
    for i, loop in enumerate(trace.loops):
        # The transition straddles the input: before has i prior choices, after
        # has i+1, and the Mirror always staked a non-empty ranked forecast.
        assert loop.transition.before.turn_count == i
        assert loop.transition.after.turn_count == i + 1
        assert loop.transition.predicted_actions
    # Continuity: each loop's "before" read is the prior loop's "after" read, so
    # the logged transitions form one unbroken chain.
    for prev, nxt in zip(trace.loops, trace.loops[1:]):
        assert nxt.transition.before == prev.transition.after


def test_forecast_tracks_the_locked_acceptance_vocabulary():
    # The forecast in the log is the same ranked prediction the gate scores; a
    # kind player on the kind log is predicted correctly once the model forms.
    trace = canonical_trace()
    # loop 0 has no history, so the forecast is just the declared order.
    assert trace.loops[0].transition.predicted_actions[0] == "c_reassure"
    # By the finale the Mirror leads with the kind option it has learned.
    assert trace.loops[-1].predicted_hit


# --- "... fired adaptation ... is logged" --------------------------------------


def test_fired_adaptations_are_logged_with_provenance():
    trace = canonical_trace()
    log = trace.adaptation_log()
    fired = {(a.kind, a.slot_key) for a in log.adaptations}
    # The kind run reveals tendency framings at the three branch slots ...
    assert (AdaptationKind.BRANCH_SELECTION, "records") in fired
    assert (AdaptationKind.BRANCH_SELECTION, "corridor") in fired
    assert (AdaptationKind.BRANCH_SELECTION, "exit") in fired
    # ... and re-orders the one fixed scene that declares the kind option last.
    assert (AdaptationKind.CHOICE_REORDERING, "confrontation") in fired

    # Every logged adaptation carries the snapshot it was a function of: the
    # trigger snapshot equals the loop's "before" read and the source event-seq is
    # the count of choices reduced so far (so it is replayable, not wall-clock).
    for loop in trace.loops:
        for adaptation in loop.adaptations:
            prov = adaptation.provenance
            assert prov.trigger_snapshot == loop.transition.before
            assert prov.source_event_seq == loop.transition.before.turn_count


def test_confrontation_reordering_surfaces_the_predicted_kind_choice():
    trace = canonical_trace()
    conf = next(loop for loop in trace.loops if loop.scene_id == "confrontation")
    reorder = next(
        a for a in conf.adaptations if a.kind is AdaptationKind.CHOICE_REORDERING
    )
    # The kind option (declared last in this scene) is lifted to the front.
    assert reorder.predicted_choice == "c_wait"
    assert reorder.ordering[0] == "c_wait"
    assert set(reorder.ordering) == {"c_wait", "c_walk", "c_log"}


def test_loop_one_fires_no_adaptation():
    # The opening intake has no history to adapt from: declared order is the
    # forecast, the slot is fixed, so nothing fires and nothing is logged.
    trace = canonical_trace()
    assert trace.loops[0].adaptations == ()
    assert not trace.loops[0].fired_adaptation


@pytest.mark.parametrize("variant", ["fixed", "random"])
def test_baseline_arm_logs_no_fired_adaptations(variant):
    # A baseline never bends content to the player, so the adaptation log is empty
    # by construction — but the Reflection beat (a render of state, not an
    # adaptation) still fires, keeping the A/B shell identical.
    trace = record_session(CANONICAL_INPUT_LOG, variant=variant, seed=DEFAULT_SEED)
    assert all(loop.adaptations == () for loop in trace.loops)
    assert trace.adaptation_log().adaptations == ()
    assert trace.first_reflection_beat() is not None


# --- "the Reflection-beat moment is locatable from logs" -----------------------


def test_reflection_beat_is_locatable_from_logs():
    # Reload from JSON first, so the beat is genuinely located *from the log*, not
    # from a live object the engine just produced.
    trace = SessionTrace.from_json(canonical_trace().to_json())
    beats = trace.reflection_beats()
    assert len(beats) == 1
    beat = beats[0]
    # The kind player crosses the notice threshold on the third kind choice
    # (the corridor), so the beat is locatable at exactly that loop.
    assert beat.loop_index == 2
    assert beat.scene_id == "corridor"
    assert "Mirror noticed" in beat.reflection
    assert "kindness" in beat.reflection
    assert trace.first_reflection_beat() == beat
    # The beat fires once and only once.
    assert sum(loop.reflected for loop in trace.loops) == 1


def test_no_reflection_beat_for_a_balanced_player():
    trace = record_session(BALANCED_INPUT_LOG)
    assert trace.reflection_beats() == []
    assert trace.first_reflection_beat() is None


def test_cli_locates_the_reflection_beat():
    # The "from logs" contract surfaced at the command line.
    assert main(["--locate-reflection"]) == 0


# --- "a recorded session replays" ----------------------------------------------


def test_trace_round_trips_through_json():
    trace = canonical_trace()
    again = SessionTrace.from_json(trace.to_json())
    assert again == trace
    assert again.state_hash() == trace.state_hash()


def test_recorded_session_replays_identically():
    recorded = canonical_trace()
    # "A recorded session": serialise the log, then reload it.
    reloaded = SessionTrace.from_json(recorded.to_json())
    # Replaying from the reloaded header reproduces the run byte-for-byte.
    replayed = reloaded.replay()
    assert replayed == recorded
    assert replayed.to_json() == recorded.to_json()


@pytest.mark.parametrize("variant", ["adaptive", "fixed", "random"])
def test_replay_reproduces_every_arm(variant):
    recorded = record_session(CANONICAL_INPUT_LOG, variant=variant, seed=7)
    assert recorded.replay() == recorded


def test_replay_rejects_a_mismatched_world():
    trace = replace(canonical_trace(), world_name="some-other-world")
    with pytest.raises(ValueError, match="cannot replay across worlds"):
        trace.replay()


def test_from_json_rejects_an_unknown_schema_version():
    data = canonical_trace().to_dict()
    data["schema_version"] = SCHEMA_VERSION + 1
    import json

    with pytest.raises(ValueError, match="unsupported trace schema version"):
        SessionTrace.from_json(json.dumps(data))


def test_to_json_is_canonical_and_stable_under_reparse():
    import json

    text = canonical_trace().to_json()
    assert text.endswith("\n")
    reparsed = json.loads(text)
    assert json.dumps(reparsed, indent=2, sort_keys=True) + "\n" == text


# --- "identical state hash across N repeated runs of the same seed+inputs" ------


@pytest.mark.parametrize("variant", ["adaptive", "fixed", "random"])
@pytest.mark.parametrize("seed", [0, 1, 42, 9999])
def test_identical_state_hash_across_n_runs(variant, seed):
    hashes = {
        record_session(CANONICAL_INPUT_LOG, seed=seed, variant=variant).state_hash()
        for _ in range(N_RUNS)
    }
    assert len(hashes) == 1, f"state hash drifted across {N_RUNS} identical runs"


def test_repeated_runs_are_byte_identical():
    first = canonical_trace().to_json()
    assert all(canonical_trace().to_json() == first for _ in range(N_RUNS))


def test_state_hash_is_self_describing_and_pure():
    digest = canonical_trace().state_hash()
    assert digest.startswith("sha256:")
    # The bare digest function ignores dict ordering and incidental formatting.
    assert state_hash({"a": 1, "b": 2}) == state_hash({"b": 2, "a": 1})
    assert state_hash({"a": 1}) != state_hash({"a": 2})


def test_placebo_seed_is_load_bearing_in_the_hash():
    # The seeded baseline's content depends on the seed, so its state hash must
    # too — otherwise "seeded" replay would be a vacuous claim.
    a = record_session(CANONICAL_INPUT_LOG, seed=1, variant="random").state_hash()
    b = record_session(CANONICAL_INPUT_LOG, seed=7, variant="random").state_hash()
    assert a != b


def test_adaptive_state_hash_is_seed_invariant():
    # The adaptive arm reads only the player model, so the seed never touches its
    # content; its state hash is identical across seeds.
    hashes = {
        record_session(CANONICAL_INPUT_LOG, seed=seed, variant="adaptive").state_hash()
        for seed in (0, 1, 42, 9999)
    }
    assert len(hashes) == 1


def test_state_hash_is_identical_across_processes_and_hash_seeds():
    # The strongest form of the guardrail: two separate processes, each with a
    # different PYTHONHASHSEED, must emit the same digest for the seeded placebo.
    # This proves the digest (and the placebo's string-seeded RNG behind it) never
    # depends on the interpreter's hash randomisation.
    def emit(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "game.instrumentation",
                "--variant",
                "random",
                "--seed",
                str(DEFAULT_SEED),
                "--state-hash",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    expected = record_session(
        CANONICAL_INPUT_LOG, seed=DEFAULT_SEED, variant="random"
    ).state_hash()
    assert emit("0") == emit("1") == expected


# --- the tracer is pinned to the engine, never a parallel reimplementation ------


def test_consistency_guard_detects_tracer_engine_drift(monkeypatch):
    # Guard the guard: if the trace's adaptation producer ever disagrees with the
    # played engine, recording must fail loudly rather than log a wrong session.
    import game.instrumentation as instrumentation

    original = instrumentation.adapt_slot

    def drifting(slot, mirror, **kwargs):
        good = original(slot, mirror, **kwargs)
        return replace(good, branch_key="__drift__")

    monkeypatch.setattr(instrumentation, "adapt_slot", drifting)
    with pytest.raises(RuntimeError, match="drifted from the engine"):
        record_session(CANONICAL_INPUT_LOG)


# --- CLI -----------------------------------------------------------------------


def test_cli_default_prints_the_canonical_trace(capsys):
    assert main([]) == 0
    assert capsys.readouterr().out == canonical_trace().to_json()


def test_cli_state_hash_matches_the_api(capsys):
    assert main(["--state-hash"]) == 0
    assert capsys.readouterr().out.strip() == canonical_trace().state_hash()


def test_cli_accepts_a_seed_variant_and_input_log(capsys):
    assert (
        main(
            [
                "--variant",
                "random",
                "--seed",
                "7",
                "--input",
                ",".join(CANONICAL_INPUT_LOG),
            ]
        )
        == 0
    )
    expected = record_session(CANONICAL_INPUT_LOG, seed=7, variant="random").to_json()
    assert capsys.readouterr().out == expected


def test_cli_rejects_an_unknown_variant(capsys):
    with pytest.raises(SystemExit):
        main(["--variant", "nonsense"])


# --- the logged loop is a faithful, typed record -------------------------------


def test_loop_trace_to_dict_round_trips():
    loop = canonical_trace().loops[2]  # the loop the beat fires on
    assert LoopTrace.from_dict(loop.to_dict()) == loop
