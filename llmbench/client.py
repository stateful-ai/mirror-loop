"""The measurement seam: an ``LLMClient`` protocol and an offline simulator.

The harness times and prices calls through one narrow interface, :class:`LLMClient`,
so the *same* harness can drive either a real, networked client (which would set
``latency_ms`` from a measured wall clock and the token counts from the provider's
reported usage) or the offline :class:`SimulatedClient` shipped here. Keeping the
two behind one protocol is the same "interchangeable implementations behind one
contract" pattern the rest of the project uses for rendering and adaptation
(``docs/adr/0002`` rationale #4; company principle on the content-adapter contract).

Only the simulator ships. A live client needs network and credentials, which the
prototype deliberately has not taken on (stdlib-only, offline, deterministic CI —
``docs/adr/0002``), so wiring one in is out of scope for *measuring before
integration*. The simulator is what makes the harness an **offline** instrument:

* **Token counts** come from the real prompt text via :func:`llmbench.tokens.estimate_tokens`
  (input) and the task's output budget (output), so **cost is computed from real
  prompts**, exactly.
* **Latency** is drawn from the model's analytic profile (``llmbench.models``)
  scaled by a per-call lognormal jitter, so a run yields a realistic distribution.
  The randomness is seeded from a SHA-256 of ``(seed, model, prompt id, trial)`` —
  never Python's hash-randomized ``hash()`` — so measurements are byte-stable
  across processes and ``PYTHONHASHSEED`` values, matching the determinism rigor
  the rest of the repo enforces (``game/tests/test_instrumentation.py``).

The simulator never sleeps: it *computes* the modeled latency and reports it, so a
full sweep is instant and CI-friendly. A real client would instead measure elapsed
wall-clock time and put it in the same field.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Protocol

from .models import ModelSpec
from .prompts import Prompt
from .tokens import estimate_tokens


@dataclass(frozen=True)
class Completion:
    """The measured result of one call — only what cost/latency need.

    A real client maps its response onto these three fields (token usage +
    measured latency); the simulator fills them from the model profile. ``text`` is
    deliberately absent: this harness measures cost and latency, not output
    quality.
    """

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class LLMClient(Protocol):
    """The one interface the harness drives.

    ``trial`` distinguishes repeated calls on the same prompt so a client can vary
    per-call latency across trials (the source of the sampled distribution) while
    staying reproducible.
    """

    def complete(self, prompt: Prompt, *, model: ModelSpec, trial: int) -> Completion:
        ...


def _seeded_rng(*parts: object) -> random.Random:
    """A ``random.Random`` seeded from a stable SHA-256 of ``parts``.

    Uses a content hash rather than ``hash()`` so the seed — and therefore every
    sampled latency — is identical across processes regardless of ``PYTHONHASHSEED``.
    """
    key = "|".join(str(p) for p in parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return random.Random(seed)


@dataclass(frozen=True)
class SimulatedClient:
    """Offline ``LLMClient``: exact token cost, modeled latency, fully deterministic.

    ``seed`` anchors the whole run; per-call jitter is derived from it together with
    the model name, prompt id, and trial index, so a given ``(seed, corpus)`` always
    produces the same measurements.
    """

    seed: int = 42

    def complete(self, prompt: Prompt, *, model: ModelSpec, trial: int) -> Completion:
        input_tokens = estimate_tokens(prompt.text)
        output_tokens = prompt.expected_output_tokens
        base = model.expected_latency_ms(input_tokens, output_tokens)
        # Lognormal multiplicative jitter: always positive, right-skewed, centred
        # near 1.0, so the sampled distribution has a realistic tail (p95 > p50).
        rng = _seeded_rng(self.seed, model.name, prompt.id, trial)
        jitter = math.exp(rng.gauss(0.0, model.latency_sigma))
        return Completion(
            model=model.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=base * jitter,
        )


__all__ = ["Completion", "LLMClient", "SimulatedClient"]
