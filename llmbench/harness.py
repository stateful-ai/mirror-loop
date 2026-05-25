"""The offline harness: sweep candidates × insertion points, report the numbers.

This is the instrument the task asks for. It drives an :class:`~llmbench.client.LLMClient`
(the offline :class:`~llmbench.client.SimulatedClient` by default) over the real
prompt corpus (``llmbench.prompts``) and produces exactly the figures the
acceptance bar names:

* **p50 / p95 latency** per (model, insertion point) — many prompts × ``trials``
  jittered samples each, summarised with the linear-interpolation percentile
  (``llmbench.metrics``).
* **per-adaptation cost** — the dollar cost of a single call at each insertion
  point (one content decision = one call), computed exactly from real token counts.
* **per-session cost** — those per-call costs multiplied by how many calls of each
  kind a real session makes, derived from the shipped world (:class:`SessionProfile`).

Everything is deterministic: the same ``(seed, trials, world)`` yields byte-stable
results, so the numbers in ``docs/LLM_COST_LATENCY.md`` are reproducible with
``python -m llmbench``. The harness only *measures*; it is never imported by the
game loop (pinned by ``llmbench/tests/test_not_wired_into_loop.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from game.world import DEFAULT_WORLD, World

from .client import LLMClient, SimulatedClient
from .metrics import mean, percentile
from .models import CANDIDATE_MODELS, ModelSpec
from .prompts import (
    INSERTION_POINTS,
    InsertionPoint,
    Prompt,
    build_corpus,
)

#: Bump if the serialized :class:`Report` shape changes incompatibly.
SCHEMA_VERSION = 1

#: Default jittered samples per prompt. Large enough that p50/p95 are stable run
#: to run; small enough that a full sweep is instant (the simulator never sleeps).
DEFAULT_TRIALS = 200

#: Default run seed — the repo's canonical seed (``game.replay.DEFAULT_SEED``).
DEFAULT_SEED = 42


@dataclass(frozen=True)
class SessionProfile:
    """How many calls of each insertion point one real session makes.

    Grounded in the shipped world, not guessed: an NPC reply fires once per loop,
    and a branch candidate is authored once per **branch** slot (the slots whose
    framing the Mirror selects). :meth:`from_world` reads both counts off the world
    so the per-session multiplier tracks the content rather than a hardcoded
    constant.
    """

    world_name: str
    calls_per_session: dict[InsertionPoint, int]

    @classmethod
    def from_world(cls, world: World = DEFAULT_WORLD) -> "SessionProfile":
        branch_slots = sum(1 for slot in world.slots if slot.variants is not None)
        return cls(
            world_name=world.name,
            calls_per_session={
                InsertionPoint.NPC_REPLY: world.length,
                InsertionPoint.BRANCH_CANDIDATE: branch_slots,
            },
        )

    def to_dict(self) -> dict:
        return {
            "world": self.world_name,
            "calls_per_session": {
                point.value: count for point, count in self.calls_per_session.items()
            },
        }


@dataclass(frozen=True)
class CallStats:
    """Measured cost/latency for one (model, insertion point) pair.

    ``cost_per_call_usd`` is the **per-adaptation** cost — one content decision is
    one call. Latency percentiles are over every jittered sample; cost figures are
    over the corpus (output tokens are fixed by the task, so cost varies only with
    each prompt's real input size).
    """

    model: str
    insertion_point: InsertionPoint
    on_critical_path: bool
    n_prompts: int
    n_samples: int
    latency_p50_ms: float
    latency_p95_ms: float
    cost_per_call_usd: float
    mean_input_tokens: float
    output_tokens: int

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "insertion_point": self.insertion_point.value,
            "on_critical_path": self.on_critical_path,
            "n_prompts": self.n_prompts,
            "n_samples": self.n_samples,
            "latency_p50_ms": round(self.latency_p50_ms, 1),
            "latency_p95_ms": round(self.latency_p95_ms, 1),
            "cost_per_call_usd": self.cost_per_call_usd,
            "mean_input_tokens": round(self.mean_input_tokens, 1),
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True)
class SessionCost:
    """Total LLM cost of one session for a model, and its per-point breakdown."""

    model: str
    per_point_usd: dict[InsertionPoint, float]
    total_usd: float

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "per_point_usd": {p.value: c for p, c in self.per_point_usd.items()},
            "total_usd": self.total_usd,
        }


@dataclass(frozen=True)
class Report:
    """The full sweep: every (model, insertion point) stat and per-session cost."""

    seed: int
    trials: int
    world_name: str
    session_profile: SessionProfile
    call_stats: tuple[CallStats, ...]
    session_costs: tuple[SessionCost, ...]
    schema_version: int = SCHEMA_VERSION

    def stat(self, model: str, point: InsertionPoint) -> CallStats:
        for s in self.call_stats:
            if s.model == model and s.insertion_point is point:
                return s
        raise KeyError(f"no stats for {model!r} at {point.value!r}")

    def session_cost(self, model: str) -> SessionCost:
        for c in self.session_costs:
            if c.model == model:
                return c
        raise KeyError(f"no session cost for {model!r}")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run": {
                "seed": self.seed,
                "trials": self.trials,
                "world": self.world_name,
            },
            "session_profile": self.session_profile.to_dict(),
            "call_stats": [s.to_dict() for s in self.call_stats],
            "session_costs": [c.to_dict() for c in self.session_costs],
        }


def _measure_pair(
    model: ModelSpec,
    point: InsertionPoint,
    prompts: tuple[Prompt, ...],
    client: LLMClient,
    trials: int,
) -> CallStats:
    """Sweep one (model, insertion point): all prompts × ``trials`` samples."""
    if not prompts:
        raise ValueError(f"no prompts for insertion point {point.value!r}")
    spec = INSERTION_POINTS[point]
    latencies: list[float] = []
    input_tokens: list[int] = []
    per_call_costs: list[float] = []
    for prompt in prompts:
        # Cost is per prompt (output tokens fixed; input deterministic), latency is
        # per trial (jittered) — so a prompt contributes one cost and many latencies.
        first = client.complete(prompt, model=model, trial=0)
        input_tokens.append(first.input_tokens)
        per_call_costs.append(model.cost_usd(first.input_tokens, first.output_tokens))
        latencies.append(first.latency_ms)
        for trial in range(1, trials):
            latencies.append(
                client.complete(prompt, model=model, trial=trial).latency_ms
            )
    return CallStats(
        model=model.name,
        insertion_point=point,
        on_critical_path=spec.on_critical_path,
        n_prompts=len(prompts),
        n_samples=len(latencies),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        cost_per_call_usd=percentile(per_call_costs, 50),
        mean_input_tokens=mean(input_tokens),
        output_tokens=spec.expected_output_tokens,
    )


def measure(
    *,
    models: tuple[ModelSpec, ...] = CANDIDATE_MODELS,
    world: World = DEFAULT_WORLD,
    trials: int = DEFAULT_TRIALS,
    seed: int = DEFAULT_SEED,
    client: LLMClient | None = None,
) -> Report:
    """Run the full offline sweep and return a :class:`Report`.

    For every model and insertion point, measures latency percentiles and the
    per-call (per-adaptation) cost on the real corpus, then composes per-session
    cost from the world-derived :class:`SessionProfile`. Deterministic in
    ``(seed, trials, world, models)``.
    """
    if trials < 1:
        raise ValueError(f"trials must be >= 1, got {trials}")
    client = client or SimulatedClient(seed=seed)
    corpus = build_corpus(world)
    profile = SessionProfile.from_world(world)

    call_stats: list[CallStats] = []
    for model in models:
        for point in INSERTION_POINTS:
            call_stats.append(
                _measure_pair(model, point, corpus[point], client, trials)
            )

    session_costs: list[SessionCost] = []
    for model in models:
        per_point = {
            point: profile.calls_per_session[point]
            * next(
                s.cost_per_call_usd
                for s in call_stats
                if s.model == model.name and s.insertion_point is point
            )
            for point in INSERTION_POINTS
        }
        session_costs.append(
            SessionCost(
                model=model.name,
                per_point_usd=per_point,
                total_usd=math.fsum(per_point.values()),
            )
        )

    return Report(
        seed=seed,
        trials=trials,
        world_name=world.name,
        session_profile=profile,
        call_stats=tuple(call_stats),
        session_costs=tuple(session_costs),
    )


# --- Rendering ----------------------------------------------------------------


def _usd(amount: float) -> str:
    """Format a dollar amount with enough precision for sub-cent per-call costs."""
    if amount == 0:
        return "$0"
    if amount < 0.01:
        return f"${amount:.5f}"
    return f"${amount:.4f}"


def render_report(report: Report) -> str:
    """Render the report as a human-readable markdown document."""
    lines: list[str] = []
    lines.append("# LLM cost/latency — offline harness measurement")
    lines.append("")
    lines.append(
        f"seed={report.seed} · trials/prompt={report.trials} · "
        f"world={report.world_name!r}"
    )
    lines.append("")

    lines.append("## Latency and per-adaptation cost (per model × insertion point)")
    lines.append("")
    lines.append(
        "| Model | Insertion point | Path | in tok | out tok | "
        "p50 latency | p95 latency | cost/call |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for stat in report.call_stats:
        spec = INSERTION_POINTS[stat.insertion_point]
        path = "critical" if stat.on_critical_path else "off-path"
        lines.append(
            f"| {stat.model} | {spec.label} | {path} | "
            f"{stat.mean_input_tokens:.0f} | {stat.output_tokens} | "
            f"{stat.latency_p50_ms:.0f} ms | {stat.latency_p95_ms:.0f} ms | "
            f"{_usd(stat.cost_per_call_usd)} |"
        )
    lines.append("")

    profile = report.session_profile.calls_per_session
    profile_desc = ", ".join(
        f"{INSERTION_POINTS[p].label} ×{n}" for p, n in profile.items()
    )
    lines.append("## Per-session cost")
    lines.append("")
    lines.append(f"One session = {profile_desc} (from world {report.world_name!r}).")
    lines.append("")
    lines.append("| Model | NPC replies | Branch candidates | Session total |")
    lines.append("|---|---:|---:|---:|")
    for cost in report.session_costs:
        npc = cost.per_point_usd[InsertionPoint.NPC_REPLY]
        branch = cost.per_point_usd[InsertionPoint.BRANCH_CANDIDATE]
        lines.append(
            f"| {cost.model} | {_usd(npc)} | {_usd(branch)} | "
            f"**{_usd(cost.total_usd)}** |"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "CallStats",
    "DEFAULT_SEED",
    "DEFAULT_TRIALS",
    "Report",
    "SCHEMA_VERSION",
    "SessionCost",
    "SessionProfile",
    "measure",
    "render_report",
]
