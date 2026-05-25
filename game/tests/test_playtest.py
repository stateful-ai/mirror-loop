"""Tests for the blind A/B playtest harness (``game.playtest``).

These pin the three things that make the playtest trustworthy:

1. **It is honest about parity.** Under the conservative-null population the
   adaptive and baseline arms produce *identical* decision points, so the locked
   metric scores them identically — the central finding of the canonical run.
2. **The decision rule discriminates.** Synthetic arm pairs exercise every branch
   (PASS / FAIL / INCONCLUSIVE), and a *nudgeable* population reaches PASS through
   real sessions — so the canonical INCONCLUSIVE is a true reading, not a rule
   that can only ever say one thing.
3. **It is deterministic and pre-registered.** Same seed → same verdict; the
   locked knobs match the method doc and the metric is imported, not re-declared.
"""

from __future__ import annotations

import json

import pytest

from acceptance.predictability import (
    MIN_DECISION_POINTS,
    MIN_MARGIN_OVER_BASELINE,
    MIN_TOP1_ACCURACY,
)

from game.playtest import (
    BASE_SEED,
    EFFECT_THRESHOLD,
    LEAN_MAX,
    LEAN_MIN,
    N_PER_ARM,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    ABResult,
    ArmResult,
    SimulatedPlayer,
    build_population,
    decide,
    main,
    run_arm,
    run_playtest,
    score_arm,
)
from game.world import TENDENCY_PRIORITY


# --- helpers ------------------------------------------------------------------


def _arm(
    top1: float,
    margin: float,
    *,
    n: int = N_PER_ARM,
    points: int | None = None,
    name: str = "adaptive",
    variant: str = "adaptive",
) -> ArmResult:
    """A synthetic arm result with controllable aggregates (for ``decide`` tests)."""
    return ArmResult(
        arm=name,
        variant_name=variant,
        n_sessions=n,
        mean_top1=top1,
        mean_margin=margin,
        mean_baseline=0.2,
        pass_rate=1.0,
        total_decision_points=points if points is not None else n * 5,
        per_session=(),
    )


# --- population ---------------------------------------------------------------


def test_population_is_sized_balanced_and_default_null():
    pop = build_population(30, base_seed=BASE_SEED)
    assert len(pop) == 30
    # Balanced across the three tendencies (30 / 3 each).
    counts = {t: sum(p.primary == t for p in pop) for t in TENDENCY_PRIORITY}
    assert counts == {"kindness": 10, "control": 10, "defiance": 10}
    # Lean is swept across the declared band, endpoints included.
    leans = [p.lean for p in pop]
    assert min(leans) == pytest.approx(LEAN_MIN)
    assert max(leans) == pytest.approx(LEAN_MAX)
    # Canonical population is the conservative null.
    assert all(p.suggestibility == 0.0 for p in pop)


def test_population_is_deterministic():
    assert build_population(12, base_seed=7) == build_population(12, base_seed=7)
    assert build_population(12, base_seed=7) != build_population(12, base_seed=8)


def test_population_rejects_empty():
    with pytest.raises(ValueError, match="population size"):
        build_population(0)


# --- arm parity: the central finding ------------------------------------------


def test_null_arms_produce_identical_decision_points():
    # The conservative-null player ignores presentation, and prediction is a
    # render present in both arms — so adaptive and the fixed baseline yield
    # byte-identical decision points for every player. This is why the metric
    # cannot separate the arms.
    pop = build_population(9, base_seed=BASE_SEED)
    adaptive = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline = run_arm("fixed", pop, seed=BASE_SEED)
    for a, b in zip(adaptive, baseline):
        assert a.decision_points() == b.decision_points()


def test_null_arms_still_offer_different_content():
    # Parity is on the *scored* decision points only — the arms genuinely differ
    # in what the player is shown (so it is a real A/B, not a no-op toggle).
    pop = build_population(6, base_seed=BASE_SEED)
    adaptive = run_arm("adaptive", pop, seed=BASE_SEED)
    baseline = run_arm("fixed", pop, seed=BASE_SEED)
    adaptive_prompts = [[r.offered.prompt for r in s.records] for s in adaptive]
    baseline_prompts = [[r.offered.prompt for r in s.records] for s in baseline]
    assert adaptive_prompts != baseline_prompts


