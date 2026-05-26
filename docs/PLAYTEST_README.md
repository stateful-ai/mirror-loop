# Mirror Loop — Playtest README (local-only capture, consent first)

**Status:** Active · **Date:** 2026-05-25 · **Audience:** anyone whose play
session is being captured for analysis.
**Implemented by:** [`telemetry/__init__.py`](../telemetry/__init__.py) ·
**Verified by:** [`telemetry/tests/test_telemetry.py`](../telemetry/tests/test_telemetry.py).

> If you are *running* the prototype yourself, with no one watching, nothing in
> this document affects you: the default code path captures nothing. This README
> matters only when a session is going to be **recorded** — which only happens
> after you, the participant, have given written consent on the machine the game
> is running on.

---

## 1. The two guarantees this README is the contract for

1. **Local-only.** Every byte of captured data is written to a directory on the
   machine the game runs on, via the standard library's filesystem APIs. The
   capture module imports **no** network modules (no `socket`, no `urllib`, no
   `http`, no third-party HTTP client) — a test pins the import set so the
   guarantee cannot regress on a careless edit, and a socket-sentinel test runs
   a complete capture with `socket.socket` monkey-patched to raise, confirming
   nothing on the capture path opens a network connection. Nothing is uploaded,
   phoned home, or aggregated off the machine.
2. **Consent first.** Capture **refuses** to write unless a `consent.json`
   already exists on disk for the target directory. The `consent` CLI requires
   an explicit `--agree` flag, so the consent record is only created when the
   participant types it themselves. Consent is recorded against the *exact list*
   of what this build logs (below) — not "logging in general" — and is invalidated
   automatically if a future build changes what is logged (the schema version
   bumps and the old consent file no longer loads).

The simulated A/B harness ([`game/playtest.py`](../game/playtest.py) and
[`docs/PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md)) has **no human subject** — its
players are deterministic policies — so it captures nothing and consent does not
apply. This README is for the human-playtest seam.

## 2. Exactly what is logged

This list is generated from the `WHAT_IS_LOGGED` constant in
[`telemetry/__init__.py`](../telemetry/__init__.py); a change there bumps the consent
schema version and invalidates older consent records, so this list and the code
cannot drift.

- `participant_id` — a free-form label you choose; **no real identity required**.
- consent timestamp (UTC, ISO-8601).
- the world spine and variant played.
- the run seed.
- the input log — the choice id selected at each loop.
- the Mirror's per-loop transition: player-model snapshot before and after, and
  the ranked forecast the Mirror staked on it.
- every adaptation that fired this loop, with its recorded provenance.
- the rendered Reflection beat where it fired.
- the final player-model snapshot at session end.

## 3. Exactly what is **not** logged

- **No real-world identity** (no name, email, postal address, IP or MAC, no
  device id).
- **No free-form text** outside the captured choice ids.
- **No system, OS, or hardware information.**
- **No clock, screen, or input-event traces** beyond the per-loop choice.
- **No network telemetry** — nothing is ever sent off this machine.

These boundaries are the in-game safety/fiction line in
[`README.md`](../README.md#safety-and-fiction-boundary) carried through to the
research instrument: *the game adapts only to in-game behaviour and voluntarily
provided choices; the playtest harness records only what the game adapts to.*

## 4. Where the data lives

The default location is `~/.mirror-loop/playtest/`. You can pick another
directory with the `--dir` flag on every command.

```text
~/.mirror-loop/playtest/
├── consent.json            # the consent record (created by the CLI)
└── sessions/
    └── <state-hash>.json   # one captured session per file
```

The filename of a captured session is a prefix of its deterministic state
hash — so capturing the same session twice writes the **same file**, not a
duplicate.

## 5. How consent works (the CLI flow)

```text
# 1. Print the disclosure (no consent recorded, just shows what is logged).
python -m telemetry disclosure

# 2. The consent command, without --agree, prints the disclosure and exits 1.
#    It does NOT record consent unless you re-run with --agree yourself.
python -m telemetry consent --participant my-label

# 3. Record consent. Required: the explicit --agree flag.
python -m telemetry consent --participant my-label --agree

# 4. See what is on file.
python -m telemetry status

# 5. Revoke consent at any time. Captured session files are kept (so you can
#    review or take them with you); delete them yourself to remove them.
python -m telemetry revoke
```

Use `--dir /some/path` on any of the above to target a directory other than
`~/.mirror-loop/playtest/`.

## 6. How to delete your data

There is no remote store, so nothing to recall.

- Delete a single session: remove its `<state-hash>.json` from the `sessions/`
  directory.
- Delete *all* captured sessions: `rm -r ~/.mirror-loop/playtest/sessions`.
- Delete consent **and** all data: `rm -r ~/.mirror-loop/playtest`.

Revoking consent (`python -m telemetry revoke`) removes only
`consent.json`, deliberately, so you can revoke without losing the session
files you may want to review or take with you. The README is explicit about
this so a participant is never surprised.

## 7. How the guarantees are tested

[`telemetry/tests/test_telemetry.py`](../telemetry/tests/test_telemetry.py) pins:

- the static import set of `telemetry/__init__.py` (no network modules — parsed
  with `ast`, not text-grepped, so docstring mentions don't trip it);
- the socket-sentinel: a full capture runs with `socket.socket` monkey-patched
  to raise, and no socket is ever opened;
- `capture_session` refuses with `CaptureRefused` when no consent is on file;
- consent round-trips through JSON, rejects unknown schema versions, and
  refuses an empty participant id;
- the CLI: `consent` without `--agree` records nothing, `consent --agree`
  records, `status`/`revoke`/`where`/`disclosure` behave as documented;
- the README and `WHAT_IS_LOGGED` agree (every bullet in §2 appears in
  `WHAT_IS_LOGGED`, every "not logged" bullet in §3 in `WHAT_IS_NOT_LOGGED`).

## 8. Amending

The list in §2/§3 is the load-bearing contract: changing it changes what a
participant has agreed to.

- A change that **adds** a category of logging, or otherwise expands the
  agreement, bumps `CONSENT_SCHEMA_VERSION` in
  [`telemetry/__init__.py`](../telemetry/__init__.py). Old consent files no longer
  load and the participant must record fresh consent against the new list.
- A change that **removes** a category (logs strictly less) still bumps the
  version, for the same reason — a participant who agreed to the old list
  should know the new one is different.
- Any change must update both this README and the constants, *in the same
  patch*; the test suite asserts they match.
