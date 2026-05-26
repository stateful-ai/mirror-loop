"""Local-only playtest capture, behind an explicit consent gate.

This is the storage seam for human playtest data when (and only when) a real
person sits down to play. It enforces the two things the prototype's privacy
posture and this task's acceptance criterion both require:

* **Local-only.** Every write goes through :mod:`pathlib` to a directory on this
  machine. This module imports no network modules — no ``socket``, no
  ``urllib``, no ``http``, no ``requests`` (pinned by
  ``telemetry/tests/test_telemetry.py``). A socket-sentinel test runs a complete
  capture with :func:`socket.socket` monkey-patched to raise and confirms no
  socket is ever opened. Zero bytes of captured data leave this machine.
* **Consent first.** :func:`capture_session` refuses to write without a
  ``consent.json`` already on disk for the target directory. Consent is
  recorded against the **exact list** of what this build logs
  (:data:`WHAT_IS_LOGGED`, frozen by :data:`CONSENT_SCHEMA_VERSION`), and the
  ``consent`` CLI requires an explicit ``--agree`` flag so the participant
  cannot record consent without typing it themselves.

The simulated A/B harness (:mod:`game.playtest`) captures **no participant
data**: its players are deterministic policies, not humans, so consent does not
apply there. This package is the seam a future human playtest plugs into. It
sits alongside :mod:`llmbench` as a *measurement-time-only* package: nothing in
the game runtime imports it, which is why it lives outside ``game/``/``loop/``/
``mirror/`` (those packages have a wall-clock-free, deterministic-only contract
the test in ``game/tests/test_replay.py`` pins; recording a real-world consent
timestamp is unavoidably clock-bound and so belongs out here).

The full participant-facing disclosure — what is logged, what is not, where it
lives, how to delete it — is ``docs/PLAYTEST_README.md``.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from game.instrumentation import SCHEMA_VERSION as TRACE_SCHEMA_VERSION
from game.instrumentation import SessionTrace

#: Bump if the on-disk consent record changes incompatibly. A consent file
#: stamped with another version is refused at load rather than silently
#: re-interpreted under a different "what is logged" list.
CONSENT_SCHEMA_VERSION = 1

#: Bump if the on-disk captured-session record changes incompatibly. The
#: embedded :class:`SessionTrace` carries its own version
#: (:data:`game.instrumentation.SCHEMA_VERSION`) so traces and capture envelopes
#: evolve independently.
CAPTURE_SCHEMA_VERSION = 1

#: The exact, ordered list of what this build records when capturing one
#: playtest session. A consent record references this tuple verbatim, so a
#: participant cannot consent to "logging in general" — they consent to *this*.
#: Any change here is a consent-record schema change and bumps
#: :data:`CONSENT_SCHEMA_VERSION`.
WHAT_IS_LOGGED: tuple[str, ...] = (
    "participant_id (a free-form label you choose; no real identity required)",
    "consent timestamp (UTC, ISO-8601)",
    "the world spine and variant played",
    "the run seed",
    "the input log (the choice id selected at each loop)",
    "the Mirror's per-loop transition: player-model snapshot before and after, "
    "and the ranked forecast the Mirror staked on it",
    "every adaptation that fired this loop, with its recorded provenance",
    "the rendered Reflection beat where it fired",
    "the final player-model snapshot at session end",
)

#: The explicit, ordered list of what this build does **not** record. Mirrored
#: in ``docs/PLAYTEST_README.md`` so the disclosure cannot drift from code.
WHAT_IS_NOT_LOGGED: tuple[str, ...] = (
    "no real-world identity (name, email, postal address, IP or MAC, device id)",
    "no free-form text outside the captured choice ids",
    "no system, OS, or hardware information",
    "no clock, screen, or input-event traces beyond the per-loop choice",
    "no network telemetry — nothing is ever sent off this machine",
)

#: Default location for captured data. Lives under the user's home so it is
#: never confused with the repo, and is the same place across CLI invocations.
DEFAULT_TELEMETRY_DIR = Path.home() / ".mirror-loop" / "playtest"

#: Filenames inside a telemetry directory. Kept as module-level constants so
#: tests and tooling reference one source of truth.
CONSENT_FILENAME = "consent.json"
SESSIONS_DIRNAME = "sessions"


class CaptureRefused(RuntimeError):
    """Raised when a capture is attempted without a consent record on file.

    The error message names the missing consent file and how to record one, so
    a programmatic caller can surface the disclosure path without re-deriving
    it.
    """


# --- Consent ------------------------------------------------------------------


@dataclass(frozen=True)
class Consent:
    """One participant's recorded consent to *this build's* logging.

    ``what_is_logged`` is stored verbatim from :data:`WHAT_IS_LOGGED` at the
    time of recording. A future build that logs differently bumps
    :data:`CONSENT_SCHEMA_VERSION`, so loading the old consent file fails
    loudly — that build cannot accidentally treat the older agreement as
    covering the new logging.
    """

    participant_id: str
    consented_at: str  # ISO-8601 UTC
    what_is_logged: tuple[str, ...]
    schema_version: int = CONSENT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "participant_id": self.participant_id,
            "consented_at": self.consented_at,
            "what_is_logged": list(self.what_is_logged),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Consent":
        version = data.get("schema_version")
        if version != CONSENT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported consent schema version {version!r} "
                f"(this build writes/reads v{CONSENT_SCHEMA_VERSION}); "
                "the participant must record fresh consent against the current "
                "WHAT_IS_LOGGED list"
            )
        return cls(
            participant_id=data["participant_id"],
            consented_at=data["consented_at"],
            what_is_logged=tuple(data["what_is_logged"]),
            schema_version=version,
        )


def _now_iso(clock: Callable[[], datetime] | None = None) -> str:
    """The current UTC time as a stable ISO-8601 string (no microseconds)."""
    now = clock() if clock is not None else datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def record_consent(
    directory: Path | str,
    *,
    participant_id: str,
    clock: Callable[[], datetime] | None = None,
) -> Consent:
    """Write ``consent.json`` for ``participant_id`` to ``directory``.

    The directory is created on demand. The consent is recorded against the
    current :data:`WHAT_IS_LOGGED`; if the build's logging changes,
    :data:`CONSENT_SCHEMA_VERSION` bumps and old consent files no longer load.
    """
    if not participant_id.strip():
        raise ValueError("participant_id must be a non-empty label")
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    consent = Consent(
        participant_id=participant_id,
        consented_at=_now_iso(clock),
        what_is_logged=WHAT_IS_LOGGED,
    )
    (target / CONSENT_FILENAME).write_text(
        json.dumps(consent.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return consent


def load_consent(directory: Path | str) -> Consent | None:
    """Return the consent on file at ``directory``, or ``None`` if there is none."""
    path = Path(directory) / CONSENT_FILENAME
    if not path.exists():
        return None
    return Consent.from_dict(json.loads(path.read_text(encoding="utf-8")))


def revoke_consent(directory: Path | str) -> bool:
    """Delete ``consent.json`` from ``directory``.

    Returns ``True`` if a consent record was removed, ``False`` if there was
    none. Captured session files are **not** touched — deleting them is a
    separate, deliberate act the README documents (``rm -r <dir>``), so
    revoking consent never silently destroys data a participant may want to
    review or take with them.
    """
    path = Path(directory) / CONSENT_FILENAME
    if not path.exists():
        return False
    path.unlink()
    return True


# --- Capture ------------------------------------------------------------------


def _session_id_from_trace(trace: SessionTrace) -> str:
    """A short, deterministic filename stem for ``trace``.

    Built from the trace's own determinism digest, so capturing the same
    session twice writes the same file (idempotent) and never produces a
    timestamped, ever-growing duplicate.
    """
    digest = trace.state_hash().split(":", 1)[-1]
    return digest[:16]


def capture_session(
    directory: Path | str,
    trace: SessionTrace,
    *,
    session_id: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Path:
    """Write ``trace`` to a local file inside ``directory/sessions/``.

    Refuses with :class:`CaptureRefused` if no consent is on file at
    ``directory``. The capture envelope records the participant id from the
    consent record, the capture timestamp, and the schema version of the
    embedded :class:`SessionTrace`, so a captured file is self-describing.

    Writes are **strictly local**: this function calls only
    :class:`pathlib.Path` writers. Nothing in this module imports a network
    module (see ``telemetry/tests/test_telemetry.py``).
    """
    target_dir = Path(directory)
    consent = load_consent(target_dir)
    if consent is None:
        raise CaptureRefused(
            f"no consent on file at {target_dir / CONSENT_FILENAME}; capture "
            "refused. See docs/PLAYTEST_README.md and run "
            "`python -m telemetry consent --participant <label> --agree` "
            "first."
        )
    sessions_dir = target_dir / SESSIONS_DIRNAME
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sid = session_id or _session_id_from_trace(trace)
    out = sessions_dir / f"{sid}.json"
    payload = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "participant_id": consent.participant_id,
        "captured_at": _now_iso(clock),
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "trace": trace.to_dict(),
    }
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def list_captured(directory: Path | str) -> list[Path]:
    """Return all captured-session files in ``directory``, in stable order."""
    sessions_dir = Path(directory) / SESSIONS_DIRNAME
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("*.json"))


# --- Static guarantee: this module touches no network modules ----------------

#: The forbidden network-module names. The static check below walks this
#: module's own AST and asserts none of them appear in any ``import``
#: statement, so the local-only guarantee cannot regress on a careless edit.
_FORBIDDEN_NETWORK_MODULES: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "http",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
    }
)


def imported_module_roots(module_source: str) -> set[str]:
    """Return the set of top-level module names that ``module_source`` imports.

    Used by the local-only guarantee test (and by anything else that wants to
    audit a module's imports) — it parses the source with :mod:`ast` rather
    than scanning text, so docstring mentions of e.g. ``socket`` don't trip it.
    """
    tree = ast.parse(module_source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue  # ``from . import x`` — package-relative, no module root
            roots.add(node.module.split(".", 1)[0])
    return roots


# --- CLI ----------------------------------------------------------------------


def _print_disclosure(stream) -> None:
    """Print the participant-facing disclosure block.

    The text is generated from :data:`WHAT_IS_LOGGED` /
    :data:`WHAT_IS_NOT_LOGGED` so the CLI disclosure cannot drift from the
    code or the README.
    """
    print("Mirror Loop — local playtest capture disclosure", file=stream)
    print("", file=stream)
    print("What is logged (and stays on this machine):", file=stream)
    for item in WHAT_IS_LOGGED:
        print(f"  - {item}", file=stream)
    print("", file=stream)
    print("What is not logged:", file=stream)
    for item in WHAT_IS_NOT_LOGGED:
        print(f"  - {item}", file=stream)
    print("", file=stream)
    print(
        "Nothing is ever sent over the network. Files are written to the "
        "directory printed below and you can delete them yourself at any time.",
        file=stream,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m telemetry",
        description=(
            "Local-only playtest telemetry: record consent, list captured "
            "sessions, revoke. All data stays on this machine."
        ),
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_TELEMETRY_DIR,
        help=f"telemetry directory (default {DEFAULT_TELEMETRY_DIR})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    consent = sub.add_parser(
        "consent",
        help="record participant consent (or print the disclosure)",
    )
    consent.add_argument(
        "--participant",
        required=True,
        help="a free-form label for this participant (no real identity)",
    )
    consent.add_argument(
        "--agree",
        action="store_true",
        help=(
            "explicitly agree to the disclosure printed by the no-flag form. "
            "Required: without it the consent is *not* recorded."
        ),
    )

    sub.add_parser("status", help="show whether consent is on file and how many sessions captured")
    sub.add_parser("revoke", help="remove the consent record (captured sessions are kept)")
    sub.add_parser("where", help="print the telemetry directory path")
    sub.add_parser(
        "disclosure",
        help="print the participant-facing disclosure and exit",
    )

    args = parser.parse_args(argv)
    target_dir: Path = args.dir

    if args.cmd == "disclosure":
        _print_disclosure(sys.stdout)
        return 0

    if args.cmd == "where":
        print(target_dir)
        return 0

    if args.cmd == "consent":
        if not args.agree:
            _print_disclosure(sys.stdout)
            print(
                "\nTo record consent for "
                f"{args.participant!r}, re-run with `--agree`. Without --agree, "
                "no consent has been recorded "
                f"(target: {target_dir / CONSENT_FILENAME})."
            )
            return 1
        consent_rec = record_consent(target_dir, participant_id=args.participant)
        print(
            f"recorded consent for {consent_rec.participant_id!r} at "
            f"{consent_rec.consented_at} -> {target_dir / CONSENT_FILENAME}"
        )
        return 0

    if args.cmd == "status":
        existing = load_consent(target_dir)
        captured = list_captured(target_dir)
        print(f"directory       : {target_dir}")
        if existing is None:
            print("consent         : none on file")
            print(f"captured        : {len(captured)} session(s)")
            return 1
        print(
            f"consent         : participant={existing.participant_id!r} "
            f"recorded {existing.consented_at}"
        )
        print(f"captured        : {len(captured)} session(s)")
        return 0

    if args.cmd == "revoke":
        removed = revoke_consent(target_dir)
        if removed:
            print(
                f"revoked consent at {target_dir / CONSENT_FILENAME}. Any "
                f"captured session files in {target_dir / SESSIONS_DIRNAME} "
                "are kept; delete that directory yourself to remove them."
            )
            return 0
        print(
            f"nothing to revoke: no consent on file at "
            f"{target_dir / CONSENT_FILENAME}"
        )
        return 1

    # argparse's ``required=True`` on the subparser makes this unreachable, but
    # be explicit so a future subcommand addition fails noisily if forgotten.
    raise AssertionError(f"unhandled subcommand: {args.cmd!r}")


__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "CONSENT_FILENAME",
    "CONSENT_SCHEMA_VERSION",
    "CaptureRefused",
    "Consent",
    "DEFAULT_TELEMETRY_DIR",
    "SESSIONS_DIRNAME",
    "WHAT_IS_LOGGED",
    "WHAT_IS_NOT_LOGGED",
    "capture_session",
    "imported_module_roots",
    "list_captured",
    "load_consent",
    "main",
    "record_consent",
    "revoke_consent",
]