# --- canonical run ------------------------------------------------------------


def test_canonical_run_is_inconclusive_with_identical_arms():
    res = run_playtest()
    assert res.verdict == VERDICT_INCONCLUSIVE
    assert res.adaptive.n_sessions == N_PER_ARM
    assert res.baseline.n_sessions == N_PER_ARM
    assert res.adaptive.total_decision_points == N_PER_ARM * 5
    # Arms coincide exactly on the locked metric.
    assert res.delta_top1 == 0.0
    assert res.delta_margin == 0.0
    assert res.arms_separated is False
    assert res.adaptive.mean_top1 == res.baseline.mean_top1
    # ...and the (shared) mean sits below the locked floor for this population,
    # which is why the verdict is not a PASS.
    assert res.adaptive.mean_top1 < MIN_TOP1_ACCURACY
    assert not res.adaptive.gate_pass
    assert "do not separate" in res.reason


def test_canonical_run_is_deterministic():
    assert run_playtest().to_dict() == run_playtest().to_dict()


def test_run_playtest_enforces_the_locked_minimum():
    # Fewer than N_PER_ARM collected -> INCONCLUSIVE by rule, regardless of run.
    res = run_playtest(n_per_arm=4)
    assert res.verdict == VERDICT_INCONCLUSIVE
    assert "insufficient sessions" in res.reason


def test_run_playtest_rejects_unknown_baseline():
    with pytest.raises(ValueError, match="baseline must be one of"):
        run_playtest(baseline_variant="adaptive")


# --- the harness is not blind to an effect ------------------------------------


def test_nudgeable_population_separates_and_passes():
    # When players are suggestible (the predictive-nudging hypothesis), the
    # adaptive arm's "predicted choice first" actually pulls choices toward the
    # prediction, so it separates from the player-independent baseline and the
    # rule reaches PASS through real sessions.
    pop = build_population(N_PER_ARM, base_seed=BASE_SEED, suggestibility=0.8)
    adaptive = score_arm("adaptive", "adaptive", run_arm("adaptive", pop, seed=BASE_SEED))
    baseline = score_arm("baseline", "fixed", run_arm("fixed", pop, seed=BASE_SEED))
    delta = adaptive.mean_top1 - baseline.mean_top1
    assert delta >= EFFECT_THRESHOLD
    assert adaptive.gate_pass
    assert decide(adaptive, baseline)[0] == VERDICT_PASS


def test_suggestibility_zero_leaves_the_null_stream_unperturbed():
    # The ``> 0`` short-circuit means a null player's choices are exactly those of
    # an explicit suggestibility-0 player: adding the knob did not move canon.
    base = SimulatedPlayer("p", "kindness", 0.7, BASE_SEED)
    explicit = SimulatedPlayer("p", "kindness", 0.7, BASE_SEED, suggestibility=0.0)
    from game.session import play_session
    from game.variants import ADAPTIVE

    a = play_session(base.policy(), variant=ADAPTIVE).decision_points()
    b = play_session(explicit.policy(), variant=ADAPTIVE).decision_points()
    assert a == b


# --- score_arm ----------------------------------------------------------------


def test_score_arm_empty_is_zeroed():
    res = score_arm("adaptive", "adaptive", [])
    assert res.n_sessions == 0
    assert res.mean_top1 == 0.0
    assert not res.gate_pass


def test_score_arm_aggregates_and_gate_uses_locked_thresholds():
    pop = build_population(6, base_seed=BASE_SEED)
    res = score_arm("adaptive", "adaptive", run_arm("adaptive", pop, seed=BASE_SEED))
    assert res.n_sessions == 6
    assert res.total_decision_points == 30
    assert 0.0 <= res.mean_top1 <= 1.0
    # gate_pass is exactly the locked thresholds applied to the means.
    assert res.gate_pass == (
        res.mean_top1 >= MIN_TOP1_ACCURACY and res.mean_margin >= MIN_MARGIN_OVER_BASELINE
    )


# --- decision rule: every branch ----------------------------------------------


def test_decide_inconclusive_on_insufficient_sessions():
    verdict, reason = decide(_arm(0.9, 0.5, n=10), _arm(0.5, 0.3, n=10))
    assert verdict == VERDICT_INCONCLUSIVE
    assert "insufficient sessions" in reason


