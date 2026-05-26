"""Tests for the canonical JSONL serialization of the event log.

The spec is ``docs/EVENT_LOG_JSONL.md``. These tests pin its four invariants
(key order, float repr, Unicode normalization, line termination) and the
top-level property the spec exists to guarantee: ``encode → decode → encode``
is byte-identical.

The "property test" is hand-rolled because the repo has no ``hypothesis``
dependency. It seeds a :class:`random.Random` deterministically and generates
hundreds of diverse logs — including non-NFC strings, supplementary-plane
codepoints, floats without short decimal forms, and optional provenance fields
both present and absent — and asserts byte-identity on every one.
"""

from __future__ import annotations

import json
import math
import random
import unicodedata

import pytest

from mirror.canonical import canonical_dumps, canonical_loads, nfc
from mirror.log import (
    ChoiceObserved,
    EventLog,
    TurnAdvanced,
    event_to_dict,
    log_from_choices,
)
from mirror.schema import MIRROR_SCHEMA, SCHEMA_VERSION, AttributeKind, schema_fingerprint
from mirror.state import Choice, Signal

# ---------------------------------------------------------------------------
# Helpers: a deterministic generator of diverse event logs.
# ---------------------------------------------------------------------------

# A pool of strings that exercises the Unicode-normalization rule. Each pair
# contains a not-already-NFC form (e.g. decomposed "é" as "e" + U+0301) and a
# composed form. After encoding they must produce the same bytes.
_NON_NFC_STRINGS = [
    "café",       # café, decomposed
    "Zoë",         # composed
    "ṩ",           # ṩ (s with dot-below + dot-above), composed
    "ṩ",    # s with combining dot-below + dot-above, decomposed
    "Ångström",
    "Ångström",  # decomposed equivalent
    "각",  # Hangul jamo (decomposes), → composed 각
    "☃",            # snowman, BMP
    "\U0001f600",        # grinning face, supplementary plane
    "simple_ascii",
    "",                  # empty string is legal too
]

_SCALAR_AXES = [
    name for name, spec in MIRROR_SCHEMA.items()
    if spec.kind is not AttributeKind.DISTRIBUTION
]
_DIST_AXES = [
    (name, spec.modes)
    for name, spec in MIRROR_SCHEMA.items()
    if spec.kind is AttributeKind.DISTRIBUTION
]


def _random_signal(rng: random.Random) -> Signal:
    """A random signal that targets a real axis with a valid payload."""
    if rng.random() < 0.6 or not _DIST_AXES:
        name = rng.choice(_SCALAR_AXES)
        spec = MIRROR_SCHEMA[name]
        low, high = (
            (0.0, 1.0) if spec.kind is AttributeKind.UNIT else (-1.0, 1.0)
        )
        # Mix of clean fractions and "ugly" floats (0.1 + 0.2-style) to
        # exercise the shortest-round-tripping float repr rule.
        ugly = rng.random() < 0.3
        target = (
            rng.uniform(low, high) if ugly
            else rng.choice([low, 0.0, high, 0.5 * (low + high)])
        )
        weight = rng.choice([1.0, 0.5, 0.25, 0.1 + 0.2, 0.7])
        return Signal.toward(name, float(target), weight=float(weight))
    name, modes = rng.choice(_DIST_AXES)
    return Signal.spend(name, rng.choice(modes), weight=rng.choice([1.0, 0.5]))


def _random_choice_id(rng: random.Random) -> str:
    """Choice ids include non-NFC text on purpose."""
    base = rng.choice([
        "question",
        "inspect_exit",
        "refuse_risky_offer",
        "challenge",
        rng.choice(_NON_NFC_STRINGS) or "anon",
    ])
    return base


def _random_provenance(rng: random.Random) -> tuple[str | None, str | None]:
    """``scene_id`` / ``act_id`` — sometimes None, sometimes non-NFC text."""
    if rng.random() < 0.3:
        return (None, None)
    scene = rng.choice([None, *_NON_NFC_STRINGS, "lab_observation_room"])
    act = rng.choice([None, "act_1", "act_2", rng.choice(_NON_NFC_STRINGS)])
    return (scene or None, act or None)


