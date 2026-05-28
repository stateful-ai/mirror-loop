"""``python -m llmbench`` entry point.

Thin shim around :func:`llmbench.harness.main` — the CLI implementation lives in
the harness module so the package's single ``main`` callable is also the module
attribute the harness exposes.
"""

from __future__ import annotations

from .harness import main

__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
