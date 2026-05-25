"""The render-agnostic snapshot of what the player should see this frame.

``WorldView`` is the data contract between the engine and a :class:`Renderer`
(``runtime/render.py``). The engine *produces* a ``WorldView``; it never formats
output itself. A renderer *consumes* one and is the only code that turns it into
characters, pixels, or anything else. Keeping this boundary plain data is what
makes the platform choice reversible (see ``docs/adr/0002-runtime-platform.md``):
swapping the terminal for a browser later changes the renderer, never the view.

The view is deliberately minimal for the M1 skeleton — enough to render an *empty
world* (no scene loaded yet) and the obvious next shape (a prompt with choices)
without committing the engine to anything it hasn't built.
"""

from __future__ import annotations

from dataclasses import dataclass

# What the terminal shows for a world with no scene loaded. Kept here, next to the
# view it describes, so renderers and tests share one source of truth for the
# "nothing to play yet" frame rather than each spelling it out. Deliberately
# ASCII-only: this string is written straight to the output stream, so a non-ASCII
# character (e.g. an em dash) would make boot raise UnicodeEncodeError under an
# ASCII locale such as ``PYTHONIOENCODING=ascii``.
EMPTY_WORLD_NOTICE = "(empty world - no scene loaded)"

DEFAULT_TITLE = "Mirror Loop"


@dataclass(frozen=True)
class WorldView:
    """An immutable, render-agnostic description of one frame.

    ``title`` always shows. ``prompt`` and ``choices`` are the scene content; when
    both are absent the world is :attr:`is_empty` and a renderer shows the
    empty-world notice instead. ``status`` is optional chrome (e.g. a footer) and
    does not, on its own, make a world non-empty.
    """

    title: str = DEFAULT_TITLE
    prompt: str | None = None
    choices: tuple[str, ...] = ()
    status: str | None = None

    @property
    def is_empty(self) -> bool:
        """True when there is no scene to play yet (no prompt and no choices)."""
        return self.prompt is None and not self.choices


def empty_world(title: str = DEFAULT_TITLE) -> WorldView:
    """The world the skeleton boots into: a title and nothing to play yet.

    This is the M1 acceptance target for the runtime scaffold — proof that the
    boot path and the render seam work end to end before any scene, reducer, or
    adaptation exists to fill the frame.
    """
    return WorldView(title=title)
