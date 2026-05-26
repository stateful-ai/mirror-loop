# Mirror Loop — The Handcrafted Scene Authoring Format

**Status:** Defined · **Date:** 2026-05-25 · **Scope:** the on-disk text format
for authoring one scene, and the loader contract that turns it into a typed
[`loop.core.Scene`](../loop/core.py).
**Implemented by:** [`game/scenes/loader.py`](../game/scenes/loader.py).
**Verified by:** [`game/tests/test_scenes.py`](../game/tests/test_scenes.py) —
every example below is asserted against the loader.
**Worked example:** [`game/scenes/data/intake.scene`](../game/scenes/data/intake.scene).

> This document defines how a designer writes a scene as a **text data file**
> rather than as Python code. It is the authoring counterpart to the in-code
> world spine in [`game/world.py`](../game/world.py): the same `Scene`/`Choice`
> objects, authored as data. No part of a scene file is executed.

---

## 1. Why a custom text format (and not YAML / JSON / TOML)

The runtime is stdlib-only (see [`docs/adr/0002-runtime-platform.md`](./adr/0002-runtime-platform.md)),
so we cannot depend on PyYAML; `tomllib` lands only at Python 3.11 (this project
declares `>=3.10`); JSON is text but is hostile to multi-line prose (every
newline becomes `\n`, every quote escaped). The format below is intentionally
**tiny, line-oriented, and not YAML** — it has no anchors, tags, inline flows,
type coercion, or `!!python/object`-style traps. The loader is auditable in one
screen and the grammar fits on the back of an index card.

The other half of "no code-in-data" is the loader: it parses bytes and never
calls `eval`, `exec`, `import`, or any other code-from-data primitive. A scene
file is data; reading one cannot execute anything.

---

## 2. The grammar

A scene file is UTF-8 text, line-oriented, with **Unix newlines** (LF). The
loader splits on universal newlines, so CRLF is tolerated on read but LF is
canonical. Indentation is **exactly two spaces** per level; tabs are rejected.

Informal grammar (`SKIP` = any number of `comment` and `blank` lines):

```
file          := SKIP  id_line  SKIP  prompt_block  SKIP  choice_block (SKIP choice_block)*  SKIP

id_line       := "id:" SP <scene-id> NL
prompt_block  := "prompt:" NL  prompt_line+            -- at least one text line
prompt_line   := "  " <text> NL                        -- indented text, comment, or blank
choice_block  := "choice " <choice-id> ":" NL  choice_body+
choice_body   := field | comment | blank               -- exactly three distinct fields total
field         := "  " ("tendency" | "text" | "evidence") ":" SP <value> NL

comment       := /\s*#[^\n]*\n/        -- full-line comment, ignored
blank         := /\s*\n/                -- ignored at top level; paragraph break inside prompt

<scene-id>    := /[A-Za-z_][A-Za-z0-9_]*/
<choice-id>   := /[A-Za-z_][A-Za-z0-9_]*/
<value>       := UTF-8 text; leading/trailing whitespace stripped; must be non-empty;
                 tabs in the value are rejected
```

The required structural order is **`id:` → `prompt:` → one-or-more `choice
<id>:`**. Comments and blank lines may appear:

- between any two top-level sections (ignored);
- inside a `prompt:` block — a blank line is a paragraph break, and a
  two-space-indented comment (`  #…`) is ignored without breaking the
  paragraph (see §4);
- inside a `choice <id>:` block, between its fields (ignored).

---

## 3. The minimal worked example

```
id: intake

prompt:
  The Mirror Lab's intake room is warm and spotless. A technician fits the
  headset to your head; her hands are shaking.

choice c_reassure:
  tendency: kindness
  text: Tell her to take her time — you are in no hurry.
  evidence: reassured the technician at intake

choice c_measure:
  tendency: control
  text: Ask exactly what the headset records, and where it goes.
  evidence: interrogated the headset's purpose at intake

choice c_refuse:
  tendency: defiance
  text: Keep the headset off until someone explains how to leave.
  evidence: refused the headset until told the way out
```

The shipped copy of this file is
[`game/scenes/data/intake.scene`](../game/scenes/data/intake.scene), and a test
asserts the loaded object is equal to `game.world.INTAKE` (the same scene, in
code). The format and the in-code authoring are interchangeable.

---

## 4. Sections in detail

### `id:` (required, exactly once, first)

The scene's stable identifier, e.g. `id: intake`. Must be a Python-identifier
shape (letter or underscore, then letters/digits/underscores). It is the value
that lands in `Scene.id` and that the rest of the runtime cites — including the
event log's `scene_id` field — so it is a long-lived reference.

