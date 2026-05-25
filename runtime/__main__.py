"""``python -m runtime`` — boot the skeleton and render an empty world.

The minimal runtime entrypoint: it proves the boot path and the rendering seam
work end to end before any scene, reducer, or adaptation exists. ``--title`` is
the one knob, so the empty-world frame is verifiable without hard-coding text.
"""

from __future__ import annotations

import argparse

from runtime.shell import boot
from runtime.view import DEFAULT_TITLE, empty_world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime", description=__doc__)
    parser.add_argument(
        "--title",
        default=DEFAULT_TITLE,
        help=f"title shown above the empty world (default: {DEFAULT_TITLE!r})",
    )
    args = parser.parse_args(argv)

    boot(world=empty_world(title=args.title))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper, exercised via main()
    raise SystemExit(main())
