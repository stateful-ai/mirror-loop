"""Handcrafted scene authoring format and loader.

A scene is the smallest authored unit of the handcrafted world (a prompt and the
choices it offers; see ``loop.core.Scene``). This package lets a designer write
scenes as **text data files** — never Python code — and load them into the same
typed objects the runtime already speaks. The format and the loader contract are
documented in ``docs/SCENE_FORMAT.md``.

The public surface is intentionally tiny:

* :func:`load_scene` — parse a ``.scene`` file path into a typed ``Scene``.
* :func:`loads_scene` — parse an in-memory source string (for tests/tools).
* :func:`dumps_scene` — emit a ``Scene`` back to canonical ``.scene`` text
  (the inverse of :func:`loads_scene`).
* :class:`SceneFormatError` — raised for any malformed input, with line/column.
"""

from game.scenes.loader import SceneFormatError, dumps_scene, load_scene, loads_scene

__all__ = ("SceneFormatError", "dumps_scene", "load_scene", "loads_scene")
