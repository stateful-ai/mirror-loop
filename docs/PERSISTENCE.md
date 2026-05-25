# Mirror Loop — Within-Session Persistence

**Status:** Built (M1 B1 engine — the last engine item) · **Date:** 2026-05-25 ·
**Scope:** how a play session accumulates the Mirror and world deltas, persists
them, and survives a reload *within* one play-through — and why losing a session
on quit is acceptable for v0.
**Implemented by:** [`game/playsession.py`](../game/playsession.py)
(`PlaySession`), over the shared loop halves in
[`game/session.py`](../game/session.py) (`offer_scene`, `record_loop`).
**Verified by:** [`game/tests/test_playsession.py`](../game/tests/test_playsession.py)
— every claim below is asserted against the code.

> This is the decision record for the prototype's persistence. The within-session
> persistence step is the final B1 engine item in the M1 plan
> ([`docs/mirror_loop_m1_founder_brief.md`](./mirror_loop_m1_founder_brief.md),
> "Phase B"). It builds on the locked event-log architecture
> ([`docs/SCHEMAS.md`](./SCHEMAS.md) §0) rather than introducing a new store.

---

## 1. What "persists" — the log, not the deltas

One locked rule governs this, exactly as it governs the schema set
([`docs/SCHEMAS.md`](./SCHEMAS.md) §0; [`docs/MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md)
§6; company memory):

> The append-only **log is the only source of truth**. The Mirror *and* the
> world-state are **pure reductions** over it; no derived state is ever the
> authority.

So a persisted session stores only the **authoritative inputs**, never the
derived "deltas" themselves:

| Stored (authoritative) | Recomputed on reload (derived) |
|------------------------|--------------------------------|
| `world` (name), `variant`, `seed` | the running tendency tally + `announced` set (the **Mirror delta**) |
| `input_log` — the choice id made each loop | the position in the spine + each revealed framing (the **world delta**) |
| `session_id`, `schema_version` | every in-scene re-ordering and the closing report |

The deltas "persist" because they are a **deterministic function of the stored
log**: on reload `PlaySession.from_dict` **replays the input log** through the
ordinary engine, reducing the Mirror model and the world position back to exactly
where they were. This is the `(seed, input log)` contract
[`game/replay.py`](../game/replay.py) already proves fully determines a run, and
the "save the log, replay it" property [`docs/MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md)
§"player-state never needs to be persisted" calls out. Storing the log instead of
the deltas is what keeps the reload honest — there is no second copy of the truth
that can drift from the first.

`PlaySession.to_dict` therefore serializes those input keys and **nothing
derived** (pinned by `test_saved_form_stores_only_the_authoritative_log`).

## 2. Adaptations accumulate, and compound, across a reload

Because the adaptation reads *only* from the reduced state, a loop played after a
reload is provably a function of the loops persisted before it. The scripted proof
(`test_two_adaptations_compound_across_a_save_reload`, and runnable via
`python -m game.playsession`) plays three loops as a consistently kind player,
saves to JSON, resumes in a **fresh** `PlaySession` (new `Mirror`, state reduced
from the log), then plays loops 4–5 and shows **two distinct adaptations
compounding** on the carried-over history:

```text
loop 4 [confrontation]  in-scene re-ordering   declared [c_walk, c_log, c_wait]
                                               -> offered [c_wait, c_walk, c_log]
                                               (kindness, declared last, lifted to front)
loop 5 [exit]           branch selection       revealed the 'kindness' framing
```

Both adaptations exist only because loops 1–3 survived the serialize/restore
boundary; the branch selection was already compounding before the save (`records`
→ `corridor` → `exit` all reveal the kind framing as the lean strengthens). The
two adaptation surfaces are the same ones [`docs/ADAPTATION.md`](./ADAPTATION.md)
defines — this slice adds nothing to *what* the Mirror does, only that it
**remembers** across a reload.

**Falsifiable by construction.** The same confrontation scene offered from a blank
(un-persisted) state keeps its declared order — no re-ordering
(`test_without_persisted_history_the_same_scene_is_not_adapted`). And a session
that persisted a *controlling* player instead adapts to control, not kindness
(`test_adaptation_tracks_what_was_persisted_not_merely_that_loops_happened`): it
is the persisted *behavior*, not the act of persisting, that the later loops bend
to. The `fixed` baseline persists history too yet shows no adaptation, separating
persistence from contingency (`test_fixed_baseline_persists_but_never_adapts`).

## 3. The seam this adds (parity with the one-shot runner)

A loop is `offer → choose → record`. The two halves —
[`offer_scene`](../game/session.py) (read-only: which framing, in what order) and
[`record_loop`](../game/session.py) (step the chosen choice, build the record) —
are shared verbatim between the one-shot [`play_session`](../game/session.py) and
the resumable `PlaySession`. The one-shot runner calls a policy *between* the
halves; the resumable session shows the offer to a caller, takes a choice id, then
records it — **possibly across a save/reload**. Sharing the halves is what
guarantees both runners step the loop identically: a session built loop-by-loop
through a reload yields a transcript byte-identical to the one-shot run of the
equivalent persona (`test_resumed_session_completes_identically_to_the_one_shot_runner`),
and the byte-identity golden gate (`python -m game.replay --check`) is unmoved by
this change.

## 4. Lost on quit is acceptable for v0

This is *within*-session persistence: durability across a save/reload **inside one
play-through** (a paused turn, a reloaded page, a separate process resuming the
same run). There is **no automatic, durable store** behind it — a `PlaySession`
held only in memory is gone when the process exits unless the caller explicitly
`save()`d it (`test_save_writes_nothing_until_called`,
`test_unsaved_sessions_share_no_hidden_state`).

That boundary is deliberate. **Cross-session persistence** — a session, profile,
or NPC memory that survives quitting the game and steers a *later* run — is
explicitly **out of scope for v0**:

- [`docs/mirror_loop_m1_founder_brief.md`](./mirror_loop_m1_founder_brief.md)
  "Out of scope (M2+)" lists **cross-session persistence** alongside crash-safe
  append and the RUN_CONFIG header.
- [`docs/RECONCILIATION.md`](./RECONCILIATION.md) §3 #5 carries **multi-run
  memory** as an open question to "decide before designing the
  event-log/profile persistence schema," and ending #5 (Recursive Reveal) /
  cross-session adaptation are deferred ([`docs/ADAPTATION.md`](./ADAPTATION.md)
  §5).

Shipping within-session persistence now — and accepting lost-on-quit — is what
lets the thesis test run against a complete play-through
([`docs/THESIS.md`](./THESIS.md)) without first committing to a durable profile
schema. When multi-run memory is decided, the persisted form already on hand (an
append-only input log keyed by world/variant/seed) is the natural seed for it: a
durable store would keep these same logs, not a new derived snapshot.

## 5. Version policy

`PlaySession` carries its own `SCHEMA_VERSION`, stamped into the serialized form;
a snapshot under an unknown version is **refused** at `from_dict` rather than
silently mis-restored, and an `input_log` recorded against an unknown (or
mismatched) world is rejected via [`game.world.get_world`](../game/world.py). This
is the same fail-loud posture the other schemas take
([`docs/SCHEMAS.md`](./SCHEMAS.md) §5).
