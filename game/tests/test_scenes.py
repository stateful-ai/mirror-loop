"""The handcrafted scene authoring format: parser, loader, and round-trip.

Pins the contract documented in ``docs/SCENE_FORMAT.md``:

* the shipped worked example (``game/scenes/data/intake.scene``) parses into a
  ``Scene`` byte-equivalent to the in-code authoring (``game.world.INTAKE``),
* every error case the spec promises raises ``SceneFormatError`` with a precise
  line number, and
* the format admits no code-in-data path (the loader has no eval/exec/import
  call site, and even a file whose values contain Python source is treated as
  inert text).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from game.scenes import SceneFormatError, load_scene, loads_scene
from game.world import INTAKE
from loop.core import Choice, Scene

EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "scenes" / "data" / "intake.scene"
)


# --- The worked example -----------------------------------------------------


def test_shipped_example_parses_into_a_scene():
    scene = load_scene(EXAMPLE_PATH)
    assert isinstance(scene, Scene)
    assert scene.id == "intake"
    assert len(scene.choices) == 3


def test_shipped_example_is_byte_equivalent_to_world_intake():
    # The .scene file and the in-code INTAKE are two authorings of the same
    # scene; they must produce identical Scene objects so the runtime cannot
    # tell which one it loaded.
    assert load_scene(EXAMPLE_PATH) == INTAKE


def test_shipped_example_uses_the_v0_tendency_vocabulary():
    scene = load_scene(EXAMPLE_PATH)
    assert {c.tendency for c in scene.choices} == {"kindness", "control", "defiance"}


def test_choices_preserve_declared_order():
    scene = load_scene(EXAMPLE_PATH)
    assert tuple(c.id for c in scene.choices) == ("c_reassure", "c_measure", "c_refuse")


# --- Format mechanics: comments, blanks, indentation, folding ---------------


def test_full_line_comments_and_blank_lines_are_ignored():
    src = dedent(
        """\
        # leading comment
        id: hello

        # comment between sections
        prompt:
          A short line.

        # comment between choices
        choice c_one:
          tendency: kindness
          text: Nod.
          evidence: nodded politely
        """
    )
    scene = loads_scene(src)
    assert scene.id == "hello"
    assert scene.prompt == "A short line."


def test_prompt_lines_fold_with_single_spaces():
    src = dedent(
        """\
        id: s
        prompt:
          one
          two
          three
        choice c:
          tendency: kindness
          text: x
          evidence: y
        """
    )
    assert loads_scene(src).prompt == "one two three"


def test_prompt_blank_line_is_a_paragraph_break():
    src = dedent(
        """\
        id: s
        prompt:
          first paragraph
          continued

          second paragraph
        choice c:
          tendency: kindness
          text: x
          evidence: y
        """
    )
    assert loads_scene(src).prompt == "first paragraph continued\n\nsecond paragraph"


def test_prompt_inline_comment_does_not_break_paragraphs():
    # A two-space-indented comment inside the prompt is an author note, not a
    # paragraph break; the surrounding text must still fold into one line.
    src = dedent(
        """\
        id: s
        prompt:
          one
          # author note about the next line
          two
        choice c:
          tendency: kindness
          text: x
          evidence: y
        """
    )
    assert loads_scene(src).prompt == "one two"


def test_choice_fields_may_appear_in_any_order():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          evidence: did the thing
          text: Do the thing.
          tendency: control
        """
    )
    [choice] = loads_scene(s := src).choices
    assert choice == Choice(
        id="c",
        text="Do the thing.",
        tendency="control",
        evidence="did the thing",
    )


def test_value_with_internal_colon_is_preserved():
    # The split is at the *first* `:`; everything after it (stripped) is the
    # value. This matters because prompts and choice text routinely contain
    # punctuation, including colons.
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: She said: take your time.
          evidence: reassured: gently
        """
    )
    [choice] = loads_scene(src).choices
    assert choice.text == "She said: take your time."
    assert choice.evidence == "reassured: gently"


def test_loads_and_load_agree_on_the_example():
    text = EXAMPLE_PATH.read_text(encoding="utf-8")
    assert loads_scene(text) == load_scene(EXAMPLE_PATH)


# --- Error cases (spec §5) --------------------------------------------------


def _assert_format_error(src: str, *, lineno: int, contains: str) -> None:
    with pytest.raises(SceneFormatError) as ei:
        loads_scene(src)
    assert ei.value.lineno == lineno, (ei.value, ei.value.lineno)
    assert contains in str(ei.value), str(ei.value)


def test_empty_file_is_rejected():
    _assert_format_error("", lineno=1, contains="file is empty")


def test_missing_id_is_rejected():
    src = "prompt:\n  hi\nchoice c:\n  tendency: kindness\n  text: x\n  evidence: y\n"
    _assert_format_error(src, lineno=1, contains="expected `id:`")


def test_missing_prompt_is_rejected():
    src = "id: s\nchoice c:\n  tendency: kindness\n  text: x\n  evidence: y\n"
    _assert_format_error(src, lineno=2, contains="`prompt:` header")


def test_prompt_with_no_indented_text_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
        choice c:
          tendency: kindness
          text: x
          evidence: y
        """
    )
    _assert_format_error(src, lineno=2, contains="at least one indented text line")


