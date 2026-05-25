"""The corpus is built from real shipped world content, not filler."""

from __future__ import annotations

import pytest

from game.world import DEFAULT_WORLD
from llmbench.prompts import (
    INSERTION_POINTS,
    PERSONAS,
    InsertionPoint,
    build_corpus,
)
from llmbench.tokens import estimate_tokens


def test_corpus_has_both_insertion_points():
    corpus = build_corpus()
    assert set(corpus) == set(InsertionPoint)
    assert all(corpus[p] for p in InsertionPoint)


def test_corpus_sizes_are_grounded_in_the_world():
    corpus = build_corpus()
    n_personas = len(PERSONAS)
    branch_slots = sum(1 for s in DEFAULT_WORLD.slots if s.variants is not None)
    # NPC reply fires every loop; branch candidate only at branch slots.
    assert len(corpus[InsertionPoint.NPC_REPLY]) == n_personas * DEFAULT_WORLD.length
    assert len(corpus[InsertionPoint.BRANCH_CANDIDATE]) == n_personas * branch_slots


def test_npc_prompt_embeds_real_scene_and_choice_text():
    corpus = build_corpus()
    # The kind player's first loop is the intake scene; its real prose and the
    # real kindness choice text must appear verbatim in the prompt.
    intake = next(
        p
        for p in corpus[InsertionPoint.NPC_REPLY]
        if p.id == "npc_reply:kind:intake:0"
    )
    assert "her hands are shaking" in intake.user  # real intake prose
    assert "Tell her to take her time" in intake.user  # real c_reassure text
    assert "no choices yet" in intake.user  # loop 0 has an empty tally


def test_branch_prompt_reflects_the_selected_framing_and_dominant_tendency():
    corpus = build_corpus()
    # By the exit slot a consistent control player is dominant 'control', so the
    # exit branch prompt must name that lean and carry the real choice spine.
    exit_prompt = next(
        p
        for p in corpus[InsertionPoint.BRANCH_CANDIDATE]
        if p.id == "branch_candidate:control:exit:4"
    )
    assert "Dominant tendency: control" in exit_prompt.user
    assert "Demand to read the model the Mirror built of you" in exit_prompt.user
    # The neutral framing is offered as the reference to reframe from.
    assert "calibrated to no one in particular" in exit_prompt.user


def test_branch_prompts_only_at_branch_slots():
    corpus = build_corpus()
    fixed_keys = {s.key for s in DEFAULT_WORLD.slots if s.variants is None}
    for prompt in corpus[InsertionPoint.BRANCH_CANDIDATE]:
        slot_key = prompt.id.split(":")[2]
        assert slot_key not in fixed_keys


def test_every_prompt_has_real_input_tokens_and_an_output_budget():
    corpus = build_corpus()
    for point, prompts in corpus.items():
        budget = INSERTION_POINTS[point].expected_output_tokens
        for prompt in prompts:
            assert estimate_tokens(prompt.text) > 0
            assert prompt.expected_output_tokens == budget


def test_prompts_carry_the_safety_contract():
    # A realistic prompt already constrains the model the way the loop would have
    # to: in-game behavior only, never remove a door, never rewrite the engine.
    corpus = build_corpus()
    npc = corpus[InsertionPoint.NPC_REPLY][0]
    assert "ONLY behavior observed" in npc.system
    branch = corpus[InsertionPoint.BRANCH_CANDIDATE][0]
    assert "never remove a door" in branch.system
    assert "never alter the engine" in branch.system


def test_npc_prompts_have_distinct_ids():
    corpus = build_corpus()
    ids = [p.id for p in corpus[InsertionPoint.NPC_REPLY]]
    assert len(ids) == len(set(ids))


def test_persona_length_mismatch_is_rejected():
    with pytest.raises(ValueError, match="slots"):
        build_corpus(personas={"short": ("c_reassure",)})
