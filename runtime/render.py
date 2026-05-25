"""The one rendering interface, and the implementations that sit behind it.

This is the seam the runtime/platform decision turns on
(``docs/adr/0002-runtime-platform.md``): every player-facing frame goes through
:class:`Renderer`, so the rest of the system depends on the *interface* and never
on a concrete output device. Choosing the terminal for M1 is therefore cheap to
undo — a browser or API front-end is later "just another ``Renderer``", and the
core never learns which one is attached.

Two implementations ship:

* :class:`TerminalRenderer` — the M1 production renderer; writes a deterministic
  text frame to an injected stream (default ``stdout``). A captured stream makes
  its output trivially assertable, which is what keeps it compatible with the
  byte-identity replay gate (``docs/THESIS.md`` §2).
* :class:`RecordingRenderer` — captures the ``WorldView`` frames it is handed
  instead of drawing them. It exists so the seam is *demonstrably* swappable
  rather than theoretical, and so tests can inspect what would be shown without a
  console.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Protocol, TextIO, runtime_checkable

from runtime.view import EMPTY_WORLD_NOTICE, WorldView


@runtime_checkable
class Renderer(Protocol):
    """The single interface all player-facing output flows through.

    An implementation turns a :class:`~runtime.view.WorldView` into output on some
    platform. That is the whole contract — one method, no state assumptions — so a
    new platform is additive (implement this, swap it in at
    :func:`runtime.shell.boot`) and the engine stays unaware of the device.
    """

    def render(self, view: WorldView) -> None:
        """Present one frame. Implementations must not mutate ``view``."""
        ...


class TerminalRenderer:
    """Render a :class:`WorldView` as a plain text frame on a stream.

    The format is deterministic and stdlib-only (no escape codes, no dependency):
    a titled header, then either the empty-world notice or the scene's prompt and
    numbered choices, then an optional status line. ``stream`` is injected so the
    same renderer drives a real console (default ``stdout``) or a ``StringIO`` in
    tests.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    def render(self, view: WorldView) -> None:
        lines = [f"=== {view.title} ==="]
        if view.is_empty:
            lines.append("")
            lines.append(EMPTY_WORLD_NOTICE)
        else:
            if view.prompt is not None:
                lines.append("")
                lines.append(view.prompt)
            if view.choices:
                lines.append("")
                lines.extend(
                    f"  {n}. {choice}" for n, choice in enumerate(view.choices, start=1)
                )
        if view.status is not None:
            lines.append("")
            lines.append(view.status)
        self._stream.write("\n".join(lines) + "\n")


@dataclass
class RecordingRenderer:
    """A :class:`Renderer` that records frames instead of drawing them.

    Every :meth:`render` appends the view to :attr:`frames`, in order, so callers
    and tests can assert on exactly what the runtime would have shown.
    """

    frames: list[WorldView] = field(default_factory=list)

    def render(self, view: WorldView) -> None:
        self.frames.append(view)
