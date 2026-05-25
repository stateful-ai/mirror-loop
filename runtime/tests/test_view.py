"""The ``WorldView`` data contract — what counts as empty, and immutability."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.view import DEFAULT_TITLE, WorldView, empty_world


def test_empty_world_has_a_title_and_no_scene():
    world = empty_world()
    assert world.title == DEFAULT_TITLE
    assert world.is_empty
    assert world.prompt is None
    assert world.choices == ()


def test_empty_world_title_is_overridable():
    assert empty_world(title="Mirror Lab").title == "Mirror Lab"


def test_a_prompt_or_choices_make_a_world_non_empty():
    assert not WorldView(prompt="Choose.").is_empty
    assert not WorldView(choices=("stay", "go")).is_empty


def test_status_alone_does_not_make_a_world_non_empty():
    # Status is chrome (a footer), not scene content; an otherwise-blank frame
    # with only a status line is still an empty world.
    assert WorldView(status="turn 0").is_empty


def test_world_view_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        empty_world().title = "mutated"  # type: ignore[misc]
