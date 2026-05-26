"""Parser + loader for the handcrafted ``.scene`` authoring format.

The format is specified in ``docs/SCENE_FORMAT.md`` — this module is the
**reference implementation** of that contract. The two documents must agree;
the tests in ``game/tests/test_scenes.py`` pin every example from the spec.

The format is deliberately **not YAML** (and not JSON): the grammar is small,
fully line-oriented, and strict, so the parser is auditable in one screen and
admits no surprises (no anchors, tags, inline flows, type coercion, or
``!!python/object`` traps). All values are strings. Indentation is exactly two
spaces per level. A file may not contain any code; the loader executes nothing
from the data.

Grammar (informal):

    file        := (line)*
    line        := blank | comment | id_line | prompt_header | prompt_line
                 | choice_header | choice_field
    blank       := /\\s*\\n/
    comment     := /\\s*#[^\\n]*\\n/
    id_line     := "id:" SP value NL              -- exactly once, before prompt
    prompt_header := "prompt:" NL                  -- exactly once
    prompt_line := "  " text NL                   -- one or more, after prompt_header
    choice_header := "choice " choice_id ":" NL   -- one or more (>=1)
    choice_field  := "  " key ":" SP value NL     -- exactly {tendency,text,evidence}
    key         := "tendency" | "text" | "evidence"
    choice_id   := /[A-Za-z_][A-Za-z0-9_]*/
    value       := any text (rstripped); empty rejected

Folding: the prompt block's indented lines are joined with single spaces; a
blank line *inside* the prompt block becomes a paragraph break (``\\n\\n``).
Leading/trailing whitespace in each prompt line is stripped.

Every error is raised as :class:`SceneFormatError` with the 1-based line number
of the offending line so authoring mistakes are easy to locate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loop.core import Choice, Scene

# The fields a choice block must declare, in any order, exactly once each.
_CHOICE_FIELDS = frozenset({"tendency", "text", "evidence"})

# A `choice <id>:` header's id token. Keep this conservative: identifier-like,
# because choice ids are referenced by code (see e.g. ``c_reassure`` in
# ``game/world.py``) and round-tripped through JSON event logs.
_ID_CHARS_HEAD = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_ID_CHARS_TAIL = _ID_CHARS_HEAD + "0123456789"


class SceneFormatError(ValueError):
    """Raised when a ``.scene`` source cannot be parsed.

    Carries ``lineno`` (1-based) pointing at the offending line so authoring
    mistakes surface with a precise location.
    """

    def __init__(self, message: str, lineno: int) -> None:
        super().__init__(f"line {lineno}: {message}")
        self.lineno = lineno


def load_scene(path: str | Path) -> Scene:
    """Read a ``.scene`` file and parse it into a typed :class:`Scene`.

    The file is read as UTF-8 text. Any I/O error propagates as-is; any
    parsing error raises :class:`SceneFormatError`.
    """
    source = Path(path).read_text(encoding="utf-8")
    return loads_scene(source)


def loads_scene(source: str) -> Scene:
    """Parse a ``.scene`` source string into a typed :class:`Scene`.

    Same contract as :func:`load_scene`, but takes the text directly. Useful
    for tests and tooling that synthesize scenes in memory.
    """
    return _Parser(source).parse()


def dumps_scene(scene: Scene) -> str:
    """Emit a :class:`Scene` as the canonical ``.scene`` text form.

    The inverse of :func:`loads_scene`: ``loads_scene(dumps_scene(s)) == s`` for
    any Scene built through normal authoring. Comments are not preserved
    (they're not part of the Scene), and each prompt paragraph is collapsed to a
    single indented line so the round-trip is stable through the parser's
    "fold indented lines into one paragraph" rule.

    Raises :class:`SceneFormatError` (with ``lineno=0`` since there is no source
    line) if the Scene contains content the format cannot represent — an empty
    prompt, no choices, or a tab in any value.
    """
    if not scene.choices:
        raise SceneFormatError(
            "cannot dump a scene with no choices (the format requires >= 1)", 0
        )
    paragraphs = [p for p in scene.prompt.split("\n\n")]
    if not any(p.strip() for p in paragraphs):
        raise SceneFormatError(
            "cannot dump a scene with an empty prompt", 0
        )

    lines: list[str] = [f"id: {scene.id}", "", "prompt:"]
    for i, paragraph in enumerate(paragraphs):
        if i > 0:
            lines.append("")
        # A paragraph may legitimately contain single newlines (from in-code
        # authoring) — flatten them to spaces so the dumped form is the one the
        # parser will fold back into the same paragraph string.
        collapsed = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        if "\t" in collapsed:
            raise SceneFormatError(
                "scene prompt contains a tab; the .scene format forbids tabs", 0
            )
        lines.append(f"  {collapsed}")

    for choice in scene.choices:
        for field_name, value in (
            ("tendency", choice.tendency),
            ("text", choice.text),
            ("evidence", choice.evidence),
        ):
            if "\t" in value:
                raise SceneFormatError(
                    f"choice {choice.id!r} field {field_name!r} contains a tab; "
                    "the .scene format forbids tabs",
                    0,
                )
            if "\n" in value:
                raise SceneFormatError(
                    f"choice {choice.id!r} field {field_name!r} contains a newline; "
                    "the .scene format requires single-line field values",
                    0,
                )
        lines.extend(
            (
                "",
                f"choice {choice.id}:",
                f"  tendency: {choice.tendency}",
                f"  text: {choice.text}",
                f"  evidence: {choice.evidence}",
            )
        )

    return "\n".join(lines) + "\n"


# --- Internal --------------------------------------------------------------


@dataclass
class _ChoiceDraft:
    lineno: int
    id: str
    fields: dict[str, str]


class _Parser:
    """Single-pass, line-oriented parser. All state is local to one parse."""

    def __init__(self, source: str) -> None:
        # Splitlines drops the trailing newline (if any). We address lines by
        # 1-based index when reporting errors.
        self._lines = source.splitlines()
        self._i = 0  # cursor into _lines (0-based)

    def parse(self) -> Scene:
        scene_id = self._parse_id_line()
        prompt = self._parse_prompt_block()
        choices = self._parse_choice_blocks()
        self._expect_eof()
        return Scene(id=scene_id, prompt=prompt, choices=choices)

    # -- cursor helpers --

    @property
    def _lineno(self) -> int:
        return self._i + 1

    def _peek(self) -> str | None:
        if self._i >= len(self._lines):
            return None
        return self._lines[self._i]

    def _advance(self) -> str:
        line = self._lines[self._i]
        self._i += 1
        return line

    def _skip_blanks_and_comments(self) -> None:
        while self._i < len(self._lines):
            line = self._lines[self._i]
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#"):
                self._i += 1
                continue
            return

    # -- section parsers --

    def _parse_id_line(self) -> str:
        self._skip_blanks_and_comments()
        if self._peek() is None:
            raise SceneFormatError("expected `id: <scene-id>` but file is empty", 1)
        line_lineno = self._lineno
        line = self._advance()
        # Inspect the key first so a file that opens with the wrong section
        # (e.g. `prompt:`) gets the actionable "expected `id:`" error, not the
        # less-specific "empty value" error from the generic splitter.
        if ":" not in line:
            raise SceneFormatError(
                f"expected `id: <scene-id>`, got `{line.rstrip()}`", line_lineno
            )
        key = line.partition(":")[0].strip()
        if key != "id":
            raise SceneFormatError(
                f"expected `id:` as the first field, got `{key}:`", line_lineno
            )
        _, value = _split_key_value(line, line_lineno)
        _validate_identifier(value, "scene id", line_lineno)
        return value

    def _parse_prompt_block(self) -> str:
        self._skip_blanks_and_comments()
        if self._peek() is None:
            raise SceneFormatError("expected `prompt:` header", self._lineno)
        header_lineno = self._lineno
        header = self._advance()
        if header.strip() != "prompt:":
            raise SceneFormatError(
                "expected `prompt:` header on its own line", header_lineno
            )

        paragraphs: list[list[str]] = [[]]
        saw_any_text = False
        # Read indented lines (two-space prefix) and blank lines as paragraph
        # separators *inside* the block. The block ends at the first line that
        # is neither indented nor blank.
        while self._i < len(self._lines):
            line = self._lines[self._i]
            stripped = line.strip()
            if line.startswith("  "):
                # Comment lines inside the block are ignored.
                if stripped.startswith("#"):
                    self._i += 1
                    continue
                # An indented line that is otherwise blank counts as a
                # paragraph break (same as a fully blank line below).
                if stripped == "":
                    if paragraphs[-1]:
                        paragraphs.append([])
                    self._i += 1
                    continue
                paragraphs[-1].append(stripped)
                saw_any_text = True
                self._i += 1
                continue
            if stripped == "":
                # Blank line: paragraph break (only meaningful between text).
                if paragraphs[-1]:
                    paragraphs.append([])
                self._i += 1
                continue
            # A non-indented non-blank line ends the prompt block.
            break

        if not saw_any_text:
            raise SceneFormatError(
                "`prompt:` block must contain at least one indented text line",
                header_lineno,
            )

        # Drop any trailing empty paragraph.
        while paragraphs and not paragraphs[-1]:
            paragraphs.pop()

        return "\n\n".join(" ".join(p) for p in paragraphs)

    def _parse_choice_blocks(self) -> tuple[Choice, ...]:
        drafts: list[_ChoiceDraft] = []
        seen_ids: set[str] = set()

        while True:
            self._skip_blanks_and_comments()
            if self._peek() is None:
                break
            line = self._peek()
            if not _is_choice_header(line):
                # Anything else at top level is unrecognized.
                raise SceneFormatError(
                    f"unexpected line at top level: `{line.rstrip()}` "
                    "(expected a `choice <id>:` block or end-of-file)",
                    self._lineno,
                )
            draft = self._parse_one_choice()
            if draft.id in seen_ids:
                raise SceneFormatError(
                    f"duplicate choice id `{draft.id}`", draft.lineno
                )
            seen_ids.add(draft.id)
            drafts.append(draft)

        if not drafts:
            raise SceneFormatError(
                "scene must declare at least one `choice <id>:` block",
                self._lineno,
            )

        return tuple(
            Choice(
                id=d.id,
                text=d.fields["text"],
                tendency=d.fields["tendency"],
                evidence=d.fields["evidence"],
            )
            for d in drafts
        )

    def _parse_one_choice(self) -> _ChoiceDraft:
        header_lineno = self._lineno
        header = self._advance().rstrip()
        # We already checked _is_choice_header, but re-parse strictly here so
        # the error messages live in one place.
        choice_id = _parse_choice_header(header, header_lineno)

        fields: dict[str, str] = {}
        while self._i < len(self._lines):
            line = self._lines[self._i]
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#"):
                self._i += 1
                continue
            if not line.startswith("  "):
                break
            # An indented line within a choice block must be a field.
            field_lineno = self._lineno
            self._i += 1
            indent_stripped = line[2:]
            if indent_stripped.startswith(" "):
                raise SceneFormatError(
                    "choice fields must be indented exactly two spaces",
                    field_lineno,
                )
            key, value = _split_key_value(indent_stripped, field_lineno)
            if key not in _CHOICE_FIELDS:
                raise SceneFormatError(
                    f"unknown choice field `{key}` "
                    f"(expected one of: {', '.join(sorted(_CHOICE_FIELDS))})",
                    field_lineno,
                )
            if key in fields:
                raise SceneFormatError(
                    f"duplicate field `{key}` in choice `{choice_id}`",
                    field_lineno,
                )
            fields[key] = value

        missing = _CHOICE_FIELDS - fields.keys()
        if missing:
            raise SceneFormatError(
                f"choice `{choice_id}` is missing required field(s): "
                f"{', '.join(sorted(missing))}",
                header_lineno,
            )
        return _ChoiceDraft(lineno=header_lineno, id=choice_id, fields=fields)

    def _expect_eof(self) -> None:
        self._skip_blanks_and_comments()
        if self._peek() is not None:
            raise SceneFormatError(
                f"unexpected trailing content: `{self._peek().rstrip()}`",
                self._lineno,
            )


# --- Pure helpers ---------------------------------------------------------


def _split_key_value(line: str, lineno: int) -> tuple[str, str]:
    """Split a ``key: value`` line. Strict: requires `: ` *or* `:` at EOL."""
    if ":" not in line:
        raise SceneFormatError(
            f"expected `key: value`, got `{line.rstrip()}`", lineno
        )
    key, _, value = line.partition(":")
    key = key.strip()
    if not key:
        raise SceneFormatError("empty key before `:`", lineno)
    # Allow exactly one separating space (or none, if the value is empty);
    # reject tabs to keep the format predictable.
    if value.startswith("\t"):
        raise SceneFormatError(
            "tabs are not allowed in values; use spaces", lineno
        )
    value = value.strip()
    if not value:
        raise SceneFormatError(f"empty value for key `{key}`", lineno)
    return key, value


def _is_choice_header(line: str) -> bool:
    return line.startswith("choice ") and line.rstrip().endswith(":")


def _parse_choice_header(line: str, lineno: int) -> str:
    # Format: `choice <id>:`
    body = line[len("choice "):]
    if not body.endswith(":"):
        raise SceneFormatError(
            "choice header must end with `:` (e.g. `choice c_reassure:`)",
            lineno,
        )
    cid = body[:-1].strip()
    if " " in cid or "\t" in cid:
        raise SceneFormatError(
            "choice header must be `choice <id>:` with a single identifier",
            lineno,
        )
    _validate_identifier(cid, "choice id", lineno)
    return cid


def _validate_identifier(value: str, what: str, lineno: int) -> None:
    if not value:
        raise SceneFormatError(f"{what} must not be empty", lineno)
    if value[0] not in _ID_CHARS_HEAD:
        raise SceneFormatError(
            f"{what} `{value}` must start with a letter or underscore",
            lineno,
        )
    for ch in value[1:]:
        if ch not in _ID_CHARS_TAIL:
            raise SceneFormatError(
                f"{what} `{value}` may only contain letters, digits, or `_`",
                lineno,
            )