def _random_log(rng: random.Random, *, max_events: int = 12) -> EventLog:
    """A random EventLog with a mix of choice and turn events."""
    n = rng.randint(0, max_events)
    events = []
    for _ in range(n):
        if rng.random() < 0.25:
            events.append(TurnAdvanced())
            continue
        n_sigs = rng.randint(0, 4)
        signals = tuple(_random_signal(rng) for _ in range(n_sigs))
        scene_id, act_id = _random_provenance(rng)
        events.append(ChoiceObserved(
            choice_id=_random_choice_id(rng),
            signals=signals,
            scene_id=scene_id,
            act_id=act_id,
        ))
    return EventLog(events=tuple(events))


# ---------------------------------------------------------------------------
# The headline property: encode → decode → encode is byte-identical.
# ---------------------------------------------------------------------------


def test_encode_decode_encode_is_byte_identical_property():
    """The spec's load-bearing fixed-point.

    Run a couple of hundred randomly-generated logs through
    ``encode → decode → encode`` and assert the second encoding produces the
    exact same bytes. Seeded so the test is deterministic; an offending case
    can be reproduced from the seed printed in the failure message.
    """
    rng = random.Random(0xCA11AB1E)
    for i in range(250):
        log = _random_log(rng)
        b1 = log.to_jsonl_bytes()
        restored = EventLog.from_jsonl_bytes(b1)
        b2 = restored.to_jsonl_bytes()
        assert b1 == b2, (
            f"non-canonical: iteration {i}, log with {len(log.events)} events "
            f"failed encode→decode→encode byte-identity"
        )


def test_encode_decode_encode_byte_identical_on_known_sessions():
    """The full-session fixtures from ``test_log.py`` also round-trip."""
    for choices in (_short_session(), _full_session()):
        log = log_from_choices(choices)
        b1 = log.to_jsonl_bytes()
        b2 = EventLog.from_jsonl_bytes(b1).to_jsonl_bytes()
        assert b1 == b2


def test_empty_log_round_trips():
    log = EventLog()
    b1 = log.to_jsonl_bytes()
    # exactly one line — the header — terminated by one newline.
    assert b1.count(b"\n") == 1
    b2 = EventLog.from_jsonl_bytes(b1).to_jsonl_bytes()
    assert b1 == b2


# ---------------------------------------------------------------------------
# Invariant 1 — key order is lexicographic on NFC-normalized keys.
# ---------------------------------------------------------------------------


def test_keys_are_sorted_lexicographically():
    line = canonical_dumps({"z": 1, "a": 2, "m": 3})
    assert line == '{"a":2,"m":3,"z":1}'


def test_dict_keys_are_normalized_to_nfc_before_sorting():
    # Two keys that compose to the same NFC string must collide loudly,
    # never silently overwrite.
    with pytest.raises(ValueError, match="NFC"):
        canonical_dumps({"café": 1, "café": 2})


def test_non_string_dict_keys_are_rejected():
    with pytest.raises(TypeError):
        canonical_dumps({1: "x"})


# ---------------------------------------------------------------------------
# Invariant 2 — float repr: shortest round-tripping; NaN/Inf refused.
# ---------------------------------------------------------------------------


def test_floats_use_shortest_round_tripping_decimal():
    # `0.1 + 0.2` does not have a short decimal form; the encoder must emit
    # the full repr so the decode recovers the same IEEE-754 double.
    s = canonical_dumps({"x": 0.1 + 0.2})
    assert s == '{"x":0.30000000000000004}'
    assert json.loads(s)["x"] == 0.1 + 0.2


def test_integral_floats_keep_their_decimal_point():
    # 1.0 stays 1.0 (a float), 1 stays 1 (an int). Preserves the JSON type
    # so round-trip equality at the Python level still holds.
    assert canonical_dumps({"f": 1.0}) == '{"f":1.0}'
    assert canonical_dumps({"i": 1}) == '{"i":1}'


