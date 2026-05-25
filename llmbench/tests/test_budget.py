"""The critical-path floor is model-independent and load-bearing.

These tests pin the property that makes the go/no-go robust: the NO-GO follows
from the output budget and a UX threshold, *not* from the modeled latency
overhead constants. The required throughput is pure arithmetic, and the per-model
decode floor depends only on decode rate — so a report can rest the headline
decision on it whether or not a live spike has run.
"""

from __future__ import annotations

import json

import pytest

from llmbench.budget import (
    INSTANT_BUDGET_MS,
    STALL_BUDGET_MS,
    CriticalPathFloor,
    render_floor,
    required_decode_tps,
)
from llmbench.models import CANDIDATE_MODELS, ModelSpec
from llmbench.prompts import INSERTION_POINTS


def test_required_tps_is_pure_arithmetic_of_budget_and_tokens():
    # 64 tokens in 100 ms -> 640 tok/s; in 1000 ms -> 64 tok/s. No model involved.
    assert required_decode_tps(64, 100.0) == pytest.approx(640.0)
    assert required_decode_tps(64, 1000.0) == pytest.approx(64.0)


def test_required_tps_rejects_degenerate_inputs():
    with pytest.raises(ValueError):
        required_decode_tps(-1, 100.0)
    with pytest.raises(ValueError):
        required_decode_tps(64, 0.0)


def test_floor_output_budget_tracks_the_critical_path_insertion_point():
    floor = CriticalPathFloor.for_models()
    expected = max(
        spec.expected_output_tokens
        for spec in INSERTION_POINTS.values()
        if spec.on_critical_path
    )
    assert floor.output_tokens == expected


def test_no_candidate_feels_instant_on_the_hot_path():
    floor = CriticalPathFloor.for_models()
    # Every candidate's decode-only floor (the most generous possible case)
    # already blows the instant budget — that is the NO-GO, derived not asserted.
    assert all(not m.fits_instant_budget for m in floor.per_model)
    assert all(m.over_instant_budget > 1.0 for m in floor.per_model)


def test_floor_ignores_overhead_constants_entirely():
    # Two specs with identical decode throughput but wildly different base overhead,
    # prefill, and jitter must yield the same decode-only floor: the floor depends
    # on decode rate alone, so it cannot be moved by the constants a live spike pins.
    common = dict(
        tier="fast",
        input_usd_per_mtok=1.0,
        output_usd_per_mtok=5.0,
        latency_per_input_token_ms=0.03,
        latency_per_output_token_ms=10.0,  # 100 tok/s
        context_window=200_000,
    )
    lean = ModelSpec(name="m", latency_base_ms=0.0, latency_sigma=0.0, **common)
    heavy = ModelSpec(name="m", latency_base_ms=9_999.0, latency_sigma=2.0, **common)
    lean_floor = CriticalPathFloor.for_models((lean,)).per_model[0]
    heavy_floor = CriticalPathFloor.for_models((heavy,)).per_model[0]
    assert lean_floor.decode_floor_ms == heavy_floor.decode_floor_ms


def test_decode_floor_is_tokens_over_throughput():
    floor = CriticalPathFloor.for_models()
    for model, mf in zip(CANDIDATE_MODELS, floor.per_model):
        assert mf.decode_floor_ms == pytest.approx(
            model.latency_per_output_token_ms * floor.output_tokens
        )
        assert mf.over_instant_budget == pytest.approx(
            mf.decode_floor_ms / INSTANT_BUDGET_MS
        )


def test_budgets_are_the_standard_thresholds():
    floor = CriticalPathFloor.for_models()
    assert floor.instant_budget_ms == INSTANT_BUDGET_MS == 100.0
    assert floor.stall_budget_ms == STALL_BUDGET_MS == 1000.0


def test_floor_to_dict_is_json_serialisable():
    data = CriticalPathFloor.for_models().to_dict()
    again = json.loads(json.dumps(data))
    assert again["output_tokens"] == data["output_tokens"]
    assert len(again["per_model"]) == len(CANDIDATE_MODELS)


def test_render_floor_states_the_required_throughput_and_multiple():
    text = "\n".join(render_floor(CriticalPathFloor.for_models()))
    assert "Critical-path floor (model-independent)" in text
    assert "640 tok/s" in text  # the instant-budget requirement for 64 tokens
    assert "decode-only floor" in text


def test_render_floor_single_model_does_not_print_a_degenerate_range():
    # With one model the "best–worst×" range collapses to a single factor.
    single = CriticalPathFloor.for_models((CANDIDATE_MODELS[-1],))
    text = "\n".join(render_floor(single))
    assert "21–21×" not in text
    assert "21× faster" in text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
