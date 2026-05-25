"""The candidate model specs: pricing arithmetic and profile sanity."""

from __future__ import annotations

import pytest

from llmbench.models import CANDIDATE_MODELS, HAIKU, OPUS, SONNET, ModelSpec, get_model


def test_cost_is_exact_token_arithmetic():
    # 1M input @ $1 + 1M output @ $5 = $6 exactly.
    assert HAIKU.cost_usd(1_000_000, 1_000_000) == pytest.approx(6.0)
    # Zero tokens cost zero; cost is linear in each axis.
    assert HAIKU.cost_usd(0, 0) == 0.0
    assert HAIKU.cost_usd(2000, 0) == pytest.approx(2 * HAIKU.cost_usd(1000, 0))


def test_cost_is_monotonic_in_tokens():
    cheap = HAIKU.cost_usd(100, 100)
    more_in = HAIKU.cost_usd(200, 100)
    more_out = HAIKU.cost_usd(100, 200)
    assert more_in > cheap
    assert more_out > cheap
    # Output is dearer than input for every candidate, so output dominates cost.
    for model in CANDIDATE_MODELS:
        assert model.output_usd_per_mtok > model.input_usd_per_mtok


def test_negative_tokens_are_rejected():
    with pytest.raises(ValueError):
        HAIKU.cost_usd(-1, 0)
    with pytest.raises(ValueError):
        HAIKU.expected_latency_ms(0, -1)


def test_expected_latency_is_base_plus_per_token():
    # The un-jittered profile centre: base + prefill + decode.
    expected = (
        HAIKU.latency_base_ms
        + HAIKU.latency_per_input_token_ms * 100
        + HAIKU.latency_per_output_token_ms * 50
    )
    assert HAIKU.expected_latency_ms(100, 50) == pytest.approx(expected)
    # Latency grows with output tokens (decode is the dominant term).
    assert HAIKU.expected_latency_ms(0, 100) > HAIKU.expected_latency_ms(0, 10)


def test_tiers_order_by_price_and_speed():
    # The three candidates are a genuine fast -> frontier ladder: pricier and
    # slower per output token as the tier rises. This is what makes the go/no-go
    # comparison meaningful rather than three near-identical rows.
    ladder = [HAIKU, SONNET, OPUS]
    prices = [m.output_usd_per_mtok for m in ladder]
    decode = [m.latency_per_output_token_ms for m in ladder]
    assert prices == sorted(prices)
    assert decode == sorted(decode)
    assert [m.tier for m in ladder] == ["fast", "balanced", "frontier"]


def test_specs_are_well_formed():
    for model in CANDIDATE_MODELS:
        assert model.input_usd_per_mtok > 0
        assert model.output_usd_per_mtok > 0
        assert model.latency_base_ms > 0
        assert model.latency_per_output_token_ms > 0
        assert model.latency_sigma > 0
        assert model.context_window > 0


def test_get_model_resolves_and_fails_loudly():
    assert get_model("claude-haiku-4-5") is HAIKU
    with pytest.raises(ValueError, match="unknown model"):
        get_model("gpt-imaginary")


def test_to_dict_round_trips_through_constructor():
    data = SONNET.to_dict()
    assert ModelSpec(**data) == SONNET