def test_nan_and_inf_are_refused():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            canonical_dumps({"x": bad})


# ---------------------------------------------------------------------------
# Invariant 3 — Unicode normalization to NFC, idempotent.
# ---------------------------------------------------------------------------


def test_strings_are_normalized_to_nfc_in_values():
    decomposed = "café"
    composed = unicodedata.normalize("NFC", decomposed)
    assert decomposed != composed
    a = canonical_dumps({"k": decomposed})
    b = canonical_dumps({"k": composed})
    assert a == b


def test_strings_are_normalized_in_keys_too():
    decomposed = "café"
    composed = unicodedata.normalize("NFC", decomposed)
    a = canonical_dumps({decomposed: 1})
    b = canonical_dumps({composed: 1})
    assert a == b


def test_nfc_walks_nested_lists_and_dicts():
    payload = {
        "outer": [{"inner": "café"}, ("a", "b")],
    }
    out = nfc(payload)
    assert out["outer"][0]["inner"] == "café"
    # tuples normalize through as lists (JSON has no tuple type).
    assert out["outer"][1] == ["a", "b"]


def test_nfc_is_idempotent_on_already_normalized_input():
    payload = {"k": "café", "x": [1.0, 2.0, "☃"]}
    once = nfc(payload)
    twice = nfc(once)
    assert once == twice
    assert canonical_dumps(once) == canonical_dumps(twice)


def test_non_ascii_is_emitted_as_ascii_escapes():
    # The canonical form is platform-independent — every non-ASCII codepoint
    # becomes a \uXXXX escape so the bytes never depend on a host encoding.
    s = canonical_dumps({"k": "☃"})  # snowman, U+2603
    assert s == '{"k":"\\u2603"}'
    # Supplementary plane → surrogate pair (json stdlib behavior).
    s = canonical_dumps({"k": "\U0001f600"})  # grinning face, U+1F600
    assert s == '{"k":"\\ud83d\\ude00"}'
    # And every byte of the canonical string is plain ASCII.
    assert s.encode("ascii").decode("ascii") == s


# ---------------------------------------------------------------------------
# Invariant 4 — line termination: LF only, trailing LF, no blanks/CR.
# ---------------------------------------------------------------------------


def test_jsonl_ends_with_lf_and_uses_no_cr():
    log = log_from_choices(_short_session())
    b = log.to_jsonl_bytes()
    assert b.endswith(b"\n")
    assert b"\r" not in b


def test_one_line_per_event_plus_one_for_the_header():
    log = log_from_choices(_short_session())
    b = log.to_jsonl_bytes()
    # short session has 2 choices × (1 ChoiceObserved + 1 TurnAdvanced) = 4 events
    assert b.count(b"\n") == 1 + len(log.events) == 5


def test_canonical_dumps_never_contains_a_newline():
    # Every value below contains a literal newline character in a string; the
    # encoder must escape it, not pass it through.
    line = canonical_dumps({"text": "line1\nline2"})
    assert "\n" not in line
    assert json.loads(line)["text"] == "line1\nline2"


def test_decoder_rejects_cr_in_input():
    log = log_from_choices(_short_session())
    b = log.to_jsonl_bytes().replace(b"\n", b"\r\n", 1)
    with pytest.raises(ValueError, match="CR"):
        EventLog.from_jsonl_bytes(b)


def test_decoder_rejects_missing_trailing_newline():
    log = log_from_choices(_short_session())
    b = log.to_jsonl_bytes().rstrip(b"\n")
    with pytest.raises(ValueError, match="trailing newline"):
        EventLog.from_jsonl_bytes(b)


def test_decoder_rejects_blank_lines():
    log = log_from_choices(_short_session())
    b = log.to_jsonl_bytes()
    # Splice in a blank line after the header.
    head, _, rest = b.partition(b"\n")
    spliced = head + b"\n\n" + rest
    with pytest.raises(ValueError, match="blank lines"):
        EventLog.from_jsonl_bytes(spliced)


