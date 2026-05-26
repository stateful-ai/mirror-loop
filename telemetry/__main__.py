"""``python -m telemetry`` — entrypoint for the local-only playtest CLI.

Delegates to :func:`telemetry.main`; see ``docs/PLAYTEST_README.md`` for the
participant-facing disclosure and consent flow.
"""

from __future__ import annotations

from . import main


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
