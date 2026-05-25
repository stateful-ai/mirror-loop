"""A model-independent latency floor for the critical path.

Why this exists: the go/no-go's headline — *no synchronous LLM call on the
per-loop hot path* — must not rest on the harness's **modeled** latency constants.
Those constants are conservative assumptions awaiting a live spike
(:mod:`llmbench.models`), and a decision that hinges on them is only as good as the
assumption. This module derives the same conclusion from quantities that are *not*
assumptions about any particular model, so the NO-GO is robust by construction
rather than by assertion.

The argument is a **floor**, not an estimate. A synchronous completion cannot
return before it has produced its output, and an autoregressive model produces
output one token at a time. So whatever a model's queueing, time-to-first-token,
prefill, and network round-trip cost — all of which are ``>= 0`` — the call takes
**at least** the time to decode ``output_tokens`` tokens:

    decode_floor_ms = output_tokens * 1000 / decode_tokens_per_second

Equivalently, to fit a responsiveness budget a model would have to *sustain* at
least::

    required_tps = output_tokens * 1000 / budget_ms

tokens per second **counting decode alone** — i.e. while granting a physically
impossible zero-overhead, zero-network endpoint. If that required rate is beyond
what hosted models sustain, then no choice of the modeled overhead constants can
rescue the critical path: the conclusion does not depend on them.

The two budgets are standard UX thresholds (Nielsen, *Response Times: The 3
Important Limits*): ~100 ms still reads as **instant**, ~1 s is the ceiling before
a user perceives a **stall**. The hot path here wants the former (its whole appeal
is a snappy, deterministic core); we additionally test against the lenient latter
to make the floor argument as conservative as it can be.

``required_tps`` uses no model constant at all — only the task's output budget and
a UX threshold. The per-model decode floor uses a single model parameter, the raw
decode throughput, with *every other* latency component set to its most favourable
value (zero); it is the absolute best case for that model. Both are in
:class:`CriticalPathFloor`, surfaced in the harness report next to the modeled
table so the decision can be read off the floor, not the assumed milliseconds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CANDIDATE_MODELS, ModelSpec
from .prompts import INSERTION_POINTS

#: UX thresholds (ms). ~100 ms reads as instantaneous; ~1 s is the ceiling before
#: a user perceives the system stalling (Nielsen's response-time limits).
INSTANT_BUDGET_MS = 100.0
STALL_BUDGET_MS = 1000.0


def required_decode_tps(output_tokens: int, budget_ms: float) -> float:
    """Sustained decode rate needed to emit ``output_tokens`` within ``budget_ms``.

    Counts decode alone — it grants a zero network, zero time-to-first-token, zero
    prefill endpoint — so it is a lower bound on the throughput any real synchronous
    call would need. Depends only on the task's output budget and the UX threshold,
    not on any model constant.
    """
    if output_tokens < 0:
        raise ValueError("output_tokens must be non-negative")
    if budget_ms <= 0:
        raise ValueError("budget_ms must be positive")
    return output_tokens * 1000.0 / budget_ms


@dataclass(frozen=True)
class ModelFloor:
    """One candidate's decode-only latency floor for the critical-path call.

    ``decode_floor_ms`` is ``output_tokens * per_output_token_ms`` — the time to
    decode the output at the model's modeled throughput, with base overhead,
    prefill, and network all set to zero. ``over_instant_budget`` is how many times
    that floor exceeds the instant threshold: equivalently, the factor by which the
    model would have to *beat* its modeled decode rate (and add no other latency) to
    feel instant.
    """

    model: str
    decode_floor_ms: float
    over_instant_budget: float
    fits_instant_budget: bool
    fits_stall_budget: bool

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "decode_floor_ms": round(self.decode_floor_ms, 1),
            "over_instant_budget": round(self.over_instant_budget, 1),
            "fits_instant_budget": self.fits_instant_budget,
            "fits_stall_budget": self.fits_stall_budget,
        }


@dataclass(frozen=True)
class CriticalPathFloor:
    """The model-independent floor under the critical-path NO-GO.

    Combines the assumption-free ``required_tps`` (output budget + UX threshold
    only) with each candidate's decode-only floor, so a reader can see both that the
    required throughput is implausible and that even the candidates' own modeled
    decode rates fall short — without trusting the overhead constants.
    """

    output_tokens: int
    instant_budget_ms: float
    stall_budget_ms: float
    required_tps_instant: float
    required_tps_stall: float
    per_model: tuple[ModelFloor, ...]

    @classmethod
    def for_models(
        cls,
        models: tuple[ModelSpec, ...] = CANDIDATE_MODELS,
        *,
        output_tokens: int | None = None,
        instant_budget_ms: float = INSTANT_BUDGET_MS,
        stall_budget_ms: float = STALL_BUDGET_MS,
    ) -> "CriticalPathFloor":
        """Build the floor for the critical-path insertion point.

        ``output_tokens`` defaults to the worst-case (largest) output budget among
        the insertion points that sit on the critical path, read off
        :data:`llmbench.prompts.INSERTION_POINTS` so it tracks the design rather
        than a hardcoded constant.
        """
        if output_tokens is None:
            output_tokens = _critical_path_output_budget()
        per_model = tuple(
            ModelFloor(
                model=model.name,
                decode_floor_ms=(floor := model.latency_per_output_token_ms * output_tokens),
                over_instant_budget=floor / instant_budget_ms,
                fits_instant_budget=floor <= instant_budget_ms,
                fits_stall_budget=floor <= stall_budget_ms,
            )
            for model in models
        )
        return cls(
            output_tokens=output_tokens,
            instant_budget_ms=instant_budget_ms,
            stall_budget_ms=stall_budget_ms,
            required_tps_instant=required_decode_tps(output_tokens, instant_budget_ms),
            required_tps_stall=required_decode_tps(output_tokens, stall_budget_ms),
            per_model=per_model,
        )

    def to_dict(self) -> dict:
        return {
            "output_tokens": self.output_tokens,
            "instant_budget_ms": self.instant_budget_ms,
            "stall_budget_ms": self.stall_budget_ms,
            "required_tps_instant": round(self.required_tps_instant, 1),
            "required_tps_stall": round(self.required_tps_stall, 1),
            "per_model": [m.to_dict() for m in self.per_model],
        }


def _critical_path_output_budget() -> int:
    """The largest output budget among critical-path insertion points."""
    on_path = [
        spec.expected_output_tokens
        for spec in INSERTION_POINTS.values()
        if spec.on_critical_path
    ]
    if not on_path:
        raise ValueError("no critical-path insertion point to bound")
    return max(on_path)


def render_floor(floor: CriticalPathFloor) -> list[str]:
    """Render the floor as markdown lines for the harness report.

    Latencies are shown coarsely (``~N.N s``) because the per-model floor is still
    derived from a modeled throughput; the load-bearing figures are the
    assumption-free required throughput and the over-budget multiple.
    """
    lines: list[str] = []
    lines.append("## Critical-path floor (model-independent)")
    lines.append("")
    lines.append(
        f"The on-path call budgets ~{floor.output_tokens} output tokens and the player "
        "waits on it every loop. A synchronous call cannot beat its own decode time, "
        "so — granting a physically impossible zero-network, zero-time-to-first-token, "
        "zero-prefill endpoint — it must still *sustain*:"
    )
    lines.append("")
    lines.append(
        f"- **≥ {floor.required_tps_instant:.0f} tok/s** to feel instant "
        f"(≤ {floor.instant_budget_ms:.0f} ms)"
    )
    lines.append(
        f"- **≥ {floor.required_tps_stall:.0f} tok/s** to merely avoid a perceptible "
        f"stall (≤ {floor.stall_budget_ms / 1000:.0f} s)"
    )
    lines.append("")
    lines.append(
        "Decode-only floor per candidate (its modeled decode rate, every other "
        "latency component set to zero):"
    )
    lines.append("")
    lines.append("| Model | decode-only floor | × over instant budget | fits ≤1 s? |")
    lines.append("|---|---:|---:|:--:|")
    for m in floor.per_model:
        fits = "yes" if m.fits_stall_budget else "no"
        lines.append(
            f"| {m.model} | ~{m.decode_floor_ms / 1000:.1f} s | "
            f"{m.over_instant_budget:.1f}× | {fits} |"
        )
    lines.append("")
    worst = max(m.over_instant_budget for m in floor.per_model)
    best = min(m.over_instant_budget for m in floor.per_model)
    factor = f"{best:.0f}×" if best == worst else f"{best:.0f}–{worst:.0f}×"
    lines.append(
        f"So a candidate would have to decode **{factor} faster than its modeled rate "
        "_and_ add no network latency** to reach an instant hot path — which no hosted "
        "model does. The NO-GO holds for any reasonable constants; a live spike "
        "sharpens the absolute numbers, it does not move this floor."
    )
    lines.append("")
    return lines


__all__ = [
    "INSTANT_BUDGET_MS",
    "STALL_BUDGET_MS",
    "CriticalPathFloor",
    "ModelFloor",
    "render_floor",
    "required_decode_tps",
]
