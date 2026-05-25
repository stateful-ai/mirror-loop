"""The measurement seam: an ``LLMClient`` protocol with offline and live clients.

The harness times and prices calls through one narrow interface, :class:`LLMClient`,
so the *same* harness can drive either the offline :class:`SimulatedClient` (default)
or the networked :class:`LiveClient`, which sets ``latency_ms`` from a measured wall
clock and the token counts from the provider's reported usage. Keeping both behind
one protocol is the same "interchangeable implementations behind one contract"
pattern the rest of the project uses for rendering and adaptation (``docs/adr/0002``
rationale #4; company principle on the content-adapter contract).

Each client reports a :attr:`latency_kind` so the harness never has to *guess*
whether a run's latency is measured or modeled — it propagates that fact into the
report instead of letting a modeled number masquerade as an observation.

:class:`SimulatedClient` is what makes the harness an **offline** instrument, and
it is the default precisely because the prototype is stdlib-only, offline, and
deterministic in CI (``docs/adr/0002``):

* **Token counts** come from the real prompt text via :func:`llmbench.tokens.estimate_tokens`
  (input) and the task's output budget (output), so **cost is computed from real
  prompts**, exactly.
* **Latency** is *modeled*: drawn from the model's analytic profile
  (``llmbench.models``) scaled by a per-call lognormal jitter, so a run yields a
  realistic distribution. The randomness is seeded from a SHA-256 of
  ``(seed, model, prompt id, trial)`` — never Python's hash-randomized ``hash()`` —
  so results are byte-stable across processes and ``PYTHONHASHSEED`` values,
  matching the determinism rigor the rest of the repo enforces
  (``game/tests/test_instrumentation.py``). The simulator never sleeps; it
  *computes* the modeled latency, so a full sweep is instant and CI-friendly.

:class:`LiveClient` is the **live latency spike** the go/no-go calls for, made a
runnable command rather than deferred future work: with ``ANTHROPIC_API_KEY`` set,
``python -m llmbench --live`` drives the very same sweep against the real endpoint
and reports *measured* wall-clock latency and provider-reported token usage. It is
opt-in only — it needs network + credentials the prototype deliberately does not
take on by default — and is never imported by the loop (pinned by
``tests/test_not_wired_into_loop.py``) nor exercised in CI. It uses only stdlib
``urllib`` so it adds no dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

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
    staying reproducible. ``latency_kind`` is ``"measured"`` for clients that time a
    real wall clock and ``"modeled"`` for the offline simulator, so the harness can
    label a report honestly without inspecting the client's type.
    """

    #: "measured" (real wall clock) | "modeled" (analytic profile).
    latency_kind: str

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

    #: This client *models* latency; it does not observe a real wall clock. A plain
    #: class attribute (not a dataclass field), so it never affects ``(seed)`` equality.
    latency_kind = "modeled"

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


#: A transport maps a request (url, payload bytes, headers) to a parsed JSON dict.
#: The default hits the network with ``urllib``; tests inject a fake to exercise
#: request building and response parsing offline.
Transport = Callable[[str, bytes, dict], dict]


def _urlopen_json(url: str, payload: bytes, headers: dict, *, timeout: float) -> dict:
    """POST ``payload`` to ``url`` and parse the JSON response (stdlib only)."""
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class LiveClient:
    """Networked ``LLMClient``: **measured** wall-clock latency, exact token usage.

    This is the live latency spike the go/no-go names, as a runnable instrument: it
    implements the same protocol as :class:`SimulatedClient`, so the harness sweep,
    report shape, and cost arithmetic are identical — only ``latency_ms`` becomes an
    observation (``time.perf_counter`` around the call) and the token counts come
    from the provider's reported ``usage`` instead of the offline estimate.

    Opt-in only. It needs network and an API key the prototype does not depend on by
    default (``docs/adr/0002``), is never imported by the loop, and is never run in
    CI. Latency from a real endpoint is not reproducible, so a live run is *not*
    deterministic — that is the point; it is the ground truth the modeled profile is
    meant to be confirmed against.

    ``transport`` and ``clock`` are injected so the request/response mapping and the
    latency timing are unit-testable without a network (see ``tests/test_client.py``).
    """

    api_key: str
    endpoint: str = "https://api.anthropic.com/v1/messages"
    api_version: str = "2023-06-01"
    timeout_s: float = 60.0
    transport: Optional[Transport] = None
    clock: Callable[[], float] = time.perf_counter

    #: This client *measures* latency from a real wall clock.
    latency_kind = "measured"

    def complete(self, prompt: Prompt, *, model: ModelSpec, trial: int) -> Completion:
        payload = json.dumps(
            {
                "model": model.name,
                "max_tokens": prompt.expected_output_tokens,
                "system": prompt.system,
                "messages": [{"role": "user", "content": prompt.user}],
            }
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
        }
        transport = self.transport or (
            lambda url, body, hdrs: _urlopen_json(
                url, body, hdrs, timeout=self.timeout_s
            )
        )
        start = self.clock()
        response = transport(self.endpoint, payload, headers)
        latency_ms = (self.clock() - start) * 1000.0
        usage = response["usage"]
        return Completion(
            model=model.name,
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            latency_ms=latency_ms,
        )


__all__ = ["Completion", "LLMClient", "LiveClient", "SimulatedClient", "Transport"]
