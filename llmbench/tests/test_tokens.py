"""The deterministic token estimator."""

from __future__ import annotations

from llmbench.tokens import CHARS_PER_TOKEN, estimate_tokens


def test_empty_text_is_zero_tokens():
    assert estimate_tokens("") == 0


def test_estimate_is_deterministic():
    text = "The Mirror dims the lights to a kinder warmth."
    assert estimate_tokens(text) == estimate_tokens(text)


def test_estimate_is_monotonic_in_length():
    short = estimate_tokens("a short prompt")
    long = estimate_tokens("a short prompt" + " with several more words appended here")
    assert long > short


def test_chars_per_token_heuristic():
    # 40 non-space chars / 4 = 10, and the one-word floor (1) does not raise it.
    assert estimate_tokens("x" * 40) == 40 // CHARS_PER_TOKEN


def test_word_floor_beats_char_estimate_for_spaced_short_words():
    # Eight single-letter words: char estimate ceil(15/4)=4, but eight words is a
    # higher, more honest lower bound — the floor wins.
    text = "a b c d e f g h"
    assert estimate_tokens(text) == 8
