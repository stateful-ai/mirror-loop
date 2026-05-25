"""The end-to-end sweep: deterministic, complete, and arithmetically sound."""

from __future__ import annotations

import json

import pytest

from game.world import DEFAULT_WORLD
from llmbench.client import LiveClient
from llmbench.harness import (
    DEFAULT_TRIALS,
    SessionProfile,
    measure,
    render_report,
)
from llmbench.models import CANDIDATE_MODELS
from llmbench.prompts import INSERTION_POINTS, InsertionPoint
from llmbench.__main__ import main


def test_report_covers_every_model_and_insertion_point():
    report = measure(trials=20)
    pairs = {(s.model, s.insertion_point) for s in report.call_stats}
    expected = {
        (m.name, p) for m in CANDIDATE_MODELS for p in INSERTION_POINTS
    }
    assert pairs == expected
    assert {c.model for c in report.session_costs} == {m.name for m in CANDIDATE_MODELS}


def test_sweep_is_deterministic_in_seed_and_trials():
    a = measure(trials=20, seed=42).to_dict()
    b = measure(trials=20, seed=42).to_dict()
    assert a == b


def test_seed_changes_latency_but_not_cost():
    a = measure(trials=50, seed=1)
    b = measure(trials=50, seed=2)
    # Cost is a pure function of (real tokens, price) — seed-invariant.
    for model in (m.name for m in CANDIDATE_MODELS):
        assert a.session_cost(model).total_usd == b.session_cost(model).total_usd
    # Latency jitter is seeded, so at least one percentile moves.
    a_lat = [(s.model, s.latency_p50_ms) for s in a.call_stats]
    b_lat = [(s.model, s.latency_p50_ms) for s in b.call_stats]
    assert a_lat != b_lat


def test_p95_is_at_least_p50_everywhere():
    report = measure(trials=DEFAULT_TRIALS)
    for stat in report.call_stats:
        assert stat.latency_p95_ms >= stat.latency_p50_ms


def test_session_cost_is_the_profile_weighted_sum_of_per_call_costs():
    report = measure(trials=20)
    profile = report.session_profile.calls_per_session
    for model in (m.name for m in CANDIDATE_MODELS):
        cost = report.session_cost(model)
        for point in INSERTION_POINTS:
            per_call = report.stat(model, point).cost_per_call_usd
            assert cost.per_point_usd[point] == pytest.approx(
                profile[point] * per_call
            )
        assert cost.total_usd == pytest.approx(sum(cost.per_point_usd.values()))


def test_session_profile_is_grounded_in_the_world():
    profile = SessionProfile.from_world(DEFAULT_WORLD)
    branch_slots = sum(1 for s in DEFAULT_WORLD.slots if s.variants is not None)
    assert profile.calls_per_session[InsertionPoint.NPC_REPLY] == DEFAULT_WORLD.length
    assert profile.calls_per_session[InsertionPoint.BRANCH_CANDIDATE] == branch_slots


def test_the_critical_path_is_the_latency_blocker_not_cost():
    # The decision the harness exists to inform: on the same model, an NPC reply
    # is cheaper than a branch candidate (less output) yet sits on the critical
    # path; the off-path branch candidate costs more but the player never waits.
    report = measure(trials=50)
    for model in (m.name for m in CANDIDATE_MODELS):
        npc = report.stat(model, InsertionPoint.NPC_REPLY)
        branch = report.stat(model, InsertionPoint.BRANCH_CANDIDATE)
        assert npc.on_critical_path and not branch.on_critical_path
        assert npc.cost_per_call_usd < branch.cost_per_call_usd


def test_cost_is_cheap_but_latency_is_not_negligible():
    # Quantifies the go/no-go: even the frontier model is cents per session, while
    # the cheapest model's critical-path p95 is still hundreds of ms.
    report = measure(trials=DEFAULT_TRIALS)
    assert max(c.total_usd for c in report.session_costs) < 1.0  # sub-dollar
    cheapest_npc = report.stat(CANDIDATE_MODELS[0].name, InsertionPoint.NPC_REPLY)
    assert cheapest_npc.latency_p95_ms > 500  # a player-perceptible hot-path cost


def test_trials_must_be_positive():
    with pytest.raises(ValueError):
        measure(trials=0)


def test_render_report_is_markdown_with_every_model():
    text = render_report(measure(trials=10))
    assert text.startswith("# LLM cost/latency")
    for model in CANDIDATE_MODELS:
        assert model.name in text
    assert "Per-session cost" in text


def test_offline_report_is_labelled_modeled_and_avoids_false_precision():
    report = measure(trials=10)
    assert report.latency_kind == "modeled"
    assert report.to_dict()["run"]["latency_kind"] == "modeled"
    text = render_report(report)
    # The latency columns must say "modeled", and modeled values are coarse (~N.N s),
    # never quoted to the millisecond as if observed.
    assert "p50 latency (modeled)" in text
    assert "latency is modeled" in text
    latency_table = text.split("## Per-session cost")[0]
    assert " ms |" not in latency_table  # no millisecond figures for modeled latency


def test_measure_propagates_a_clients_measured_latency_kind():
    # A live/measured client (here with an injected transport + clock so no network
    # is touched) makes the whole report — and its rendering — report "measured".
    def transport(url, payload, headers):
        return {"usage": {"input_tokens": 100, "output_tokens": 50}}

    client = LiveClient(api_key="k", transport=transport, clock=lambda: 0.0)
    report = measure(trials=3, client=client)
    assert report.latency_kind == "measured"
    text = render_report(report)
    assert "p95 latency (measured)" in text
    assert "latency is measured" in text


def test_report_to_dict_is_json_serialisable():
    data = measure(trials=10).to_dict()
    again = json.loads(json.dumps(data))
    assert again["run"]["seed"] == 42
    assert len(again["call_stats"]) == len(CANDIDATE_MODELS) * len(INSERTION_POINTS)


def test_cli_markdown_and_json(capsys):
    assert main(["--trials", "5"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# LLM cost/latency")

    assert main(["--trials", "5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
