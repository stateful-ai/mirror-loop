"""The thin runtime shell: wire a world to a renderer, render it, return.

This is the "thin shell" the company principle calls for — the only place output
happens. It owns no game logic: it constructs (or accepts) a
:class:`~runtime.view.WorldView`, hands it to a :class:`~runtime.render.Renderer`,
and gets out of the way. Both collaborators are injectable so the shell is fully
testable without a console, and so a future platform swaps in at exactly one seam.
"""

from __future__ import annotations

from runtime.render import Renderer, TerminalRenderer
from runtime.view import WorldView, empty_world


def boot(renderer: Renderer | None = None, world: WorldView | None = None) -> WorldView:
    """Boot the runtime and render one world frame.

    Defaults to the M1 platform — a :class:`TerminalRenderer` — and the *empty
    world*, so ``boot()`` with no arguments is the minimal skeleton: it boots and
    renders an empty world. Pass a ``renderer`` to target another platform or to
    capture frames in tests; pass a ``world`` to render a specific frame. Returns
    the rendered view so callers can assert on what was shown.
    """
    active_renderer = renderer if renderer is not None else TerminalRenderer()
    active_world = world if world is not None else empty_world()
    active_renderer.render(active_world)
    return active_world