def test_decide_inconclusive_on_too_few_points():
    verdict, reason = decide(
        _arm(0.9, 0.5, points=MIN_DECISION_POINTS - 1),
        _arm(0.9, 0.5, points=MIN_DECISION_POINTS - 1),
    )
    assert verdict == VERDICT_INCONCLUSIVE
    assert "too few" in reason


def test_decide_fail_when_adaptation_is_counterproductive():
    # adaptive worse than baseline by >= effect threshold -> kill-criterion.
    verdict, reason = decide(_arm(0.50, 0.3), _arm(0.60, 0.4))
    assert verdict == VERDICT_FAIL
    assert "counterproductive" in reason


def test_decide_pass_when_separated_up_and_gate_clears():
    verdict, reason = decide(_arm(0.75, 0.50), _arm(0.65, 0.40))
    assert verdict == VERDICT_PASS
    assert "adds real" in reason


def test_decide_inconclusive_when_separated_up_but_below_floor():
    # Effect is real (+0.10) but the adaptive arm is still under the locked floor.
    verdict, reason = decide(_arm(0.55, 0.40), _arm(0.45, 0.30))
    assert verdict == VERDICT_INCONCLUSIVE
    assert "below the locked floor" in reason


def test_decide_inconclusive_when_arms_do_not_separate_gate_pass():
    verdict, reason = decide(_arm(0.70, 0.50), _arm(0.69, 0.50))
    assert verdict == VERDICT_INCONCLUSIVE
    assert "do not separate" in reason
    assert "gate PASS" in reason


def test_decide_inconclusive_when_arms_do_not_separate_gate_fail():
    verdict, reason = decide(_arm(0.57, 0.37), _arm(0.57, 0.37))
    assert verdict == VERDICT_INCONCLUSIVE
    assert "do not separate" in reason
    assert "gate FAIL" in reason


def test_decide_required_min_override():
    # A smaller required minimum lets a small run be judged on its merits.
    verdict, _ = decide(_arm(0.75, 0.5, n=6), _arm(0.65, 0.4, n=6), required_min=5)
    assert verdict == VERDICT_PASS


# --- locked knobs: guard against drift from the method doc ---------------------


def test_locked_knobs_match_the_method_doc():
    assert N_PER_ARM == 30
    assert EFFECT_THRESHOLD == 0.05
    assert (LEAN_MIN, LEAN_MAX) == (0.50, 1.00)
    # The per-session metric is the founder-locked gate, imported (not redefined).
    assert (MIN_TOP1_ACCURACY, MIN_MARGIN_OVER_BASELINE, MIN_DECISION_POINTS) == (
        0.60,
        0.15,
        5,
    )


# --- ABResult rendering / serialization ---------------------------------------


def test_abresult_render_and_to_dict_are_consistent():
    res = run_playtest()
    text = res.render()
    assert res.verdict in text
    assert "adaptive" in text and "baseline" in text
    d = res.to_dict()
    assert d["verdict"] == res.verdict
    assert d["contrast"]["delta_top1"] == res.delta_top1
    assert d["adaptive"]["n_sessions"] == res.adaptive.n_sessions
    assert d["method"]["min_top1_accuracy"] == MIN_TOP1_ACCURACY


# --- CLI ----------------------------------------------------------------------


def test_cli_canonical_returns_inconclusive_exit_code(capsys):
    code = main(["--seed", str(BASE_SEED)])
    assert code == 3
    out = capsys.readouterr().out
    assert "INCONCLUSIVE" in out
    assert "Δ mean top-1 = +0.000" in out


def test_cli_json_is_valid_and_self_consistent(capsys):
    code = main(["--seed", str(BASE_SEED), "--json"])
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "INCONCLUSIVE"
    assert payload["method"]["n_per_arm"] == N_PER_ARM
    assert payload["contrast"]["arms_separated"] is False


def test_cli_insufficient_n_is_inconclusive(capsys):
    code = main(["--n", "4"])
    assert code == 3
    assert "insufficient sessions" in capsys.readouterr().out


def test_cli_random_baseline_runs(capsys):
    code = main(["--baseline", "random", "--seed", str(BASE_SEED)])
    assert code == 3
    assert "baseline (random)" in capsys.readouterr().out
