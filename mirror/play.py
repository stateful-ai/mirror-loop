"""``python -m mirror play`` — run the intake questionnaire and emit its log.

The play command opens with the lab questionnaire (``docs/INTAKE.md``): five
multiple-choice questions whose answers reduce into the starting
:class:`~mirror.state.MirrorState`. Two modes share one code path so the
emitted log is byte-identical regardless of how the answers got collected:

* **Interactive** (default) — prompt the player on **stderr**, read answers
  from stdin. Stdout stays clean for the JSON log so the command remains
  pipe-friendly even mid-prompt.
* **Non-interactive** (``--answers FILE``) — load ``{question_id: answer_id}``
  from a JSON file. **No TTY**, no prompts, no stderr chatter — the mode CI and
  fixture capture use, and the one that satisfies "runs with no TTY prompt and
  yields the same log as the scripted interactive run".

Both modes feed the same :func:`mirror.intake.seed_log`, so the emitted log is
a pure function of the answer set. The output is the JSON-serialized
:class:`~mirror.log.EventLog` (``EventLog.to_json``) — the same shape an
intake-only ``EventLog`` already serializes to elsewhere in the codebase, so a
downstream consumer round-trips it through :meth:`EventLog.from_json` with no
new format to learn.

``--seed`` is accepted for forward compatibility with the broader
``python -m mirror play --seed N`` north-star command
(``docs/mirror_loop_m1_founder_brief.md``); intake itself is deterministic
from the answers alone, so the seed does not affect the emitted intake log.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from mirror.intake import QUESTIONNAIRE, seed_log


def load_answers(path: str | Path) -> dict[str, str]:
    """Load and validate a ``{question_id: answer_id}`` JSON file.

    The shape is what ``docs/INTAKE.md`` §2 pins: a flat JSON object whose
    keys and values are strings. Anything else — a list at the root, a nested
    value, a non-string key — is rejected with a precise message so a malformed
    fixture fails fast rather than silently producing an empty intake. The
    *semantic* validation (unknown question id, unknown answer id) is deferred
    to :func:`mirror.intake.encode`, which already raises ``KeyError`` with a
    helpful message and is the single source of truth for that rule.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"answers file {str(path)!r} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"answers file {str(path)!r} must be a JSON object mapping "
            f"question_id -> answer_id; got {type(data).__name__}"
        )
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(
                f"answers file {str(path)!r} must map string question_id -> "
                f"string answer_id; got {key!r} -> {value!r}"
            )
    return dict(data)


def prompt_answers(
    *,
    read_line: Callable[[], str] | None = None,
    write: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Walk :data:`~mirror.intake.QUESTIONNAIRE` on the TTY and return the answers.

    Each question is rendered with numbered options via ``write`` (defaulting
    to stderr so stdout stays clean for the JSON log). The player types a
    digit, or blank to skip. ``read_line`` reads one line from stdin including
    the trailing newline; an empty string signals EOF and is treated as an
    intentional close — the loop raises ``EOFError`` so a non-interactive
    caller that forgot ``--answers`` fails loudly rather than silently emitting
    an empty log.
    """
    if read_line is None:
        read_line = sys.stdin.readline
    if write is None:
        def write(text: str) -> None:  # type: ignore[misc]
            print(text, end="", file=sys.stderr, flush=True)

    answers: dict[str, str] = {}
    for question in QUESTIONNAIRE:
        write(f"\n{question.prompt}\n")
        options = list(question.answers)
        for i, (answer_id, _signals) in enumerate(options, start=1):
            write(f"  {i}. {answer_id}\n")
        write("  (blank to skip)\n")
        while True:
            write(f"choose 1-{len(options)}: ")
            line = read_line()
            if line == "":
                raise EOFError(
                    f"stdin closed before answering {question.id!r}; "
                    "use `--answers <file>` for non-interactive runs"
                )
            raw = line.rstrip("\n").strip()
            if raw == "":
                break  # skipped: emit no event for this question
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                answers[question.id] = options[int(raw) - 1][0]
                break
            write("  (enter the number of a listed answer, or blank to skip)\n")
    return answers


def run(
    *,
    seed: int = 0,
    answers_path: str | Path | None = None,
    answers: Mapping[str, str] | None = None,
    read_line: Callable[[], str] | None = None,
    write: Callable[[str], None] | None = None,
) -> str:
    """Run the intake and return the event log as canonical JSON.

    Selects one of three answer sources, in priority order: an
    ``answers_path`` (the ``--answers FILE`` mode), an explicit ``answers``
    mapping (used by tests), or the interactive prompt loop. Passing both
    ``answers_path`` and ``answers`` is a misuse and raises ``ValueError`` —
    the call site has to commit to one source so the run stays deterministic.

    ``seed`` is accepted and held so the signature lines up with the broader
    ``python -m mirror play --seed N`` command; intake is deterministic from
    the answers alone (``mirror.intake.encode`` is pure), so the value does
    not affect the emitted intake log today.
    """
    if answers_path is not None and answers is not None:
        raise ValueError(
            "pass either answers_path or answers, not both; the call site must "
            "commit to one source so the run stays deterministic"
        )
    if answers_path is not None:
        collected: Mapping[str, str] = load_answers(answers_path)
    elif answers is not None:
        collected = dict(answers)
    else:
        collected = prompt_answers(read_line=read_line, write=write)
    _ = seed  # reserved for the gameplay phase; see module docstring
    return seed_log(collected).to_json()
