"""Canonical JSON encoding for the event log's JSONL form.

The on-disk byte format of one event log is pinned by
``docs/EVENT_LOG_JSONL.md``. This module is the encoder/decoder primitive: one
function ``canonical_dumps`` that takes a JSON-ready Python object and returns
the canonical one-line JSON string for it, and one function
``canonical_loads`` that parses a single canonical line back. ``EventLog`` in
``mirror/log.py`` composes these into the full JSONL envelope.

The four invariants the spec pins, all enforced here:

1. **Key order** is lexicographic on the NFC-normalized key string
   (``sort_keys=True`` after NFC).
2. **Float repr** is Python's shortest-round-tripping decimal
   (``float.__repr__``, via stdlib ``json``). ``NaN`` and ``±Infinity`` are
   refused (``allow_nan=False``).
3. **Unicode normalization**: every JSON string — key or value — is normalized
   to NFC before encoding. Idempotent, so the round-trip is byte-identical.
4. **Line termination**: a canonical line has no interior whitespace
   (``separators=(",", ":")``), no trailing whitespace, and no embedded
   newlines; the JSONL writer in ``mirror/log.py`` joins lines with ``\\n``.

The encoder is ASCII-only (``ensure_ascii=True``): every non-ASCII codepoint
becomes a ``\\uXXXX`` escape. That makes the canonical bytes independent of any
host text encoding.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

#: Compact JSON separators — no spaces. Two encoders cannot disagree on these.
_CANONICAL_SEPARATORS = (",", ":")


def nfc(value: Any) -> Any:
    """Return ``value`` with every contained ``str`` normalized to Unicode NFC.

    Walks dicts and lists/tuples; leaves numbers, bools, and ``None`` alone.
    Dict keys are normalized too, and a collision under NFC (two visually
    equivalent keys that compose to the same string) is rejected — silently
    dropping one would be exactly the kind of canonicalization bug this module
    exists to prevent.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, sub in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"canonical JSON object keys must be str, got {type(key).__name__}"
                )
            nkey = unicodedata.normalize("NFC", key)
            if nkey in normalized:
                raise ValueError(
                    f"canonical JSON dict has two keys that collide under NFC: "
                    f"{key!r} and an earlier key normalize to {nkey!r}"
                )
            normalized[nkey] = nfc(sub)
        return normalized
    if isinstance(value, (list, tuple)):
        return [nfc(v) for v in value]
    return value


def canonical_dumps(obj: Any) -> str:
    """Encode ``obj`` to its single-line canonical JSON string.

    The returned string never contains a newline; callers that want a JSONL
    line should append ``\\n``. Raises :class:`ValueError` on ``NaN``/``Inf``
    (no canonical decimal form) and :class:`TypeError` on non-string dict keys.
    """
    return json.dumps(
        nfc(obj),
        sort_keys=True,
        separators=_CANONICAL_SEPARATORS,
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_loads(line: str) -> Any:
    """Parse one canonical JSON line back into a Python object.

    Symmetric with :func:`canonical_dumps`. The line must contain no embedded
    newline; the JSONL splitter is what consumes the ``\\n`` terminators.
    """
    if "\n" in line:
        raise ValueError("a canonical JSON line must not contain a newline")
    return json.loads(line)


__all__ = ["canonical_dumps", "canonical_loads", "nfc"]
