# Mirror Loop — Session Objective and End Condition

**Status:** Decided (v0 build target) · **Date:** 2026-05-25 · **Scope:** what a
session of the handcrafted world is, what completing one means, and how a
session ends (win / lose / exhaust). Required for the "complete a short session"
DoD and for the per-session unit a scoreable A/B metric averages over.
**Bounded by:** the locked [`docs/THESIS.md`](./THESIS.md) gate; consistent with
the locked [`docs/CORE_LOOP.md`](./CORE_LOOP.md) and the handcrafted world in
[`game/world.py`](../game/world.py).
**Implemented by:** [`game/session.py`](../game/session.py) (`play_session`,
`MIN_LOOPS`, `MAX_LOOPS`), the resumable
[`game/playsession.py`](../game/playsession.py) (`PlaySession`), and the closing
readout in [`game/templates.py`](../game/templates.py) (`final_report`, `_band`).
**Verified by:** [`game/tests/test_session_objective_doc.py`](../game/tests/test_session_objective_doc.py)
— every constant and outcome boundary below is asserted against the code.

> This is the decision record for the prototype's session: what counts as one,
> what an ending is, and which of the three named outcomes the run resolved
> into. It is the missing piece between the locked core-loop turn
> ([`CORE_LOOP.md`](./CORE_LOOP.md)) and the locked per-session metric
> ([`THESIS.md`](./THESIS.md) §2) — both speak of "a session" without saying
> where one starts, where it stops, or what its outcome was.

---

## 1. What a session is

A **session** is one player's walk of the handcrafted world's fixed spine —

```text
intake → records → corridor → confrontation → exit
```

— played once, slot by slot, with no LLM and no randomness on the path. One
**loop** is the locked core-loop turn (scene → choices → state update → optional
Reflection beat, [`CORE_LOOP.md`](./CORE_LOOP.md) §1). One **session** is the
spine those loops accumulate over — five loops in the shipped world, inside the
`[MIN_LOOPS, MAX_LOOPS] = [3, 5]` target. `play_session` raises rather than
return a session outside that bound, so a trivially short or over-long run fails
loudly instead of shipping.

