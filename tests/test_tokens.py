"""Pinned-behavior tests for :mod:`llmbench.tokens`.

These complement the in-package suite (``llmbench/tests/test_tokens.py``) by
asserting the exact, documented shape of the heuristic from the repo-root
tests/: the chars-per-token divisor, the empty-string base case, and the
word-count floor that protects whitespace-heavy prompts from being
under-counted.
"""

from __future__ import annotations

from llmbench.tokens import CHARS_PER_TOKEN, estimate_tokens


def test_empty_string_is_zero_tokens():
    assert estimate_tokens("") == 0


def test_short_text_returns_at_least_word_count():
    # 'hi there' is 8 chars (ceil(8/4)=2) and 2 words; either way the answer
    # must be >= the word count.
    assert estimate_tokens("hi there") >= 2


def test_long_prose_uses_char_estimate():
    # 100 single chars / 4 chars-per-token = 25, and the one-word floor (1)
    # does not raise it.
    assert estimate_tokens("a" * 100) == 25


def test_whitespace_heavy_prompt_uses_word_floor():
    # ceil(7 / 4) = 2 char-estimate tokens, but the prompt is four words long;
    # the floor must win so spaced prompts are not under-counted.
    text = "a b c d"
    assert estimate_tokens(text) == 4


def test_chars_per_token_constant_is_four():
    assert CHARS_PER_TOKEN == 4