### `prompt:` (required, exactly once, after `id:`)

The text the player reads. The header is `prompt:` on its own line; the body is
one or more **two-space-indented** lines beneath it.

Folding rules:
- Adjacent indented text lines are joined into one paragraph with **a single
  space** between them. (Authors can wrap long prose at 80 columns without
  changing the rendered text.)
- A **blank line** (or a fully blank indented line) inside the block is a
  **paragraph break**: paragraphs are joined with `\n\n`.
- Leading/trailing whitespace inside each line is stripped.
- A comment line inside the block (still two-space-indented, starting with
  `#`) is ignored and does **not** count as a paragraph break.

Example with two paragraphs:

```
prompt:
  The Mirror Lab's intake room is warm and spotless. A technician fits the
  headset to your head; her hands are shaking.

  She does not meet your eye.
```

### `choice <id>:` (required, one or more)

Each block declares one option the player can pick. The header is
`choice <id>:` and the body is exactly three two-space-indented fields, **in
any order, each exactly once**:

| Field | Lands on | Meaning |
|-------|----------|---------|
| `tendency` | `Choice.tendency` | the single behavioral axis this option expresses (e.g. `kindness`). See [`docs/ADAPTATION.md`](./ADAPTATION.md) §2 — the v0 vocabulary is `kindness`, `control`, `defiance`, but the format itself does not constrain the string so other worlds can ship other vocabularies. |
| `text` | `Choice.text` | what the player reads on the option. |
| `evidence` | `Choice.evidence` | the past-tense phrase the Mirror cites when it later reflects on this choice (`docs/CORE_LOOP.md` §3). Must read as observed *in-game* behavior — never a claim about the real player. |

Choice IDs must be unique within a scene and must be Python-identifier-shaped
(they are stable references; e.g. `c_reassure` appears in event logs and in
`Mirror.predict` output).

### Comments and blank lines

A `#` at the start of a line (after any whitespace) makes the rest of the line
a comment. Blank lines are ignored *except* inside a `prompt:` block, where
they mark a paragraph break (see above).

---

## 5. The loader contract

The Python entry points are in [`game/scenes/loader.py`](../game/scenes/loader.py):

| Function | Signature | Returns |
|----------|-----------|---------|
| `load_scene(path)` | `str \| Path → Scene` | reads the file as UTF-8 and parses it. |
| `loads_scene(source)` | `str → Scene` | parses an in-memory string (for tests / tools). |

Both return a `loop.core.Scene` whose `id`, `prompt`, and `choices` come
verbatim from the file. The `Choice` objects appear in the **declared order**;
the runtime's adaptation is the only thing that ever re-orders them (see
[`docs/ADAPTATION.md`](./ADAPTATION.md) §1, `Mirror.adapt`).

**Errors.** Any malformed input raises `SceneFormatError` (a `ValueError`
subclass) carrying a 1-based `lineno` pointing at the offending line. The
loader fails loudly rather than partially constructing a scene. Cases the
loader rejects:

- missing `id:`, `prompt:`, or a fields-complete choice block;
- an unknown field name in a choice (only `tendency`, `text`, `evidence` are
  accepted);
- a duplicate field within one choice, or a duplicate choice id within one
  scene;
- a `prompt:` block with no indented text;
- an empty value (`key:` with nothing after);
- a non-identifier scene id or choice id;
- tabs in a value, or wrong indentation in a field line;
- any trailing content after the last choice block that isn't a comment or
  blank line.

**Determinism.** The loader is pure: it touches no global state and produces
byte-identical `Scene` objects for byte-identical input. Two readers of the
same file always get the same scene; reductions and replays downstream are not
disturbed.

---

## 6. What this format does *not* try to do

The contract above is deliberately small. Things it explicitly leaves out, so
the format can grow without breaking the v0 example:

- **No world / spine wiring.** This is a one-scene format. The handcrafted
  spine (which slot is fixed, which is a branch, the order of slots) still
  lives in [`game/world.py`](../game/world.py). Future work can layer a
  *world* file on top that names which `.scene` files fill which slots; that
  is a strict superset and does not change anything documented here.
- **No conditionals, no expressions, no scripting.** A scene file is data.
  Any branching belongs to the runtime's adaptation type
  ([`docs/ADAPTATION.md`](./ADAPTATION.md)), not the authoring format.
- **No numbers, booleans, or typed values.** Everything is a string. The
  runtime types live in `loop/core.py`.
- **No includes, imports, or references between files.** A scene is
  self-contained.

If any of these constraints needs to relax, bump a version line at the top of
this document and add the test to `game/tests/test_scenes.py` *before*
changing the loader — the spec is the contract.
