"""``llmbench`` — the offline LLM cost/latency harness.

A standalone measurement instrument that answers, *before* any model touches the
gameplay loop, two questions about the candidate models on **real prompts**: what
they cost (per adaptation and per session, computed exactly), and whether they can
sit on the latency-sensitive critical path. The latter is settled by a
**model-independent floor** (``llmbench.budget``) — decode time alone versus a UX
budget — with a per-model *modeled* p50/p95 profile for illustration and a live
spike (``--live``) for measured wall-clock latency on demand. It exists because the
prototype deliberately defers the LLM — v0 adaptation is templated and
deterministic, and "any LLM is measured in an offline cost/latency harness before it
enters the loop" (company principle; ``docs/ADAPTATION.md`` §5).

The written go/no-go that interprets these numbers — where (if anywhere) the LLM
belongs and the deterministic fallback — is ``docs/LLM_COST_LATENCY.md``.

This package is **not wired into the loop**: nothing in the game/engine imports it
(enforced by ``llmbench/tests/test_not_wired_into_loop.py``). It imports the real
world content the other way around, to build prompts the loop would actually send.

Run it::

    python -m llmbench            # the measurement report (markdown)
    python -m llmbench --json     # the same report as JSON
"""

from __future__ import annotations

from .budget import CriticalPathFloor, ModelFloor, required_decode_tps
from .client import Completion, LLMClient, SimulatedClient
from .harness import (
    CallStats,
    Report,
    SessionCost,
    SessionProfile,
    main,
    measure,
    render_report,
)
from .metrics import mean, percentile
from .models import CANDIDATE_MODELS, ModelSpec, get_model
from .prompts import INSERTION_POINTS, InsertionPoint, Prompt, build_corpus
from .tokens import estimate_tokens

__all__ = [
    "CANDIDATE_MODELS",
    "CallStats",
    "Completion",
    "CriticalPathFloor",
    "INSERTION_POINTS",
    "InsertionPoint",
    "LLMClient",
    "ModelFloor",
    "ModelSpec",
    "Prompt",
    "Report",
    "SessionCost",
    "SessionProfile",
    "SimulatedClient",
    "build_corpus",
    "estimate_tokens",
    "get_model",
    "main",
    "mean",
    "measure",
    "percentile",
    "render_report",
    "required_decode_tps",
]
