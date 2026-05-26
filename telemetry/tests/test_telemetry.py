"""Tests for ``telemetry`` — the local-only, consent-gated playtest capture seam.

These pin the two guarantees ``docs/PLAYTEST_README.md`` is the contract for:

1. **Local-only / zero network egress.** The module imports no network
   modules (parsed from its own AST, not text-grepped), and a complete capture
   runs under a monkey-patched-socket sentinel without opening a socket.
2. **Consent first.** ``capture_session`` refuses without a consent record;
   the consent CLI requires ``--agree`` explicitly; the consent record carries
   the exact ``WHAT_IS_LOGGED`` list and rejects an unknown schema version.

Also pinned: README/code agreement on what is (and is not) logged, so the
participant-facing disclosure cannot drift from the constants.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

import telemetry
from game.instrumentation import canonical_trace, record_session
from telemetry import (
    CAPTURE_SCHEMA_VERSION,
    CONSENT_FILENAME,
    CONSENT_SCHEMA_VERSION,
    DEFAULT_TELEMETRY_DIR,
    SESSIONS_DIRNAME,
    WHAT_IS_LOGGED,
    WHAT_IS_NOT_LOGGED,
    CaptureRefused,
    Consent,
    capture_session,
    imported_module_roots,
    list_captured,
    load_consent,
    main as telemetry_main,
    record_consent,
    revoke_consent,
)


# --- Local-only guarantee: static + dynamic ----------------------------------


_FORBIDDEN_NETWORK_MODULES = telemetry._FORBIDDEN_NETWORK_MODULES


def test_telemetry_module_imports_no_network_modules():
    """Static guarantee: ``telemetry/__init__.py`` does not import any networking module.

    Parsed with ``ast`` rather than scanned as text, so a docstring mention of
    e.g. ``socket`` doesn't trip the check.
    """
    source = Path(telemetry.__file__).read_text(encoding="utf-8")
    roots = imported_module_roots(source)
    offenders = roots & _FORBIDDEN_NETWORK_MODULES
    assert not offenders, f"telemetry imports forbidden module(s): {sorted(offenders)}"


def test_capture_does_not_touch_a_socket(tmp_path, monkeypatch):
    """Dynamic guarantee: a full consent+capture flow opens no socket."""
    sentinel_calls: list[tuple] = []

    def _fail_socket(*args, **kwargs):
        sentinel_calls.append(("socket", args, kwargs))
        raise RuntimeError("network egress attempted from local-only telemetry")

    def _fail_connection(*args, **kwargs):
        sentinel_calls.append(("create_connection", args, kwargs))
        raise RuntimeError("network egress attempted from local-only telemetry")

    monkeypatch.setattr(socket, "socket", _fail_socket)
    monkeypatch.setattr(socket, "create_connection", _fail_connection)

    record_consent(tmp_path, participant_id="alice")
    trace = canonical_trace()
    out = capture_session(tmp_path, trace)

    assert out.exists()
    assert sentinel_calls == [], (
        f"telemetry opened a socket during capture: {sentinel_calls}"
    )


# --- Consent: round-trip, schema, refusal ------------------------------------


def test_record_consent_writes_local_file(tmp_path):
    consent = record_consent(tmp_path, participant_id="alice")
    consent_file = tmp_path / CONSENT_FILENAME
    assert consent_file.exists()
    data = json.loads(consent_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == CONSENT_SCHEMA_VERSION
    assert data["participant_id"] == "alice"
    assert tuple(data["what_is_logged"]) == WHAT_IS_LOGGED
    # The returned dataclass matches what was persisted.
    assert consent.participant_id == "alice"
    assert consent.what_is_logged == WHAT_IS_LOGGED


def test_record_consent_uses_injected_clock(tmp_path):
    fixed = datetime(2026, 5, 25, 12, 34, 56, tzinfo=timezone.utc)
    consent = record_consent(tmp_path, participant_id="alice", clock=lambda: fixed)
    assert consent.consented_at == "2026-05-25T12:34:56+00:00"


def test_record_consent_rejects_empty_or_whitespace_participant(tmp_path):
    with pytest.raises(ValueError, match="participant_id"):
        record_consent(tmp_path, participant_id="")
    with pytest.raises(ValueError, match="participant_id"):
        record_consent(tmp_path, participant_id="   ")
    # And nothing was written on rejection.
    assert not (tmp_path / CONSENT_FILENAME).exists()


def test_load_consent_returns_none_when_missing(tmp_path):
    assert load_consent(tmp_path) is None


def test_load_consent_rejects_unknown_schema_version(tmp_path):
    (tmp_path / CONSENT_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": CONSENT_SCHEMA_VERSION + 1,
                "participant_id": "alice",
                "consented_at": "2026-05-25T00:00:00+00:00",
                "what_is_logged": list(WHAT_IS_LOGGED),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="consent schema version"):
        load_consent(tmp_path)


def test_consent_round_trips_through_dict():
    consent = Consent(
        participant_id="alice",
        consented_at="2026-05-25T00:00:00+00:00",
        what_is_logged=WHAT_IS_LOGGED,
    )
    assert Consent.from_dict(consent.to_dict()) == consent


def test_revoke_consent_returns_true_only_when_something_removed(tmp_path):
    assert revoke_consent(tmp_path) is False
    record_consent(tmp_path, participant_id="alice")
    assert revoke_consent(tmp_path) is True
    assert load_consent(tmp_path) is None
    # Idempotent: second call is a no-op (returns False).
    assert revoke_consent(tmp_path) is False


def test_revoke_consent_does_not_touch_captured_sessions(tmp_path):
    record_consent(tmp_path, participant_id="alice")
    captured = capture_session(tmp_path, canonical_trace())
    assert captured.exists()
    revoke_consent(tmp_path)
    # Session file is kept by design — the README documents this.
    assert captured.exists()


# --- Capture: refusal, success, idempotency ----------------------------------


def test_capture_refused_without_consent(tmp_path):
    trace = canonical_trace()
    with pytest.raises(CaptureRefused, match="no consent"):
        capture_session(tmp_path, trace)
    # No partial output left behind.
    assert not (tmp_path / SESSIONS_DIRNAME).exists()


def test_capture_writes_envelope_with_trace_and_participant(tmp_path):
    record_consent(tmp_path, participant_id="alice")
    trace = canonical_trace()
    out = capture_session(tmp_path, trace)
    assert out.parent == tmp_path / SESSIONS_DIRNAME
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
    assert payload["participant_id"] == "alice"
    # The embedded trace is the trace exactly — we serialize through the
    # trace's own to_dict so the captured form round-trips against from_dict.
    assert payload["trace"] == trace.to_dict()
    from game.instrumentation import SessionTrace

    assert SessionTrace.from_dict(payload["trace"]) == trace


def test_capture_filename_is_deterministic_and_idempotent(tmp_path):
    record_consent(tmp_path, participant_id="alice")
    trace = canonical_trace()
    first = capture_session(tmp_path, trace)
    second = capture_session(tmp_path, trace)
    assert first == second
    assert list_captured(tmp_path) == [first]


def test_capture_distinguishes_distinct_sessions(tmp_path):
    record_consent(tmp_path, participant_id="alice")
    one = canonical_trace()
    # A different input log produces a different trace and so a different file.
    # The defiance pick at every slot — a different input log than the
    # canonical kind log, so the resulting trace (and its filename) differ.
    other = record_session(("c_refuse", "c_breach", "c_doors", "c_walk", "c_break"))
    a = capture_session(tmp_path, one)
    b = capture_session(tmp_path, other)
    assert a != b
    assert set(list_captured(tmp_path)) == {a, b}


def test_capture_uses_explicit_session_id_when_given(tmp_path):
    record_consent(tmp_path, participant_id="alice")
    out = capture_session(
        tmp_path, canonical_trace(), session_id="custom-label"
    )
    assert out.name == "custom-label.json"


def test_list_captured_returns_empty_when_no_directory(tmp_path):
    assert list_captured(tmp_path) == []


# --- README / code agreement -------------------------------------------------


_README_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "PLAYTEST_README.md"
)


def test_readme_exists_and_states_local_only_and_consent():
    text = _README_PATH.read_text(encoding="utf-8")
    # The two acceptance criteria are stated unambiguously.
    assert "Local-only" in text
    assert "Consent first" in text
    # The README references the implementing package and test file, so a
    # reader can verify the guarantees from the prose alone.
    assert "telemetry/__init__.py" in text or "telemetry/" in text
    assert "telemetry/tests/test_telemetry.py" in text


def _readme_text() -> str:
    """The README with markdown bold (``**``) stripped, lowercased.

    Lets bullet entries match regardless of whether the README bolds the
    leading clause for emphasis (e.g. ``**No free-form text**``). Underscores
    are preserved so identifiers like ``participant_id`` match verbatim.
    """
    return _README_PATH.read_text(encoding="utf-8").lower().replace("**", "")


def test_readme_lists_every_what_is_logged_entry():
    text = _readme_text()
    for item in WHAT_IS_LOGGED:
        # Match on the first clause (up to a comma or parenthesis) so the README
        # can phrase each bullet naturally without verbatim-pinning every word.
        head = item.split("(")[0].split(",")[0].strip().lower()
        assert head in text, f"README is missing WHAT_IS_LOGGED entry: {head!r}"


def test_readme_lists_every_what_is_not_logged_category():
    text = _readme_text()
    for item in WHAT_IS_NOT_LOGGED:
        head = item.split("(")[0].split(",")[0].split(" — ")[0].strip().lower()
        assert head in text, f"README is missing WHAT_IS_NOT_LOGGED entry: {head!r}"


def test_default_dir_lives_under_user_home():
    # The default storage location stays under $HOME so a participant always
    # knows where their data is and ``rm -r`` it themselves.
    assert DEFAULT_TELEMETRY_DIR.is_absolute()
    assert Path.home() in DEFAULT_TELEMETRY_DIR.parents


# --- CLI ---------------------------------------------------------------------


def test_cli_disclosure_prints_what_is_logged(capsys):
    code = telemetry_main(["disclosure"])
    assert code == 0
    out = capsys.readouterr().out
    for item in WHAT_IS_LOGGED:
        head = item.split("(")[0].split(",")[0].strip()
        assert head in out
    for item in WHAT_IS_NOT_LOGGED:
        head = item.split("(")[0].split(",")[0].strip()
        assert head in out


def test_cli_where_prints_target_dir(tmp_path, capsys):
    code = telemetry_main(["--dir", str(tmp_path), "where"])
    assert code == 0
    assert capsys.readouterr().out.strip() == str(tmp_path)


def test_cli_status_with_no_consent_exits_nonzero(tmp_path, capsys):
    code = telemetry_main(["--dir", str(tmp_path), "status"])
    assert code == 1
    assert "none on file" in capsys.readouterr().out


def test_cli_consent_without_agree_records_nothing(tmp_path, capsys):
    code = telemetry_main(
        ["--dir", str(tmp_path), "consent", "--participant", "alice"]
    )
    assert code == 1
    out = capsys.readouterr().out
    # The disclosure was printed (so the participant saw what they would consent to)
    assert "What is logged" in out
    # And nothing was written.
    assert load_consent(tmp_path) is None
    assert not (tmp_path / CONSENT_FILENAME).exists()


def test_cli_consent_with_agree_records(tmp_path, capsys):
    code = telemetry_main(
        ["--dir", str(tmp_path), "consent", "--participant", "alice", "--agree"]
    )
    assert code == 0
    assert "recorded consent" in capsys.readouterr().out
    consent = load_consent(tmp_path)
    assert consent is not None
    assert consent.participant_id == "alice"
    assert consent.what_is_logged == WHAT_IS_LOGGED


def test_cli_status_after_consent_shows_participant_and_count(tmp_path, capsys):
    telemetry_main(
        ["--dir", str(tmp_path), "consent", "--participant", "alice", "--agree"]
    )
    capsys.readouterr()  # discard

    capture_session(tmp_path, canonical_trace())
    code = telemetry_main(["--dir", str(tmp_path), "status"])
    out = capsys.readouterr().out
    assert code == 0
    assert "alice" in out
    assert "1 session" in out


def test_cli_revoke_removes_consent_but_not_sessions(tmp_path, capsys):
    telemetry_main(
        ["--dir", str(tmp_path), "consent", "--participant", "alice", "--agree"]
    )
    captured = capture_session(tmp_path, canonical_trace())
    capsys.readouterr()  # discard

    code = telemetry_main(["--dir", str(tmp_path), "revoke"])
    out = capsys.readouterr().out
    assert code == 0
    assert "revoked consent" in out
    assert load_consent(tmp_path) is None
    assert captured.exists()  # session files survive a revoke, by design

    # A second revoke is a no-op and exits nonzero.
    code = telemetry_main(["--dir", str(tmp_path), "revoke"])
    assert code == 1
    assert "nothing to revoke" in capsys.readouterr().out
