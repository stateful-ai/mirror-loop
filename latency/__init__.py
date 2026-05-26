"""Latency feasibility spike for the **templated beat loop**.

This is the M1 founder-brief DoD #8 latency spike (``docs/mirror_loop_m1_founder_brief.md``
- *"Latency spike has written one number into ``docs/latency_budget.md``"*) carried
through to its measurement form: a tiny, stdlib-only harness that walks the Act 1
templated beat loop and records **per-beat wall-clock latency** so the M1 build
has a real ``(p50, p95)`` to point at rather than a vibe.

The "templated beat loop" — for the purpose of this measurement — is the loop the
M1 slice actually walks today: each iteration through :mod:`game.act1`'s spine.
One **beat** is the work the engine does between the player making one choice and
seeing the next prompt:

1. ``offer_scene`` — the variant's scene selection + the Mirror's choice re-ordering
   (the single adaptation seam, :mod:`game.variants`),
2. the templated **flavor swap** at the M1 adaptation beat slot
   (:func:`game.flavor.select_directive` + :meth:`game.flavor.FlavorPack.render`),
3. the **MirrorState** per-choice update (``mirror.state.MirrorState.apply_choice``)
   — the typed-axis player-model step the M1 reducer would record,
4. the policy's choice,
5. ``record_loop`` — :meth:`loop.core.Mirror.step` and the system-voice
   ``adapt_message`` render.

Every step above is **templated and deterministic** — no LLM is on the path
(:mod:`llmbench`'s NO-GO on the critical path,
``docs/LLM_COST_LATENCY.md`` §4). What this spike measures is the floor: how
fast that templated path actually is on real hardware, so a future LLM
integration knows the budget it would have to live inside.

The harness is **opt-in measurement code**: nothing in the game runtime
imports it, same posture as :mod:`llmbench` and :mod:`telemetry`. It uses
:func:`time.perf_counter_ns` (process-local, monotonic), runs no I/O on the
hot path (scenes are loaded once before timing starts), and reports
percentiles via :mod:`statistics`. The output is a markdown report
(:func:`latency.harness.render_report`) suitable for committing as
``docs/latency_report_m1.md`` and a JSON form for tooling.
"""

from .harness import (
    DEFAULT_TRIALS,
    LATENCY_BUDGET_MS,
    BeatLatencyReport,
    measure_beat_latency,
    render_report,
)

__all__ = [
    "DEFAULT_TRIALS",
    "LATENCY_BUDGET_MS",
    "BeatLatencyReport",
    "measure_beat_latency",
    "render_report",
]
