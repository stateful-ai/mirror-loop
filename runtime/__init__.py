"""The runtime/platform shell for Mirror Loop.

A deliberately thin layer that boots the prototype and renders frames through one
interface. The platform decision (terminal for M1, reversible by design) is
recorded in ``docs/adr/0002-runtime-platform.md``.

Public surface:

* :class:`WorldView` / :func:`empty_world` — the render-agnostic frame the engine
  produces.
* :class:`Renderer` — the one interface all output flows through; with the shipped
  :class:`TerminalRenderer` and :class:`RecordingRenderer` implementations.
* :func:`boot` — the thin shell; ``boot()`` renders an empty world to the terminal.

Run the skeleton with ``python -m runtime``.
"""

from __future__ import annotations

from runtime.render import RecordingRenderer, Renderer, TerminalRenderer
from runtime.shell import boot
from runtime.view import EMPTY_WORLD_NOTICE, WorldView, empty_world

__all__ = [
    "WorldView",
    "empty_world",
    "EMPTY_WORLD_NOTICE",
    "Renderer",
    "TerminalRenderer",
    "RecordingRenderer",
    "boot",
]
