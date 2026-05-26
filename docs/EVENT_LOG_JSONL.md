# Mirror Loop — Canonical JSONL Serialization for the Event Log

**Status:** Defined · **Date:** 2026-05-25 · **Scope:** the on-disk byte format
of one event log. Implementation: [`mirror/canonical.py`](../mirror/canonical.py)
+ `EventLog.to_jsonl_bytes` / `EventLog.from_jsonl_bytes` in
[`mirror/log.py`](../mirror/log.py). Property test:
[`mirror/tests/test_jsonl_canonical.py`](../mirror/tests/test_jsonl_canonical.py).

> The append-only event log is the only source of truth
> ([`MIRROR_SCHEMA.md` §6](./MIRROR_SCHEMA.md)). If two machines or two builds
> serialize the same log to different bytes, the log stops being a stable
> primitive — diffs, hashes, signatures, and content-addressed storage all
> silently break. This document pins **one** byte sequence per logical log, so
> `encode → decode → encode` is a fixed point.

## 1. Shape

A canonical log is a sequence of UTF-8 lines. Each line is one JSON object
followed by exactly one `\n` (`0x0A`). The file ends with `\n`; there is no
trailing blank line, no BOM, no leading whitespace.

```
<header>\n
<event_0>\n
<event_1>\n
…
<event_{n-1}>\n
```

- **Header line** (always exactly one, always first): the `EventLog` envelope
  minus `events`. For the current schema this is
  `{"fingerprint": "<hex>", "schema_version": <int>}`.
- **Event lines**: one canonical-JSON object per `MirrorEvent`, in log order, as
  produced by `event_to_dict` (`mirror/log.py`).

The header is mandatory: a log without `schema_version` + `fingerprint` cannot
prove it reduces against the current schema and is refused at load
(`EventLog.from_jsonl_bytes`), matching the existing rule for the indented
single-document form (`test_from_dict_without_fingerprint_is_refused_at_reduce`).

## 2. Canonical JSON (one object per line)

Each object is encoded with Python `json.dumps` under exactly these settings:

| Setting | Value | Why |
|---|---|---|
| `sort_keys` | `True` | Key order is lexicographic on the **NFC-normalized** key string. Eliminates dict-iteration nondeterminism. |
| `separators` | `(",", ":")` | No interior whitespace. Two encoders cannot disagree on spacing. |
| `ensure_ascii` | `True` | Output is pure ASCII; every non-ASCII codepoint becomes `\uXXXX` (surrogate pair for SMP). Removes any dependency on the host's filesystem/text encoding. |
| `allow_nan` | `False` | `NaN` / `Infinity` are not valid JSON and have no canonical decimal form. The encoder raises. |
| Indentation | none | One object, one line. |

### 2.1 Key order

Keys are sorted with Python's default string ordering **after** NFC
normalization (§2.3). Two keys that are canonically equivalent under Unicode
normalize to the same string and therefore collide — the encoder rejects the
object rather than silently dropping one.

### 2.2 Float repr

Numbers are emitted by the stdlib `json` encoder, which uses
`float.__repr__` — the *shortest decimal string that round-trips to the same
IEEE-754 double*. `1.0` stays `1.0`; `0.1 + 0.2` stays `0.30000000000000004`;
integral floats keep the trailing `.0` so the JSON type matches the in-memory
type round-trip. `NaN`, `+Infinity`, `-Infinity` are refused at encode time.

Ints are emitted as bare integers (no decimal point); the only float fields
the schema uses are `signal.target` and `signal.weight`, which are always
`float` at construction (`mirror/state.py`).

### 2.3 Unicode normalization

Every JSON string — both keys and string values — is normalized to **NFC**
before encoding. Two visually identical strings that differ only by combining
sequence (e.g. `café` vs `café`) therefore produce the same canonical
bytes. The encoder normalizes; the decoder does not need to (decoded strings
will be re-normalized on the next encode, so the second encode matches the
first).

Strings that are already NFC are unchanged. `unicodedata.normalize` is
idempotent, which is what makes the round-trip property hold.

### 2.4 Line termination

- Lines are joined with `\n` (`0x0A`) only. No `\r`. No `\r\n`.
- The file ends with `\n` (the terminator of the final line, not a blank line
  after it).
- The encoder returns `bytes`, not `str`, to remove any "did the host translate
  newlines on write" risk; callers should write with `Path.write_bytes`.

## 3. The byte-identical round-trip

For any `log: EventLog` whose events are constructible (i.e. no `NaN`, no
unknown axes, etc.):

```
b1 = log.to_jsonl_bytes()
b2 = EventLog.from_jsonl_bytes(b1).to_jsonl_bytes()
assert b1 == b2
```

This is what the property test
(`mirror/tests/test_jsonl_canonical.py::test_encode_decode_encode_is_byte_identical`)
pins, over hundreds of randomly-generated logs that include:

- non-NFC strings (decomposed accents, Hangul jamo);
- non-ASCII codepoints inside and outside the BMP;
- floats that don't have short decimal forms (`0.1 + 0.2`, etc.);
- optional provenance fields present and absent;
- empty logs, single-event logs, long multi-act logs.

Because the encoder normalizes on every call, `encode(decode(b1)) == b1` is the
round-trip identity — not "decode happens to recover the original Python
object", which is the stronger and unrelated guarantee already pinned by the
existing `to_json` tests.

## 4. What this format is **not**

- **Not** the in-memory `EventLog.to_dict()` shape. That is one JSON document
  with an `events` list; this is one document per event. The two forms coexist:
  `to_json` / `from_json` remain for human-readable single-file dumps;
  `to_jsonl_bytes` / `from_jsonl_bytes` are the canonical on-disk form.
- **Not** a streaming format with mid-log version changes. The header is fixed
  at the top; a different `schema_version` mid-stream is rejected.
- **Not** a place for per-line comments, blank lines, or trailing metadata. A
  canonical line is one JSON object; anything else is a load error.