def test_no_choices_is_rejected():
    src = "id: s\nprompt:\n  P\n"
    with pytest.raises(SceneFormatError, match="at least one `choice"):
        loads_scene(src)


def test_unknown_choice_field_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: x
          evidence: y
          mood: brooding
        """
    )
    _assert_format_error(src, lineno=8, contains="unknown choice field `mood`")


def test_duplicate_choice_field_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: x
          text: y
          evidence: e
        """
    )
    _assert_format_error(src, lineno=7, contains="duplicate field `text`")


def test_missing_choice_field_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: x
        """
    )
    _assert_format_error(src, lineno=4, contains="missing required field(s)")


def test_duplicate_choice_id_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: x
          evidence: y
        choice c:
          tendency: control
          text: z
          evidence: w
        """
    )
    _assert_format_error(src, lineno=8, contains="duplicate choice id `c`")


def test_empty_value_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency:
          text: x
          evidence: y
        """
    )
    _assert_format_error(src, lineno=5, contains="empty value")


def test_tab_in_value_is_rejected():
    # The `:` is followed by a literal tab character then text. Tabs in values
    # are rejected so indentation behavior cannot drift on a contributor's
    # editor setting.
    src = "id: s\nprompt:\n  P\nchoice c:\n  tendency:\tkindness\n  text: x\n  evidence: y\n"
    _assert_format_error(src, lineno=5, contains="tabs are not allowed")


def test_non_identifier_scene_id_is_rejected():
    src = "id: 1bad\nprompt:\n  P\nchoice c:\n  tendency: k\n  text: x\n  evidence: y\n"
    _assert_format_error(src, lineno=1, contains="must start with a letter or underscore")


def test_non_identifier_choice_id_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice 1c:
          tendency: kindness
          text: x
          evidence: y
        """
    )
    _assert_format_error(src, lineno=4, contains="must start with a letter or underscore")


def test_trailing_garbage_after_last_choice_is_rejected():
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: x
          evidence: y
        garbage at the end
        """
    )
    _assert_format_error(src, lineno=8, contains="unexpected line at top level")


def test_unexpected_top_level_keyword_is_rejected():
    # A line that looks like a field but isn't a recognized top-level section
    # is reported clearly rather than silently absorbed.
    src = dedent(
        """\
        id: s
        prompt:
          P
        mood: brooding
        """
    )
    _assert_format_error(src, lineno=4, contains="unexpected line at top level")


# --- No-code-in-data --------------------------------------------------------


def test_loader_module_has_no_dynamic_code_execution_callsites():
    # Defense-in-depth pin: any future change that smuggles eval/exec/import
    # into the loader fails this test loudly. Comments/docstrings reference
    # these names; only call-site usage should fail us, so we scan for the
    # call form specifically.
    source = (
        Path(__file__).resolve().parents[1] / "scenes" / "loader.py"
    ).read_text(encoding="utf-8")
    for callsite in ("eval(", "exec(", "compile(", "__import__("):
        assert callsite not in source, (
            f"loader.py must not contain a {callsite} call — no code-in-data"
        )


def test_value_that_looks_like_python_is_treated_as_inert_text():
    # A choice whose `text` is literal Python source must come back as a
    # plain string, not be evaluated. (This is what the loader's behavior
    # already guarantees, but pinning it here turns "no code-in-data" into
    # an executable claim, not a comment.)
    src = dedent(
        """\
        id: s
        prompt:
          P
        choice c:
          tendency: kindness
          text: __import__('os').system('echo pwned')
          evidence: said something that looks like code
        """
    )
    [choice] = loads_scene(src).choices
    assert choice.text == "__import__('os').system('echo pwned')"
    assert isinstance(choice.text, str)
