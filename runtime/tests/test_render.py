"""The rendering interface and its two shipped implementations.

These tests pin the seam the platform decision turns on: that there is *one*
``Renderer`` interface, that the terminal implementation draws a deterministic,
captured-stream-friendly frame, and that a second implementation can stand in
without the rest of the system noticing.
"""

from __future__ import annotations

import io

from runtime.render import RecordingRenderer, Renderer, TerminalRenderer
from runtime.view import EMPTY_WORLD_NOTICE, WorldView, empty_world


def test_both_implementations_satisfy_the_one_interface():
    # The seam is real: every shipped renderer is a Renderer, so any of them can
    # be the one swapped in at boot.
    assert isinstance(TerminalRenderer(io.StringIO()), Renderer)
    assert isinstance(RecordingRenderer(), Renderer)


def test_terminal_renders_the_empty_world_frame():
    out = io.StringIO()
    TerminalRenderer(out).render(empty_world(title="Mirror Lab"))

    text = out.getvalue()
    assert text == f"=== Mirror Lab ===\n\n{EMPTY_WORLD_NOTICE}\n"


def test_terminal_renders_a_scene_with_numbered_choices():
    out = io.StringIO()
    view = WorldView(
        title="Mirror Lab",
        prompt="A technician fits the headset.",
        choices=("Reassure her.", "Ask what it measures.", "Refuse it."),
        status="turn 1",
    )
    TerminalRenderer(out).render(view)

    assert out.getvalue() == (
        "=== Mirror Lab ===\n"
        "\n"
        "A technician fits the headset.\n"
        "\n"
        "  1. Reassure her.\n"
        "  2. Ask what it measures.\n"
        "  3. Refuse it.\n"
        "\n"
        "turn 1\n"
    )


def test_terminal_render_is_deterministic():
    # Same view in, byte-identical frame out — the property the replay gate needs.
    view = WorldView(prompt="Choose.", choices=("a", "b"))
    first, second = io.StringIO(), io.StringIO()
    TerminalRenderer(first).render(view)
    TerminalRenderer(second).render(view)
    assert first.getvalue() == second.getvalue()


def test_terminal_defaults_to_stdout(capsys):
    TerminalRenderer().render(empty_world())
    assert EMPTY_WORLD_NOTICE in capsys.readouterr().out


def test_recording_renderer_captures_frames_in_order():
    recorder = RecordingRenderer()
    first, second = empty_world(), WorldView(prompt="next")

    recorder.render(first)
    recorder.render(second)

    assert recorder.frames == [first, second]
