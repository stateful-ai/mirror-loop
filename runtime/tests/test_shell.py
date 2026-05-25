"""The thin shell and the ``python -m runtime`` entrypoint.

The acceptance bar for this scaffold: the minimal skeleton boots and renders an
*empty world* — through the injected interface, with the default terminal
platform, and as an actual ``python -m runtime`` process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from runtime.__main__ import main
from runtime.render import RecordingRenderer
from runtime.shell import boot
from runtime.view import EMPTY_WORLD_NOTICE, WorldView, empty_world

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_boot_renders_exactly_one_empty_world_through_the_interface():
    recorder = RecordingRenderer()

    returned = boot(renderer=recorder)

    # One frame, it is the empty world, and the shell reports back what it showed.
    assert recorder.frames == [empty_world()]
    assert recorder.frames[0].is_empty
    assert returned == empty_world()


def test_boot_renders_a_supplied_world():
    recorder = RecordingRenderer()
    scene = WorldView(prompt="Choose.", choices=("a", "b"))

    boot(renderer=recorder, world=scene)

    assert recorder.frames == [scene]


def test_boot_defaults_to_the_terminal_platform(capsys):
    # No renderer injected: the shipped default (terminal) must draw the empty
    # world to stdout — the real boot path a founder hits.
    boot()
    assert EMPTY_WORLD_NOTICE in capsys.readouterr().out


def test_main_boots_and_renders_empty_world(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out == f"=== Mirror Loop ===\n\n{EMPTY_WORLD_NOTICE}\n"


def test_main_title_flag_sets_the_header(capsys):
    assert main(["--title", "Mirror Lab"]) == 0
    assert capsys.readouterr().out.startswith("=== Mirror Lab ===")


def test_python_dash_m_runtime_boots_a_real_process():
    # Prove the skeleton boots as an actual entrypoint, not just via import.
    result = subprocess.run(
        [sys.executable, "-m", "runtime"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert EMPTY_WORLD_NOTICE in result.stdout