The session is the **unit of analysis**. The per-session log it emits is exactly
what the locked Beats-Baseline Prediction Test scores ([`THESIS.md`](./THESIS.md)
§2), and what the A/B harness averages to the arm level
([`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md) §4). Anything shorter than a full
session has no per-session score (`MIN_DECISION_POINTS = 5`); anything longer is,
by construction, two sessions.

## 2. The objective

The session has two simultaneous objectives — one diegetic, one mechanical —
and the whole point of the prototype is that they pull in opposite directions.

| Whose objective | What it is | Where it lives |
|-----------------|------------|----------------|
| **The player** (diegetic) | complete the lab's "personalized experience": walk the spine from `intake` to `exit`. | [`game/world.py`](../game/world.py); the lab's surface premise, [`game_design.md`](./game_design.md) §3.1 |
| **The Mirror** (mechanical) | predict the player's next choice; tighten the model with every loop. | [`loop.core.Mirror.predict`](../loop/core.py); the hidden premise and load-bearing thesis, [`game_design.md`](./game_design.md) §3.2, [`THESIS.md`](./THESIS.md) §1 |

There is **no resource economy, no health bar, no turn limit, no early
termination, and no game-over screen in v0**. The spine cannot be failed out of
— the Mirror's adaptation only ever re-orders or reframes pre-authored content
and never removes a door ([`ADAPTATION.md`](./ADAPTATION.md) §4). The session is
won, lost, or exhausted on **how predictable** the player turned out to be, not
on whether they reached the end (they always do).

## 3. How a session ends (win / lose / exhaust)

Every session ends the same structural way — **the player walks every slot in
the spine, in order, exactly once**, and `is_finale` fires on the final
(`exit`) slot. That is the only termination condition v0 has. On top of that
single structural ending, **three diegetic outcomes** are read off the closing
readout (`final_report`, `_band`) by binning the session's top-1 predictability
score, and those three outcomes are the named session ends:

| Outcome | Trigger (top-1 over the session) | Mirror's closing readout | What it means |
|---------|----------------------------------|--------------------------|----------------|
| **LOSE** — *captured* | top-1 **≥ 0.60** *(clears the locked gate)* | `MODEL CONFIDENCE: HIGH`, `AGENCY DRIFT: LOW`, `ESCAPE: improbable` | The Mirror modelled the player; the system "won." Diegetically the bad ending: predictable enough that the experience completes you. |
| **EXHAUST** — *ambiguous* | **0.40 ≤ top-1 < 0.60** | `MODEL CONFIDENCE: MODERATE`, `AGENCY DRIFT: ELEVATED`, `ESCAPE: plausible` | The spine ran out before either side proved. Neither captured nor escaped — the session ends because there are no more slots, not because anything was decided. |
| **WIN** — *escape* | top-1 **< 0.40** *(the escape archetype)* | `MODEL CONFIDENCE: LOW`, `AGENCY DRIFT: HIGH`, `ESCAPE: open` | The player slipped the model ([`game_design.md`](./game_design.md) §12); the central horror does not land on them. |

**The boundaries are not redefined here.** The LOSE / EXHAUST boundary is
`acceptance/predictability.MIN_TOP1_ACCURACY = 0.60` — at or above it the locked
gate is cleared and the Mirror's model has "won" the session against the
player. The EXHAUST / WIN boundary is the report's `0.40` floor below which the
closing verdict line flips from *"the Mirror anticipated …"* to *"you were harder
to predict than you were sold as being."* Both numbers are reused from existing
single-sources-of-truth (`acceptance/predictability.py` for the gate,
`game/templates.py` for the bands), and the test pins them — so this doc cannot
quietly drift from either.

**Inverted polarity, on purpose.** Mechanically, the thesis *passes* (a "good"
engineering outcome) exactly when the player *loses* (a "bad" diegetic
outcome). This is the load-bearing design tension: the prototype only proves
its central fantasy by demonstrating that the player can be modelled, which is
the same thing as showing the lab can contain them. The A/B metric scores
prediction accuracy; the closing readout dramatises that accuracy as
captivity. The two are the same number with opposite signs of valence — and
that is why the outcomes are named *win / lose / exhaust* from the **player's**
seat rather than the engineering one.

## 4. What is *not* a session end (deliberately excluded from v0)

- **Quitting mid-spine.** A `PlaySession` saved with `position < world.length`
  is **paused**, not ended. Resuming reduces the saved input log and continues
  from the same slot, in any process ([`PERSISTENCE.md`](./PERSISTENCE.md)).
  Quitting and never resuming is not a recorded outcome — the run simply has no
  closing readout because it has no completed session to score.
- **Failing a choice.** No choice in any slot ends the run, locks an exit, or
  removes a future slot. The Mirror only ever re-orders or reframes
  ([`ADAPTATION.md`](./ADAPTATION.md) §4) — it never deletes the spine.
- **Time limits / resource exhaustion.** Out of scope for v0; deferred along
  with the Act-2+ challenge dimensions ([`game_design.md`](./game_design.md)
  §4.4).
- **Multi-run arcs.** A session is one walk of the spine. Cross-session
  persistence and prior-run memory are deferred
  ([`game_design.md`](./game_design.md) §17 #5,
  [`RECONCILIATION.md`](./RECONCILIATION.md) §3 #5).

## 5. How this feeds the DoD and the A/B metric

- **"Complete a short session" DoD.** A session is *complete* when
  `play_session` returns successfully — the spine was walked, the 3–5-loop
  bound held, and the closing readout was rendered. Completion is **structural**
  and arm-independent: the player completes in any of the three outcomes above,
  exactly the same way, with the same shape of log.
- **Per-session A/B metric.** The `(predicted_actions, actual_action)` pairs
  the Mirror writes each loop are the decision points the locked gate scores;
  the log emitted by `Session.session_log` drops into
  `python -m acceptance.predictability` with no translation, and into the
  arm-level aggregation in [`game/playtest.py`](../game/playtest.py)
  ([`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md) §4). Because every session is
  exactly one walk of the spine, "session" is well-defined as the metric's unit
  of analysis without further bookkeeping — and the three outcomes above are
  precisely the bands a scoreable per-session result already lives in.
