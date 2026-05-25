"""A dependency-free, deterministic token estimator.

Cost is a function of token counts, so the harness needs to count tokens — but the
repo is stdlib-only (no ``tiktoken``/tokenizer dependency, ``docs/adr/0002`` "no
dependencies"). This module provides a small, **deterministic** estimator instead:
a documented heuristic, not the model's real tokenizer.

The heuristic is the well-worn ``~4 characters per token`` rule for English prose,
floored at the word count (a token is rarely longer than a word, so word count is
a lower bound). It is consistent and side-effect-free, which is what the harness
needs to compare candidates and compute per-session cost reproducibly. It is
**not** exact billing: real tokenizers vary by a rough ±15-20% on natural-language
prompts, more on JSON/punctuation-heavy text. The go/no-go writeup
(``docs/LLM_COST_LATENCY.md``) calls this out, and a live spike that reports the
provider's reported ``usage`` is the way to pin exact dollars.
"""

from __future__ import annotations

import math

#: The chars-per-token divisor for the prose heuristic. The single tuning knob; a
#: real tokenizer is the way to remove the approximation entirely.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (deterministic, no dependency).

    ``ceil(len(text) / CHARS_PER_TOKEN)``, floored at the whitespace-word count so
    short, spaced text is never under-counted. Empty text is zero tokens.
    """
    if not text:
        return 0
    char_estimate = math.ceil(len(text) / CHARS_PER_TOKEN)
    word_floor = len(text.split())
    return max(char_estimate, word_floor)


__all__ = ["CHARS_PER_TOKEN", "estimate_tokens"]
