"""The simulated client: deterministic, exact cost, realistic latency spread."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llmbench.client import Completion, SimulatedClient
from llmbench.models import HAIKU, OPUS
from llmbench.prompts import InsertionPoint, build_corpus
from llmbench.tokens import estimate_tokens

REPO_ROOT = Path(__file__).resolve().parents[2]


def _a_prompt():
    return build_corpus()[InsertionPoint.NPC_REPLY][0]


def test_same_seed_and_trial_is_byte_identical():
    prompt = _a_prompt()
    a = SimulatedClient(seed=42).complete(prompt, model=HAIKU, trial=0)
    b = SimulatedClient(seed=42).complete(prompt, model=HAIKU, trial=0)
    assert a == b


def test_token_counts_match_the_estimator_and_budget():
    prompt = _a_prompt()
    c = SimulatedClient().complete(prompt, model=HAIKU, trial=0)
    assert c.input_tokens == estimate_tokens(prompt.text)
    assert c.output_tokens == prompt.expected_output_tokens


def test_different_trials_vary_latency_but_not_tokens():
    prompt = _a_prompt()
    client = SimulatedClient(seed=1)
    samples = [client.complete(prompt, model=HAIKU, trial=t) for t in range(20)]
    latencies = {s.latency_ms for s in samples}
    assert len(latencies) > 1  # jitter produces a spread
    # Tokens (and therefore cost) are fixed across trials.
    assert {s.input_tokens for s in samples} == {samples[0].input_tokens}
    assert {s.output_tokens for s in samples} == {prompt.expected_output_tokens}


def test_latency_centres_on_the_model_profile():
    # Averaging many lognormal-jittered draws recovers a value near the profile
    # median, and a slower model is slower on the same prompt.
    prompt = _a_prompt()
    client = SimulatedClient(seed=7)
    n = 2000
    haiku = [client.complete(prompt, model=HAIKU, trial=t).latency_ms for t in range(n)]
    opus = [client.complete(prompt, model=OPUS, trial=t).latency_ms for t in range(n)]
    in_tok = estimate_tokens(prompt.text)
    centre = HAIKU.expected_latency_ms(in_tok, prompt.expected_output_tokens)
    # The mean of a lognormal jitter is exp(sigma^2/2)·centre, not centre, so
    # compare against that analytic mean rather than the median.
    import math

    haiku_mean_factor = math.exp(HAIKU.latency_sigma**2 / 2)
    assert sum(haiku) / n == pytest.approx(centre * haiku_mean_factor, rel=0.05)
    assert sum(opus) / n > sum(haiku) / n


def test_seed_changes_the_jitter():
    prompt = _a_prompt()
    a = SimulatedClient(seed=1).complete(prompt, model=HAIKU, trial=0).latency_ms
    b = SimulatedClient(seed=2).complete(prompt, model=HAIKU, trial=0).latency_ms
    assert a != b


def test_completion_is_a_frozen_record():
    c = Completion(model="m", input_tokens=10, output_tokens=20, latency_ms=1.0)
    assert dataclasses.is_dataclass(c)
    try:
        c.latency_ms = 2.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - defends the frozen contract
        raise AssertionError("Completion must be frozen")


def test_latency_is_independent_of_pythonhashseed():
    # The strongest determinism form: two processes with different PYTHONHASHSEED
    # must produce the same sampled latency, proving the SHA-256 seeding never
    # leans on Python's hash randomisation.
    def emit(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        code = (
            "from llmbench.client import SimulatedClient;"
            "from llmbench.models import HAIKU;"
            "from llmbench.prompts import InsertionPoint, build_corpus;"
            "p=build_corpus()[InsertionPoint.NPC_REPLY][0];"
            "print(SimulatedClient(seed=42).complete(p, model=HAIKU, trial=3).latency_ms)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    assert emit("0") == emit("1")
