"""Commit-time guard: reject diffs with no source change or with compiled artifacts.

This is the build-pipeline gate (see :mod:`ci`). It enforces two independent
invariants on the diff a coding task is about to merge:

* ``NO_SOURCE_DIFF`` — at least one path in the diff must be a real source
  file (anything that isn't a compiled / generated build artifact). A diff
  that touches *only* artifacts means the task produced no source change and
  must not be marked completed.
* ``BYTECODE_COMMITTED`` — no path in the diff may *add or modify* a compiled
  artifact (``.pyc``/``.pyo``/``.pyd``/``.so``/``.class`` files, anything
  inside ``__pycache__/``, ``*.egg-info/``, ``dist/``, ``build/``, the cache
  dirs ``.pytest_cache/``/``.mypy_cache/``/``.ruff_cache/``, or
  ``node_modules/``). A pure cleanup PR that only **deletes** previously
  committed artifacts is fine — that is exactly how a future fix would look.

The motivating regression is PR #2: four files added, every one of them a
``.pyc`` under ``__pycache__/`` with 0 additions / 0 deletions. That diff
fires both invariants.

The check is split into a pure core (:func:`inspect_diff` over a list of
:class:`DiffEntry`) and a small ``git``-shelling wrapper (:func:`main`), so the
gate logic can be unit-tested without spinning up a real repo on every case.

Run from a checkout::

    python -m ci.commit_guard                # HEAD vs origin/main (or main)
    python -m ci.commit_guard --base main    # HEAD vs main
    python -m ci.commit_guard main..HEAD     # explicit refspec

Exit code is ``0`` when the diff passes both invariants, ``1`` when it is
rejected, ``2`` on usage error or when ``git`` cannot be invoked — mirroring
``python -m acceptance.predictability`` and ``python -m guardrails``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Sequence

# --- What counts as a compiled / generated build artifact --------------------
#
# Kept in sync with the project ``.gitignore`` — the gate is the executable
# enforcement of the same "build artifacts/bytecode are never committed" rule
# that file documents. New entries here should land in ``.gitignore`` too.

COMPILED_ARTIFACT_SUFFIXES: frozenset[str] = frozenset(
    {
        # Python bytecode / native extensions (the PR #2 case).
        ".pyc",
        ".pyo",
        ".pyd",
        # Compiled shared / object code (C extensions, native builds).
        ".so",
        ".o",
        ".a",
        ".dylib",
        ".dll",
        # JVM bytecode (not used today; cheap insurance).
        ".class",
    }
)

# Directory *segments* (matched anywhere in the path) that only ever contain
# generated output. Any file beneath one of these is treated as an artifact
# regardless of suffix.
COMPILED_ARTIFACT_DIR_SEGMENTS: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
    }
)

# Suffixes for whole directory *names* (rather than fixed names). ``foo.egg-info/``
# is a generated metadata directory; we match by suffix so any package's
# ``*.egg-info`` is covered without enumeration.
_COMPILED_ARTIFACT_DIR_NAME_SUFFIXES: tuple[str, ...] = (".egg-info",)


def is_compiled_artifact(path: str) -> bool:
    """Return ``True`` if ``path`` is a compiled / generated build artifact.

    Uses POSIX path semantics so the check behaves the same on every platform
    ``git diff`` might be invoked from (``git`` always reports forward slashes).
    """
    p = PurePosixPath(path)
    if p.suffix in COMPILED_ARTIFACT_SUFFIXES:
        return True
    for part in p.parts:
        if part in COMPILED_ARTIFACT_DIR_SEGMENTS:
            return True
        if any(part.endswith(suf) for suf in _COMPILED_ARTIFACT_DIR_NAME_SUFFIXES):
            return True
    return False


# --- Diff model --------------------------------------------------------------


@dataclass(frozen=True)
class DiffEntry:
    """One file in a diff, as reported by ``git diff --name-status``.

    ``status`` is the porcelain status letter (``A``/``M``/``D``/``T``, or
    ``R``/``C`` for renames/copies). For renames and copies, ``path`` is the
    **destination** path — that is the file the PR is *adding to the tree*,
    which is the one the gate cares about. The original (deleted) source of a
    rename is exposed as a separate ``D`` entry only when callers choose to
    expand it; the rename target alone is enough to enforce both invariants.
    """

    status: str
    path: str

    def __post_init__(self) -> None:
        if not self.status:
            raise ValueError("DiffEntry.status must not be empty")
        if not self.path:
            raise ValueError("DiffEntry.path must not be empty")

    @property
    def is_addition_or_modification(self) -> bool:
        """``True`` when this entry adds content to the tree (A/M/R/C/T)."""
        # ``D`` is the only status that does not introduce content; everything
        # else (including ``R``/``C`` rename/copy *destinations* and ``T`` type
        # changes) means a file is present in HEAD with this content.
        return self.status[0].upper() != "D"


@dataclass(frozen=True)
class CommitGuardViolation:
    """One broken commit-guard invariant.

    ``invariant`` is a stable id (``NO_SOURCE_DIFF`` / ``BYTECODE_COMMITTED``)
    so reports and CI logs can be grepped without parsing prose.
    """

    invariant: str
    message: str
    paths: tuple[str, ...] = ()

    def render(self) -> str:
        base = f"[ERROR  ] {self.invariant}: {self.message}"
        if not self.paths:
            return base
        return base + "\n" + "\n".join(f"  - {p}" for p in self.paths)


@dataclass(frozen=True)
class CommitGuardReport:
    """Outcome of inspecting a diff: every guard-invariant it broke (if any).

    The diff itself is preserved so the report is self-describing: a passing
    report names the source files that satisfied the source-diff check, and a
    failing report names the offending artifacts.
    """

    diff: tuple[DiffEntry, ...]
    violations: tuple[CommitGuardViolation, ...]

    @property
    def ok(self) -> bool:
        """``True`` when the diff passes every invariant. Never merges otherwise."""
        return not self.violations

    @property
    def source_paths(self) -> tuple[str, ...]:
        """Diff entries that are not compiled artifacts (the 'real' changes)."""
        return tuple(e.path for e in self.diff if not is_compiled_artifact(e.path))

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        """Diff entries that *are* compiled artifacts (regardless of status)."""
        return tuple(e.path for e in self.diff if is_compiled_artifact(e.path))

    def render(self) -> str:
        verdict = "OK" if self.ok else "REJECTED"
        header = (
            f"[{verdict}] commit guard: {len(self.diff)} changed file(s), "
            f"{len(self.violations)} violation(s)"
        )
        lines = [header]
        for v in self.violations:
            lines.append(v.render())
        if self.ok and self.source_paths:
            lines.append("  source changes:")
            for p in self.source_paths:
                lines.append(f"    - {p}")
        return "\n".join(lines)


# --- Parser for ``git diff --name-status`` output ----------------------------


def parse_name_status(text: str) -> tuple[DiffEntry, ...]:
    """Parse ``git diff --name-status`` (or ``--name-status -z``-stripped) output.

    ``git diff --name-status`` lines look like::

        A\tpath/to/added.py
        M\tpath/to/changed.py
        D\tpath/to/removed.py
        R092\told/path.py\tnew/path.py
        C075\torig.py\tcopy.py

    For ``R``/``C`` we keep the **destination** path (the file the diff is
    adding to the tree) — that is what the gate inspects. Blank lines are
    ignored so callers can feed in raw subprocess output without trimming.
    """
    entries: list[DiffEntry] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            # Defensive: a malformed line is more useful as a single error than
            # as a silent skip. We surface it via the status letter so callers
            # can see it in the report.
            raise ValueError(f"unparseable git --name-status line: {raw_line!r}")
        status = fields[0]
        if status[:1].upper() in {"R", "C"}:
            if len(fields) < 3:
                raise ValueError(
                    f"rename/copy status without destination path: {raw_line!r}"
                )
            destination = fields[-1]
            entries.append(DiffEntry(status=status, path=destination))
        else:
            entries.append(DiffEntry(status=status, path=fields[1]))
    return tuple(entries)


# --- The gate ----------------------------------------------------------------


_NO_SOURCE_DIFF_MSG = (
    "diff contains no source-file changes; the only paths touched are compiled "
    "or generated artifacts. A coding task with this diff has not actually "
    "produced source code and must not be marked completed."
)

_EMPTY_DIFF_MSG = (
    "diff is empty; no files changed between the base ref and HEAD. A coding "
    "task with this diff has not produced any change and must not be marked "
    "completed."
)

_BYTECODE_COMMITTED_MSG = (
    "diff adds or modifies compiled / generated build artifacts. These must "
    "never be committed (see .gitignore); the path(s) below are blocking the "
    "merge."
)


def inspect_diff(entries: Iterable[DiffEntry]) -> CommitGuardReport:
    """Apply both commit-guard invariants to a diff. Pure; the unit of test.

    Order of the returned violations is stable: ``NO_SOURCE_DIFF`` (if any)
    first, then ``BYTECODE_COMMITTED`` (if any). Both fire independently on
    PR #2's diff, which is the regression case.
    """
    diff = tuple(entries)
    violations: list[CommitGuardViolation] = []

    # NO_SOURCE_DIFF — empty diff and "artifacts-only" diff are both failures,
    # but they get distinct messages because the cause and the fix differ.
    source_paths = tuple(e.path for e in diff if not is_compiled_artifact(e.path))
    if not diff:
        violations.append(
            CommitGuardViolation(
                invariant="NO_SOURCE_DIFF",
                message=_EMPTY_DIFF_MSG,
            )
        )
    elif not source_paths:
        violations.append(
            CommitGuardViolation(
                invariant="NO_SOURCE_DIFF",
                message=_NO_SOURCE_DIFF_MSG,
                paths=tuple(e.path for e in diff),
            )
        )

    # BYTECODE_COMMITTED — only flag *additions/modifications* of artifacts; a
    # PR that deletes accidentally-committed bytecode is the cleanup we want.
    bad_artifacts = tuple(
        e.path
        for e in diff
        if is_compiled_artifact(e.path) and e.is_addition_or_modification
    )
    if bad_artifacts:
        violations.append(
            CommitGuardViolation(
                invariant="BYTECODE_COMMITTED",
                message=_BYTECODE_COMMITTED_MSG,
                paths=bad_artifacts,
            )
        )

    return CommitGuardReport(diff=diff, violations=tuple(violations))


# --- CLI / git integration ---------------------------------------------------


class GitInvocationError(RuntimeError):
    """Raised when ``git`` cannot be invoked or returns a non-zero status."""


def _run_git(args: Sequence[str], *, cwd: str | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise GitInvocationError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise GitInvocationError(
            f"git {' '.join(args)} failed ({exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    return completed.stdout


def _resolve_default_base(cwd: str | None = None) -> str:
    """Pick the base ref to diff against when the caller doesn't specify one.

    Prefers ``origin/main`` (the canonical CI base), falls back to local
    ``main``. Raises :class:`GitInvocationError` if neither exists — the
    caller is expected to pass ``--base`` explicitly in that case.
    """
    for candidate in ("origin/main", "main"):
        try:
            _run_git(["rev-parse", "--verify", "--quiet", candidate], cwd=cwd)
            return candidate
        except GitInvocationError:
            continue
    raise GitInvocationError(
        "could not resolve a default base ref (tried origin/main, main); "
        "pass --base <ref> explicitly"
    )


def collect_diff(base: str, *, head: str = "HEAD", cwd: str | None = None) -> tuple[DiffEntry, ...]:
    """Collect the diff between ``base`` and ``head`` using ``git diff --name-status``.

    ``base`` may be a ref (``main``, ``origin/main``) or a refspec
    (``main..HEAD``). When ``base`` already contains ``..`` it is passed
    through unchanged so callers can disambiguate two-dot vs three-dot diffs.
    """
    if ".." in base:
        ref_arg = base
    else:
        ref_arg = f"{base}..{head}"
    raw = _run_git(["diff", "--name-status", ref_arg], cwd=cwd)
    return parse_name_status(raw)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ci.commit_guard",
        description=(
            "Reject diffs that have no source change or that commit compiled "
            "artifacts (.pyc, __pycache__/, *.egg-info/, dist/, build/, ...)."
        ),
    )
    parser.add_argument(
        "refspec",
        nargs="?",
        help=(
            "Refspec to diff (e.g. 'main..HEAD'). If omitted, the diff is "
            "computed between --base and HEAD."
        ),
    )
    parser.add_argument(
        "--base",
        default=None,
        help=(
            "Base ref to diff HEAD against. Defaults to origin/main, then main."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.refspec and args.base:
        parser.error("pass a refspec positionally OR --base, not both")

    try:
        if args.refspec:
            diff = collect_diff(args.refspec)
        else:
            base = args.base or _resolve_default_base()
            diff = collect_diff(base)
    except GitInvocationError as exc:
        print(f"commit-guard: {exc}", file=sys.stderr)
        return 2

    report = inspect_diff(diff)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
