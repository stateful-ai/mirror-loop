"""Candidate model specs — pricing and a per-model latency profile.

This is the parameter sheet the offline harness measures against. The prototype
defers the LLM (``docs/ADAPTATION.md`` §5; company principle *"v0 adaptation stays
templated/deterministic; any LLM is measured in an offline cost/latency harness
before it enters the loop"*), so before a model can be wired into the content
supply chain we need two numbers per candidate: **what it costs** and **how slow
it is**.

Two of those quantities are knowable offline with different fidelity, and the
split is deliberate:

* **Cost is exact.** Given a prompt's token counts (``llmbench.tokens``) and a
  price sheet, the dollar cost of a call is arithmetic — no model has to run. The
  prices below are public list prices (USD per million tokens); :meth:`ModelSpec.cost_usd`
  turns tokens into dollars.
* **Latency is modeled, not live-measured.** Without a live endpoint the harness
  cannot observe a real wall clock, so each model carries an analytic latency
  *profile* — a fixed overhead plus a per-token decode cost, with a lognormal
  jitter that gives the sampled distribution a realistic right tail (so p95 > p50
  is meaningful, ``llmbench.client``). These figures are deliberately conservative
  published-throughput assumptions and are the one input a short **live latency
  spike** should replace before anything is wired in (founder brief DoD #8).

Numbers are assumptions as of **2026-05** and are the single edit point if a price
or a throughput figure changes; treat absolute dollars/milliseconds as
order-of-magnitude until the live spike confirms them. The harness's load-bearing
output is the *relative* comparison and the per-session structure, both of which
are robust to the exact constants.

Candidates span the three tiers the design cares about — a fast/cheap tier for the
latency-sensitive critical path, and heavier tiers for off-path authoring where
quality matters more than milliseconds (``README.md`` "Development Principles" #3,
#4: keep LLM calls off the critical path; use short context packets for fast
replies).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump if the serialized :class:`ModelSpec` shape changes incompatibly.
SCHEMA_VERSION = 1

#: Tokens per million — the unit list prices are quoted in.
_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelSpec:
    """One candidate model: its price sheet and its latency profile.

    Pricing (``input_usd_per_mtok`` / ``output_usd_per_mtok``) drives the *exact*
    cost arithmetic. The latency fields describe a *modeled* call duration in
    milliseconds:

        latency = base + per_input * input_tokens + per_output * output_tokens

    scaled by a per-call lognormal jitter factor with shape ``latency_sigma``
    (applied in :mod:`llmbench.client`), so a run over many prompts and trials
    yields a distribution with a realistic tail rather than a single point.
    ``latency_per_output_token_ms`` is the dominant term — it is ``1000 /
    decode_tokens_per_second`` — because autoregressive decoding, not prefill,
    sets generation latency.
    """

    name: str
    #: Display grouping: "fast" | "balanced" | "frontier".
    tier: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    #: Fixed per-call overhead (queueing + time-to-first-token), ms.
    latency_base_ms: float
    #: Prefill cost per input token, ms (small; prefill is parallel and cheap).
    latency_per_input_token_ms: float
    #: Decode cost per output token, ms (= 1000 / decode tokens-per-second).
    latency_per_output_token_ms: float
    #: Shape of the lognormal jitter applied to each sampled latency (unitless).
    latency_sigma: float
    #: Maximum context window, tokens (sanity bound for prompt sizes).
    context_window: int

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Exact dollar cost of one call with these token counts."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        return (
            input_tokens * self.input_usd_per_mtok
            + output_tokens * self.output_usd_per_mtok
        ) / _PER_MILLION

    def expected_latency_ms(self, input_tokens: int, output_tokens: int) -> float:
        """The profile's *median* (un-jittered) latency for these token counts.

        The analytic centre of the sampled distribution — useful for tests and
        for reasoning about a model without drawing samples.
        """
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        return (
            self.latency_base_ms
            + self.latency_per_input_token_ms * input_tokens
            + self.latency_per_output_token_ms * output_tokens
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tier": self.tier,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "latency_base_ms": self.latency_base_ms,
            "latency_per_input_token_ms": self.latency_per_input_token_ms,
            "latency_per_output_token_ms": self.latency_per_output_token_ms,
            "latency_sigma": self.latency_sigma,
            "context_window": self.context_window,
        }


def _per_output_ms(tokens_per_second: float) -> float:
    """Decode ms/token from a tokens-per-second throughput assumption."""
    return 1000.0 / tokens_per_second


# --- The candidate set -------------------------------------------------------
# One per tier. Prices are public list prices (USD / million tokens) and decode
# throughputs are conservative published figures, both as of 2026-05. See the
# module docstring: these are the constants a live spike should confirm.

HAIKU = ModelSpec(
    name="claude-haiku-4-5",
    tier="fast",
    input_usd_per_mtok=1.00,
    output_usd_per_mtok=5.00,
    latency_base_ms=300.0,
    latency_per_input_token_ms=0.03,
    latency_per_output_token_ms=_per_output_ms(110.0),  # ~9.1 ms/token
    latency_sigma=0.25,
    context_window=200_000,
)

SONNET = ModelSpec(
    name="claude-sonnet-4-6",
    tier="balanced",
    input_usd_per_mtok=3.00,
    output_usd_per_mtok=15.00,
    latency_base_ms=450.0,
    latency_per_input_token_ms=0.05,
    latency_per_output_token_ms=_per_output_ms(55.0),  # ~18.2 ms/token
    latency_sigma=0.28,
    context_window=200_000,
)

OPUS = ModelSpec(
    name="claude-opus-4-7",
    tier="frontier",
    input_usd_per_mtok=15.00,
    output_usd_per_mtok=75.00,
    latency_base_ms=650.0,
    latency_per_input_token_ms=0.08,
    latency_per_output_token_ms=_per_output_ms(30.0),  # ~33.3 ms/token
    latency_sigma=0.30,
    context_window=200_000,
)

#: The candidates the harness measures, cheapest/fastest first.
CANDIDATE_MODELS: tuple[ModelSpec, ...] = (HAIKU, SONNET, OPUS)


def get_model(name: str) -> ModelSpec:
    """Resolve a candidate by :attr:`ModelSpec.name` (fail-loud on unknown)."""
    for model in CANDIDATE_MODELS:
        if model.name == name:
            return model
    known = ", ".join(m.name for m in CANDIDATE_MODELS)
    raise ValueError(f"unknown model {name!r}; candidates: {known}")


__all__ = [
    "CANDIDATE_MODELS",
    "HAIKU",
    "OPUS",
    "SCHEMA_VERSION",
    "SONNET",
    "ModelSpec",
    "get_model",
]
