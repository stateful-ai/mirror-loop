"""Tests for the experience-change observables and pre-registered rule.

These pin four properties of ``acceptance.experience_change``:

1. **Sufficiency.** Every observable in ``LoopPresentation`` is a direct read
   of a field the existing replay log (``game.session.LoopRecord``) already
   carries — no new instrumentation, no engine replay. The same values
   round-trip through the projection JSON shape.
2. **Predicates are right.** ``framing_diverged`` / ``order_diverged`` /
   ``presentation_diverged`` / ``behavior_diverged`` answer the booleans they
   are documented to answer, and reject mis-paired loops.
3. **Discrimination.** The canonical conservative-null population (the same
   one that produced the prior playtest's INCONCLUSIVE verdict on the locked
   prediction metric) clears the presentation floor and fails the behavior
   floor under this rule — exactly the diagnosis ``docs/PLAYTEST_RESULTS.md``
   §3 names. A nudgeable population clears both and reaches PASS.
4. **Locked knobs.** The pre-registered floors match the values in
   ``docs/ACCEPTANCE_OBSERVABLES.md`` §3 (drift guard).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from acceptance.experience_change import (
    BEHAVIORAL_DIVERGENCE_FLOOR,
    MIN_PAIRED_LOOPS,
    MIN_PAIRED_SESSIONS,
    PRESENTATION_DIVERGENCE_FLOOR,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    LoopPresentation,
    PairObservables,
    behavior_diverged,
    decide,
    evaluate_paired_sessions,
    framing_diverged,
    load_pair_log,
    order_diverged,
    pair_observables,
    presentation_diverged,
    session_observables_log,
    session_presentations,
    write_pair_log,
)
from game.playtest import (
    BASE_SEED,
    N_PER_ARM,
    build_population,
    run_arm,
)
from game.session import play_session
from game.variants import ADAPTIVE, FIXED


# --- helpers ------------------------------------------------------------------


def _lp(
    *,
    loop_index: int = 0,
    scene_id: str = "intake",
    branch_key: str = "default",
    offered_order: tuple[str, ...] = ("a", "b", "c"),
    actual_action: str = "a",
) -> LoopPresentation:
    return LoopPresentation(
        loop_index=loop_index,
        scene_id=scene_id,
        branch_key=branch_key,
        offered_order=offered_order,
        actual_action=actual_action,
    )


def _pair(**kwargs) -> PairObservables:
    defaults = {
        "player_id": "p000",
        "n_paired_loops": MIN_PAIRED_LOOPS,
        "framing_divergence_rate": 0.0,
        "order_divergence_rate": 0.0,
        "presentation_divergence_rate": 0.0,
        "behavior_divergence_rate": 0.0,
    }
    defaults.update(kwargs)
    return PairObservables(**defaults)


# --- sufficiency: the observables come straight from the existing log --------


def test_loop_presentation_reads_record_fields_directly():
    # A real session through the engine; the observables must come straight off
    # LoopRecord with no extra computation. (If the assertions below ever need
    # something the log does not already carry, that is new instrumentation.)
    player = build_population(3, base_seed=BASE_SEED)[0]
    session = play_session(player.policy(), variant=ADAPTIVE)
    record = session.records[0]
    p = LoopPresentation.from_record(record)

    assert p.loop_index == record.loop_index
    assert p.scene_id == record.offered.id
    assert p.branch_key == record.branch_key
    assert p.offered_order == tuple(c.id for c in record.offered.choices)
    assert p.actual_action == record.result.actual_action


def test_session_presentations_is_one_loop_record_in_order():
    player = build_population(3, base_seed=BASE_SEED)[0]
    session = play_session(player.policy(), variant=ADAPTIVE)
    ps = session_presentations(session)
    assert len(ps) == len(session.records)
    assert [p.loop_index for p in ps] == list(range(len(session.records)))


def test_presentation_round_trips_through_json():
    p = _lp(
        loop_index=2,
        scene_id="records:control",
        branch_key="control",
        offered_order=("c_control", "c_kind", "c_defy"),
        actual_action="c_control",
    )
    assert LoopPresentation.from_dict(p.to_dict()) == p


def test_session_observables_log_uses_only_existing_fields(tmp_path):
    # The serialized projection is structurally a subset of the in-memory log:
    # round-tripping it back to LoopPresentations recovers exactly what
    # session_presentations would produce from the live session.
    player = build_population(3, base_seed=BASE_SEED)[0]
    adaptive = play_session(player.policy(), variant=ADAPTIVE)
    baseline = play_session(player.policy(), variant=FIXED)

    path = tmp_path / "pair.json"
    write_pair_log(path, player_id="p000", adaptive=adaptive, baseline=baseline)

    player_id, adaptive_loops, baseline_loops = load_pair_log(path)
    assert player_id == "p000"
    assert tuple(adaptive_loops) == session_presentations(adaptive)
    assert tuple(baseline_loops) == session_presentations(baseline)


def test_session_observables_log_shape_is_explicit():
    # Pins the projection shape so a downstream consumer's contract is stable.
    player = build_population(3, base_seed=BASE_SEED)[0]
    session = play_session(player.policy(), variant=ADAPTIVE)
    payload = session_observables_log(session, player_id="p000", arm="adaptive")
    assert set(payload) == {"player_id", "arm", "variant", "world", "loops"}
    assert payload["arm"] == "adaptive"
    assert payload["variant"] == ADAPTIVE.name
    assert payload["loops"], "every session must project at least one loop"
    loop0 = payload["loops"][0]
    assert set(loop0) == {
        "loop_index",
        "scene_id",
        "branch_key",
        "offered_order",
        "actual_action",
    }


# --- per-loop divergence predicates -------------------------------------------


def test_framing_diverged_compares_branch_keys():
    a = _lp(branch_key="kindness")
    b = _lp(branch_key="default")
    assert framing_diverged(a, b) is True
    assert framing_diverged(a, replace(a, branch_key="kindness")) is False


def test_order_diverged_compares_offered_order():
    a = _lp(offered_order=("x", "y", "z"))
    b = _lp(offered_order=("y", "x", "z"))
    assert order_diverged(a, b) is True
    assert order_diverged(a, a) is False


def test_presentation_diverged_is_union_of_framing_or_order():
    a = _lp(branch_key="kindness", offered_order=("x", "y", "z"))
    # neither -> False
    assert presentation_diverged(a, a) is False
    # framing only
    framing_only = replace(a, branch_key="default")
    assert presentation_diverged(a, framing_only) is True
    # order only
    order_only = replace(a, offered_order=("y", "x", "z"))
    assert presentation_diverged(a, order_only) is True


def test_behavior_diverged_compares_actual_actions():
    a = _lp(actual_action="x")
    b = _lp(actual_action="y")
    assert behavior_diverged(a, b) is True
    assert behavior_diverged(a, a) is False


def test_predicates_require_matching_loop_indices():
    a = _lp(loop_index=0)
    b = _lp(loop_index=1)
    with pytest.raises(ValueError, match="loop_index"):
        framing_diverged(a, b)
    with pytest.raises(ValueError, match="loop_index"):
        order_diverged(a, b)
    with pytest.raises(ValueError, match="loop_index"):
        behavior_diverged(a, b)


# --- pair_observables ---------------------------------------------------------


def test_pair_observables_rejects_uneven_pairs():
    with pytest.raises(ValueError, match="same number of loops"):
        pair_observables([_lp()], [_lp(), _lp(loop_index=1)], player_id="p0")


def test_pair_observables_empty_returns_zero_rates_and_unscorable():
    obs = pair_observables([], [], player_id="p0")
    assert obs.n_paired_loops == 0
    assert obs.presentation_divergence_rate == 0.0
    assert obs.behavior_divergence_rate == 0.0
    assert obs.scorable is False


def test_pair_observables_aggregates_rates_correctly():
    adaptive = [
        _lp(loop_index=0, branch_key="kindness", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=1, branch_key="kindness", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=2, branch_key="default",  offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=3, branch_key="default",  offered_order=("b", "a"), actual_action="b"),
        _lp(loop_index=4, branch_key="default",  offered_order=("a", "b"), actual_action="a"),
    ]
    baseline = [
        _lp(loop_index=0, branch_key="default", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=1, branch_key="default", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=2, branch_key="default", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=3, branch_key="default", offered_order=("a", "b"), actual_action="a"),
        _lp(loop_index=4, branch_key="default", offered_order=("a", "b"), actual_action="a"),
    ]
    obs = pair_observables(adaptive, baseline, player_id="p0")
    # framing diverges on loops 0,1 -> 2/5
    assert obs.framing_divergence_rate == pytest.approx(2 / 5)
    # order diverges on loop 3 -> 1/5
    assert obs.order_divergence_rate == pytest.approx(1 / 5)
    # presentation diverges on 0,1,3 -> 3/5
    assert obs.presentation_divergence_rate == pytest.approx(3 / 5)
    # behavior diverges on loop 3 only -> 1/5
    assert obs.behavior_divergence_rate == pytest.approx(1 / 5)
    assert obs.scorable is True


# --- decision rule -----------------------------------------------------------


def test_decide_inconclusive_when_too_few_pairs():
    pairs = [_pair() for _ in range(MIN_PAIRED_SESSIONS - 1)]
    result = decide(pairs)
    assert result.verdict == VERDICT_INCONCLUSIVE
    assert "insufficient paired sessions" in result.reason
    assert result.n_pairs == MIN_PAIRED_SESSIONS - 1


def test_decide_skips_unscorable_pairs():
    # Pair with too few loops is dropped from the population count even if
    # numerically present.
    bad = _pair(n_paired_loops=MIN_PAIRED_LOOPS - 1)
    good = _pair(presentation_divergence_rate=0.5, behavior_divergence_rate=0.5)
    pairs = [bad] + [good] * (MIN_PAIRED_SESSIONS - 1)
    result = decide(pairs)
    # only MIN_PAIRED_SESSIONS - 1 scorable -> INCONCLUSIVE on size, not on rates.
    assert result.verdict == VERDICT_INCONCLUSIVE
    assert result.n_pairs == MIN_PAIRED_SESSIONS - 1


def test_decide_fail_below_presentation_floor():
    pairs = [
        _pair(
            presentation_divergence_rate=PRESENTATION_DIVERGENCE_FLOOR - 0.05,
            behavior_divergence_rate=0.5,
        )
        for _ in range(MIN_PAIRED_SESSIONS)
    ]
    result = decide(pairs)
    assert result.verdict == VERDICT_FAIL
    assert "no visible difference" in result.reason


def test_decide_fail_below_behavior_floor_when_presentation_clears():
    # Exactly the conservative-null story: presentation clearly diverges, but
    # the player chose the same in both arms.
    pairs = [
        _pair(
            presentation_divergence_rate=0.6,
            behavior_divergence_rate=0.0,
        )
        for _ in range(MIN_PAIRED_SESSIONS)
    ]
    result = decide(pairs)
    assert result.verdict == VERDICT_FAIL
    assert "conservative-null" in result.reason


def test_decide_pass_when_both_floors_clear():
    pairs = [
        _pair(
            presentation_divergence_rate=PRESENTATION_DIVERGENCE_FLOOR + 0.05,
            behavior_divergence_rate=BEHAVIORAL_DIVERGENCE_FLOOR + 0.05,
        )
        for _ in range(MIN_PAIRED_SESSIONS)
    ]
    result = decide(pairs)
    assert result.verdict == VERDICT_PASS
    assert "responded" in result.reason


def test_decide_floors_are_strict_lower_bounds_at_boundary():
    # Exactly at the floors should PASS (>=, not >).
    pairs = [
        _pair(
            presentation_divergence_rate=PRESENTATION_DIVERGENCE_FLOOR,
            behavior_divergence_rate=BEHAVIORAL_DIVERGENCE_FLOOR,
        )
        for _ in range(MIN_PAIRED_SESSIONS)
    ]
    result = decide(pairs)
    assert result.verdict == VERDICT_PASS


# --- discrimination on real paired sessions -----------------------------------


def test_canonical_null_population_diagnoses_presentation_without_behavior():
    """The same canonical null population that pinned the prediction-metric A/B
    to INCONCLUSIVE: under this rule it must clear presentation and fail
    behavior — diagnosing exactly the structural pin
    ``docs/PLAYTEST_RESULTS.md`` §3 names."""
    pop = build_population(N_PER_ARM, base_seed=BASE_SEED)
    adaptive_sessions = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline_sessions = run_arm("fixed", pop, seed=BASE_SEED)

    triples = list(zip([p.player_id for p in pop], adaptive_sessions, baseline_sessions))
    result = evaluate_paired_sessions(triples)

    # Presentation divergence must be non-trivial: leaning players hit the
    # adaptation seam, so the arms genuinely differ in what was shown.
    assert result.mean_presentation_divergence >= PRESENTATION_DIVERGENCE_FLOOR
    # Behavior divergence must be exactly zero under the conservative null:
    # the player chooses by tendency, not by presentation.
    assert result.mean_behavior_divergence == 0.0
    assert result.verdict == VERDICT_FAIL
    assert "conservative-null" in result.reason


def test_nudgeable_population_passes_both_floors():
    """A nudgeable population (predictive-nudging hypothesis,
    ``docs/game_design.md`` §4.6) clears both floors through real paired
    sessions, so the rule reaches PASS — confirming the rule discriminates and
    is not structurally pinned to FAIL."""
    pop = build_population(N_PER_ARM, base_seed=BASE_SEED, suggestibility=0.8)
    adaptive_sessions = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline_sessions = run_arm("fixed", pop, seed=BASE_SEED)

    triples = list(zip([p.player_id for p in pop], adaptive_sessions, baseline_sessions))
    result = evaluate_paired_sessions(triples)

    assert result.mean_presentation_divergence >= PRESENTATION_DIVERGENCE_FLOOR
    assert result.mean_behavior_divergence >= BEHAVIORAL_DIVERGENCE_FLOOR
    assert result.verdict == VERDICT_PASS


def test_evaluate_paired_sessions_is_deterministic():
    pop = build_population(MIN_PAIRED_SESSIONS, base_seed=BASE_SEED)
    adaptive_sessions = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline_sessions = run_arm("fixed", pop, seed=BASE_SEED)
    triples = list(zip([p.player_id for p in pop], adaptive_sessions, baseline_sessions))
    assert evaluate_paired_sessions(triples).to_dict() == evaluate_paired_sessions(triples).to_dict()


# --- locked knobs (drift guard against the doc) -------------------------------


def test_pre_registered_floors_match_the_doc():
    # These are the numbers ``docs/ACCEPTANCE_OBSERVABLES.md`` §3 cites. If you
    # need to move them, that is an amend per §6 of that doc — update both.
    assert PRESENTATION_DIVERGENCE_FLOOR == 0.20
    assert BEHAVIORAL_DIVERGENCE_FLOOR == 0.05
    assert MIN_PAIRED_LOOPS == 5
    assert MIN_PAIRED_SESSIONS == 30


def test_result_render_includes_verdict_and_means():
    pairs = [
        _pair(
            presentation_divergence_rate=0.4,
            behavior_divergence_rate=0.1,
        )
        for _ in range(MIN_PAIRED_SESSIONS)
    ]
    rendered = decide(pairs).render()
    assert "PASS" in rendered
    assert "0.400" in rendered  # the presentation mean
    assert "0.100" in rendered  # the behavior mean


def test_result_to_dict_is_json_serializable():
    pairs = [_pair(presentation_divergence_rate=0.3, behavior_divergence_rate=0.1)
             for _ in range(MIN_PAIRED_SESSIONS)]
    payload = decide(pairs).to_dict()
    # Should round-trip through json.dumps without raising.
    json.dumps(payload)
    assert payload["verdict"] in (VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE)
    assert payload["floors"]["presentation_divergence"] == PRESENTATION_DIVERGENCE_FLOOR
    assert payload["floors"]["behavior_divergence"] == BEHAVIORAL_DIVERGENCE_FLOOR


# --- CLI: one-command end-to-end demonstration --------------------------------


def test_cli_canonical_run_fails_on_behavior_floor(capsys):
    from acceptance.experience_change import main

    exit_code = main([])
    out = capsys.readouterr().out
    # The canonical conservative-null population: presentation clears, behavior
    # pinned to zero -> FAIL by the behavior floor. Exit code 1 by the mapping.
    assert exit_code == 1
    assert VERDICT_FAIL in out
    assert "conservative-null" in out


def test_cli_nudgeable_population_passes(capsys):
    from acceptance.experience_change import main

    exit_code = main(["--suggestibility", "0.8"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert VERDICT_PASS in out


def test_cli_inconclusive_exit_code_is_3(capsys):
    from acceptance.experience_change import main

    # n below MIN_PAIRED_SESSIONS -> INCONCLUSIVE by the size rule.
    exit_code = main(["--n", str(MIN_PAIRED_SESSIONS - 1)])
    out = capsys.readouterr().out
    assert exit_code == 3
    assert VERDICT_INCONCLUSIVE in out


def test_cli_json_output_is_parsable(capsys):
    from acceptance.experience_change import main

    main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] in (VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE)
    assert payload["floors"]["presentation_divergence"] == PRESENTATION_DIVERGENCE_FLOOR


def test_cli_from_logs_path_scores_without_running_engine(tmp_path, capsys):
    # Write a population of paired logs through the existing engine, then re-
    # score them from disk: the rule must compute end-to-end from the
    # serialized projection alone (the no-re-instrumentation contract from
    # disk).
    from acceptance.experience_change import main
    from game.playtest import build_population

    pop = build_population(MIN_PAIRED_SESSIONS, base_seed=BASE_SEED, suggestibility=0.8)
    log_paths = []
    for player in pop:
        adaptive = play_session(player.policy(), variant=ADAPTIVE)
        baseline = play_session(player.policy(), variant=FIXED)
        path = tmp_path / f"{player.player_id}.json"
        write_pair_log(path, player_id=player.player_id, adaptive=adaptive, baseline=baseline)
        log_paths.append(str(path))

    exit_code = main(["--from-logs", *log_paths, "--json"])
    payload = json.loads(capsys.readouterr().out)
    # Nudgeable population through disk -> PASS, same as via the engine.
    assert exit_code == 0
    assert payload["verdict"] == VERDICT_PASS
    assert payload["n_pairs"] == MIN_PAIRED_SESSIONS