def test_decoder_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        EventLog.from_jsonl_bytes(b"")


def test_decoder_rejects_header_without_schema_version():
    payload = (canonical_dumps({"fingerprint": "deadbeef"}) + "\n").encode("ascii")
    with pytest.raises(ValueError, match="schema_version"):
        EventLog.from_jsonl_bytes(payload)


def test_decoder_rejects_str_input():
    with pytest.raises(TypeError):
        EventLog.from_jsonl_bytes("not bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The canonical form composes with the existing schema/fingerprint guard.
# ---------------------------------------------------------------------------


def test_jsonl_round_trip_reduces_to_identical_state():
    log = log_from_choices(_full_session())
    restored = EventLog.from_jsonl_bytes(log.to_jsonl_bytes())
    assert restored.events == log.events
    assert restored.reduce() == log.reduce()
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.fingerprint == schema_fingerprint()


def test_jsonl_preserves_a_drifted_fingerprint_for_loud_failure():
    # A log written under a different fingerprint must come back with that
    # *same* fingerprint, so the reduce guard fires — not be silently coerced.
    log = EventLog(events=(TurnAdvanced(),), fingerprint="deadbeef")
    restored = EventLog.from_jsonl_bytes(log.to_jsonl_bytes())
    assert restored.fingerprint == "deadbeef"
    with pytest.raises(ValueError, match="fingerprint"):
        restored.reduce()


# ---------------------------------------------------------------------------
# Header layout: one specific, frozen example so the on-disk shape is pinned.
# ---------------------------------------------------------------------------


def test_header_layout_is_frozen():
    """The header is the first line, alphabetic on its keys, no whitespace."""
    log = EventLog()
    b = log.to_jsonl_bytes()
    header_line = b.split(b"\n", 1)[0].decode("ascii")
    parsed = json.loads(header_line)
    assert parsed == {
        "fingerprint": schema_fingerprint(),
        "schema_version": SCHEMA_VERSION,
    }
    # And the on-the-wire ordering is alphabetic ('f' < 's').
    assert header_line.index('"fingerprint"') < header_line.index('"schema_version"')


def test_event_line_layout_is_frozen():
    event = ChoiceObserved(
        choice_id="inspect_exit",
        signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "exploration"),
        ),
        scene_id="lab_observation_room",
        act_id="act_2",
    )
    line = canonical_dumps(event_to_dict(event))
    # Keys are alphabetic; no whitespace; floats keep their decimal point.
    assert line == (
        '{"act_id":"act_2",'
        '"choice_id":"inspect_exit",'
        '"event_type":"choice_observed",'
        '"scene_id":"lab_observation_room",'
        '"signals":['
        '{"attribute":"authority_trust","target":-1.0,"weight":1.0},'
        '{"attribute":"playstyle_mix","mode":"exploration","weight":1.0}'
        ']}'
    )


# ---------------------------------------------------------------------------
# Re-use the fixtures from the existing log tests so we share session shapes.
# ---------------------------------------------------------------------------


def _short_session() -> list[Choice]:
    return [
        Choice("question", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("inspect_exit", signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
            Signal.toward("frustration", 1.0, weight=0.5),
        )),
    ]


def _full_session() -> list[Choice]:
    return [
        Choice("question", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("inspect_exit", signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
            Signal.toward("frustration", 1.0, weight=0.6),
        )),
        Choice("refuse_risky_offer", signals=(Signal.toward("risk_tolerance", -1.0),)),
        Choice("challenge", signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.spend("playstyle_mix", "conversation"),
        )),
        Choice("probe_again", signals=(Signal.toward("boundary_testing", 1.0),)),
        Choice("decline_again", signals=(Signal.toward("risk_tolerance", -1.0),)),
        Choice("read_lore", signals=(
            Signal.toward("curiosity", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
        )),
        Choice("hold_principle", signals=(Signal.toward("moral_consistency", 1.0),)),
    ]
