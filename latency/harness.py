"""Per-beat wall-clock measurement for the templated beat loop.

The harness walks the Act 1 spine end-to-end (:func:`game.act1.play_act1`'s body,
inlined here so the timing fence is exactly one beat) and records the elapsed
wall-clock time for each beat. It returns a :class:`BeatLatencyReport` with the
median (p50), p95, and the headline budget verdict.

Why inline the walk rather than use ``play_act1`` and an ``on_loop`` hook? Because
``on_loop`` fires *after* the loop record is built — between two beats — which
elides the time spent in :func:`game.session.offer_scene` for the next beat. The
measured fence has to enclose the **whole** per-beat critical section (offer →
templated swap → MirrorState update → policy → record), so this module mirrors
``play_act1``'s body and brackets each iteration with
:func:`time.perf_counter_ns`. Scene I/O happens once before timing starts, so
disk reads are not counted in the per-beat number (a session loads scenes once;
playing a beat does not re-read them).

The measurement is otherwise faithful to the shipped engine:

* the variant is :data:`game.variants.ADAPTIVE` (the real game's seam),
* the policy is :func:`game.act1.seeded_policy` (the M1 deterministic walk),
* the templated flavor swap at :data:`game.flavor.M1_ADAPTATION_BEAT_SLOT` fires
  through :func:`game.flavor.select_directive` and
  :meth:`game.flavor.FlavorPack.render`, and
* the typed :class:`mirror.state.MirrorState` is advanced per beat by
  ``apply_choice`` with a representative per-tendency signal, so
  ``select_directive`` is doing real work on a non-trivial state.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Sequence

from game.act1 import (
    DEFAULT_SEED,
    load_act1_world,
    seeded_policy,
)
from game.flavor import (
    M1_ADAPTATION_BEAT_SLOT,
    M1_BEAT2_FLAVOR_PACK,
    select_directive,
)
from game.session import offer_scene, record_loop
from game.variants import ADAPTIVE
from loop.core import Mirror, PlayerState
from mirror.state import Choice as MirrorChoice
from mirror.state import MirrorState, Signal

#: Default number of full session walks the harness performs. Each walk emits one
#: latency sample per beat (~14 beats per Act 1 walk), so the default produces
#: ~700 samples — enough for a stable p95 without the run becoming sluggish.
DEFAULT_TRIALS = 50

#: The acceptance-criterion latency budget the M1 task names: a beat that
#: completes inside this is "instant enough" for the templated layer; above it,
#: a pre-generate/cache plan is required.
LATENCY_BUDGET_MS = 150.0

#: Representative MirrorState signals per v0 tendency. These are chosen so that
#: walking a few beats moves at least one ``select_directive``-relevant axis off
#: neutral, exercising the directive scorer on real (not blank) state — the
#: measurement reflects the cost the layer actually pays when the Mirror has a
#: lean to read.
_TENDENCY_SIGNALS: dict[str, tuple[Signal, ...]] = {
    "kindness": (
        Signal.toward("authority_trust", target=0.6),
        Signal.toward("risk_tolerance", target=-0.6),
    ),
    "control": (
        Signal.toward("authority_trust", target=0.4),
        Signal.toward("moral_consistency", target=0.7),
    ),
    "defiance": (
        Signal.toward("authority_trust", target=-0.7),
        Signal.toward("risk_tolerance", target=0.6),
        Signal.toward("boundary_testing", target=0.9),
    ),
}


@dataclass(frozen=True)
class BeatLatencyReport:
    """One measurement run's per-beat latency distribution + verdict.

    All times are nanoseconds; helpers expose them in milliseconds for the
    report. Storing as integers means the raw samples round-trip losslessly
    through JSON and are stable across machines (no float drift in the log).
    """

    #: Every per-beat elapsed time, in nanoseconds, in the order measured. Kept
    #: in full so a caller can recompute any percentile they need.
    samples_ns: tuple[int, ...]
    #: Number of full session walks the samples came from.
    trials: int
    #: Number of beats per walk (the Act 1 spine length).
    beats_per_trial: int
    #: The latency budget the samples are compared against, in milliseconds.
    budget_ms: float = LATENCY_BUDGET_MS
    #: Seed used to drive the deterministic policy walk.
    seed: int = DEFAULT_SEED

    @property
    def n(self) -> int:
        """Total beat samples (``trials × beats_per_trial``)."""
        return len(self.samples_ns)

    @property
    def median_ms(self) -> float:
        """The p50 (median) per-beat latency, in milliseconds."""
        return _ns_to_ms(statistics.median(self.samples_ns))

    @property
    def p95_ms(self) -> float:
        """The p95 per-beat latency, in milliseconds."""
        return _ns_to_ms(_percentile(self.samples_ns, 0.95))

    @property
    def min_ms(self) -> float:
        return _ns_to_ms(min(self.samples_ns))

    @property
    def max_ms(self) -> float:
        return _ns_to_ms(max(self.samples_ns))

    @property
    def mean_ms(self) -> float:
        return _ns_to_ms(statistics.fmean(self.samples_ns))

    @property
    def over_budget(self) -> bool:
        """True iff median or p95 exceeds :attr:`budget_ms`.

        The acceptance criterion ("median > 150ms p95") is read as
        *"the templated beat loop has missed the budget if either the median
        or the p95 exceeds 150 ms."* Either failure justifies the
        pre-generate/cache plan; only a clean pass on both lets us skip it.
        """
        return self.median_ms > self.budget_ms or self.p95_ms > self.budget_ms

    def to_dict(self) -> dict:
        """JSON-serializable shape (samples kept as the integer ns array)."""
        return {
            "trials": self.trials,
            "beats_per_trial": self.beats_per_trial,
            "n": self.n,
            "seed": self.seed,
            "budget_ms": self.budget_ms,
            "median_ms": self.median_ms,
            "p95_ms": self.p95_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "over_budget": self.over_budget,
            "samples_ns": list(self.samples_ns),
        }


def measure_beat_latency(
    trials: int = DEFAULT_TRIALS,
    *,
    seed: int = DEFAULT_SEED,
    budget_ms: float = LATENCY_BUDGET_MS,
) -> BeatLatencyReport:
    """Walk the Act 1 templated beat loop ``trials`` times, timing each beat.

    Every per-beat sample brackets the whole critical section (offer → templated
    swap → MirrorState update → policy → record), measured with
    :func:`time.perf_counter_ns` to avoid wall-clock skew. Scene I/O happens once
    before any timing begins.

    Raises ``ValueError`` if ``trials`` is not positive — a zero-trial run would
    produce an empty distribution, which is not a measurement.
    """
    if trials <= 0:
        raise ValueError(f"trials must be > 0, got {trials}")

    world = load_act1_world()
    samples: list[int] = []

    for trial_index in range(trials):
        # A fresh policy per trial keeps each walk's seed-state independent,
        # so the per-trial sequence is identical across runs (every trial sees
        # the same input log, deterministic by ``seed``). The samples then
        # differ only by wall-clock jitter, which is what we are measuring.
        policy = seeded_policy(seed)
        mirror = Mirror()
        state = PlayerState()
        mirror_state = MirrorState.new()

        for i, slot in enumerate(world.slots):
            start = time.perf_counter_ns()

            declared, offered, branch_key = offer_scene(
                ADAPTIVE, mirror, state, slot
            )

            # The single templated flavor swap the M1 brief locks at Beat 2.
            # Done here on every walk through the M1 beat slot so the per-beat
            # number includes the cost of the adaptation it carries.
            if slot.key == M1_ADAPTATION_BEAT_SLOT:
                directive = select_directive(mirror_state, seed=seed)
                _flavored = M1_BEAT2_FLAVOR_PACK.render(directive)
                # Reference the rendered prompt so the optimizer cannot elide
                # the work. ``_flavored`` is the prompt body the M1 renderer
                # would hand to the view; we are timing the production of it.
                assert _flavored

            choice_id = policy(offered, state, i)

            record = record_loop(
                mirror,
                state,
                declared,
                offered,
                branch_key,
                choice_id,
                loop_index=i,
                is_finale=(i == world.length - 1),
            )

            chosen = offered.choice(choice_id)
            mirror_state.apply_choice(
                MirrorChoice(
                    id=choice_id,
                    label=chosen.text,
                    signals=_TENDENCY_SIGNALS[chosen.tendency],
                )
            )
            mirror_state.tick()

            elapsed = time.perf_counter_ns() - start
            samples.append(elapsed)

            state = record.result.state

    return BeatLatencyReport(
        samples_ns=tuple(samples),
        trials=trials,
        beats_per_trial=world.length,
        budget_ms=budget_ms,
        seed=seed,
    )


def render_report(report: BeatLatencyReport) -> str:
    """Render a :class:`BeatLatencyReport` as the markdown shipped at
    ``docs/latency_report_m1.md``.

    Layout: a TL;DR with the headline numbers + verdict, a methodology section
    that names exactly what was measured, the percentile table, and either a
    short "no plan needed" note (when the budget is met) or the pre-generate /
    cache plan the acceptance criterion calls for (when it is not).
    """
    verdict = (
        f"**OVER BUDGET** — median {report.median_ms:.3f} ms or p95 "
        f"{report.p95_ms:.3f} ms exceeds the {report.budget_ms:.0f} ms budget."
        if report.over_budget
        else (
            f"**Within budget** — median {report.median_ms:.3f} ms and "
            f"p95 {report.p95_ms:.3f} ms both sit below the "
            f"{report.budget_ms:.0f} ms budget."
        )
    )

    lines: list[str] = []
    lines.append("# Templated Beat Loop — Latency Spike (M1)")
    lines.append("")
    lines.append(
        "**What this measures.** Per-beat wall-clock time for one full iteration "
        "of the **templated** beat loop (Act 1 spine, no LLM on the path), with "
        "the M1 flavor swap at the locked adaptation beat included on every "
        "pass through it. This is the floor a future LLM integration would have "
        "to live inside — see ``docs/LLM_COST_LATENCY.md`` for the cross-check "
        "against synchronous-LLM critical-path budgets."
    )
    lines.append("")
    lines.append(f"**Result.** {verdict}")
    lines.append("")
    lines.append("## TL;DR")
    lines.append("")
    lines.append(f"- **median (p50):** {report.median_ms:.3f} ms")
    lines.append(f"- **p95:** {report.p95_ms:.3f} ms")
    lines.append(f"- **budget:** {report.budget_ms:.0f} ms (median & p95 must clear it)")
    lines.append(
        f"- **samples:** {report.n} beats "
        f"({report.trials} trials × {report.beats_per_trial} beats/trial, seed {report.seed})"
    )
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "The harness (:mod:`latency.harness`) walks the Act 1 spine "
        "(``game.act1.load_act1_world`` + ``seeded_policy``) once per trial, "
        "brackets each beat with ``time.perf_counter_ns``, and records every "
        "sample. Scene files are loaded **once** before timing begins, so disk "
        "I/O is not counted — a session loads scenes once at start, not per "
        "beat. Each timed section covers, in order:"
    )
    lines.append("")
    lines.append(
        "1. ``offer_scene`` — variant scene selection + Mirror choice re-ordering "
        "(``game.variants.ADAPTIVE``)."
    )
    lines.append(
        "2. At the M1 beat slot (``game.flavor.M1_ADAPTATION_BEAT_SLOT``), the "
        "templated flavor swap: ``select_directive`` + ``FlavorPack.render``."
    )
    lines.append("3. The seeded policy's choice draw.")
    lines.append(
        "4. ``record_loop`` — ``Mirror.step`` (predict → record → reflect) + "
        "the system-voice template render."
    )
    lines.append(
        "5. ``MirrorState.apply_choice`` + ``MirrorState.tick`` — the typed M1 "
        "player-model step, fed a per-tendency signal so the next "
        "``select_directive`` sees real state, not neutral."
    )
    lines.append("")
    lines.append(
        "Everything on this path is templated and deterministic; no network, no "
        "LLM, no clock-bound work other than the measurement fence itself. The "
        "policy and the seed are fixed so the per-beat *work* is identical "
        "across trials — the per-beat *latency* is what varies."
    )
    lines.append("")
    lines.append("## Distribution")
    lines.append("")
    lines.append("| stat | value (ms) |")
    lines.append("|---|---:|")
    lines.append(f"| min | {report.min_ms:.3f} |")
    lines.append(f"| median (p50) | {report.median_ms:.3f} |")
    lines.append(f"| mean | {report.mean_ms:.3f} |")
    lines.append(f"| p95 | {report.p95_ms:.3f} |")
    lines.append(f"| max | {report.max_ms:.3f} |")
    lines.append(f"| n | {report.n} |")
    lines.append("")

    if report.over_budget:
        lines.append("## Pre-generate / cache plan (budget missed)")
        lines.append("")
        lines.append(
            "The templated beat loop missed the "
            f"{report.budget_ms:.0f} ms per-beat budget. The plan to bring it "
            "back inside the budget, in priority order:"
        )
        lines.append("")
        lines.append(
            "1. **Pre-generate the per-beat content at session start.** A whole "
            "Act 1 walk's prompts (canonical + every authored flavor variant) "
            "are tiny and authored offline. Render each beat's "
            "``(directive → prompt)`` mapping once into an in-memory table at "
            "``play_act1`` boot, then look it up at beat time. This converts "
            "the templated render from a per-beat cost into a one-shot startup "
            "cost (off the player's clock by definition)."
        )
        lines.append(
            "2. **Cache the offer.** ``offer_scene``'s output is a pure function "
            "of ``(variant, slot, state)`` and ``state`` only changes at choice "
            "time; memoise per ``(slot.key, tendency_counts_signature)`` so a "
            "second look at the same offer is free. Eviction is bounded by the "
            "number of distinct tendency-tally signatures reachable in one "
            "session (small)."
        )
        lines.append(
            "3. **Hoist the system-voice template render out of the hot path.** "
            "``adapt_message`` is template substitution; precompute the message "
            "shells for each ``(dominant, just_noticed, model_locked, "
            "predicted_hit, is_finale)`` tuple at module load and only fill the "
            "counts/totals at beat time."
        )
        lines.append(
            "4. **If still over budget after (1)-(3): degrade the adaptation "
            "seam to the identity transform** (``game.variants.FIXED``) until "
            "the templated path clears the budget on its own. The structural "
            "baseline≡adaptive parity gate (``docs/mirror_loop_m1_synthesis.md``) "
            "guarantees the engine is byte-identical without the seam, so this "
            "is a safe fallback rather than a content change."
        )
        lines.append("")
        lines.append(
            "Re-run ``python -m latency`` after each step and stop at the first "
            "one that brings p95 inside budget."
        )
    else:
        lines.append("## Pre-generate / cache plan?")
        lines.append("")
        lines.append(
            "**Not needed.** The acceptance criterion requires a "
            "pre-generate/cache plan only if the templated beat loop misses the "
            f"{report.budget_ms:.0f} ms budget; both the median and p95 sit well "
            "below it, so the templated path has ample headroom and an LLM "
            "integration (if it ever lands) would land **outside** this loop "
            "anyway (``docs/LLM_COST_LATENCY.md`` §4)."
        )
        lines.append("")
        lines.append(
            "For future reference, the plan that *would* have been written here "
            "if the budget had been missed is: (1) precompute the "
            "``(directive → prompt body)`` table at session start, (2) memoise "
            "``offer_scene`` keyed on ``(slot, tendency tally)``, (3) hoist the "
            "``adapt_message`` template render out of the hot path, and (4) "
            "fall back to ``FIXED`` (identity-seam) variant if still over "
            "budget — in that order."
        )

    lines.append("")
    lines.append("## Reproducing")
    lines.append("")
    lines.append("```")
    lines.append("python -m latency                       # markdown report")
    lines.append("python -m latency --json                # same report, JSON")
    lines.append("python -m latency --trials 200 --seed 7 # tighter percentiles")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


# --- Internals ---------------------------------------------------------------


def _ns_to_ms(value: float) -> float:
    """Convert nanoseconds to milliseconds, rounded to ``0.001 ms`` (1 µs)."""
    return round(value / 1_000_000.0, 3)


def _percentile(samples: Sequence[int], q: float) -> float:
    """Inclusive nearest-rank percentile.

    ``q`` is in ``[0, 1]``; samples are ranked smallest-first and the value at
    ``ceil(n*q)`` is returned (``q=0`` returns the minimum). Nearest-rank rather
    than linear interpolation so the reported number is always one of the
    measured samples — useful when those samples are integer nanoseconds and we
    do not want to fabricate a fractional sample the run did not produce.
    """
    import math

    if not samples:
        raise ValueError("percentile of empty sample set is undefined")
    if not (0.0 <= q <= 1.0):
        raise ValueError(f"percentile q must be in [0, 1], got {q}")
    ordered = sorted(samples)
    if q == 0.0:
        return float(ordered[0])
    rank = max(1, min(len(ordered), math.ceil(len(ordered) * q)))
    return float(ordered[rank - 1])
