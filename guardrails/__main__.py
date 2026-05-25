"""``python -m guardrails <package.json>`` -> validate a content package."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
