# Mirror Loop — Acceptance Observables (the operationalized definition)

**Status:** Locked (definition) · **Date:** 2026-05-25
**Scope:** the written, executable definition of which **events / derived
values from the replay log** constitute *"the adaptation changed the player's
experience,"* together with the **pre-registered A/B rule** they compute —
confirmed sufficient with **no later re-instrumentation**.
**Bounded by:** the founder-locked [`docs/THESIS.md`](./THESIS.md). This
document does *not* replace the locked Beats-Baseline Prediction Test; it
operationalizes the experience-change question that prior playtest established
the prediction metric structurally cannot answer
([`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md) §3).
**Implemented by:** [`acceptance/experience_change.py`](../acceptance/experience_change.py).
**Verified by:** [`acceptance/tests/test_experience_change.py`](../acceptance/tests/test_experience_change.py).

> Pre-registered. The observables and the floors below are fixed *before* any
> run that judges by them so the rule cannot be edited to fit the outcome, per
> the company product principle that *"the adaptive thesis is validated by a
> blind A/B with a decision rule (metric, n, effect threshold, kill-criteria)
> pre-registered before the playtest, not judged post-hoc."* The numbers below
> are the rule.

---

## 1. Why a separate operationalization

The locked prediction metric ([`docs/THESIS.md`](./THESIS.md) §2) scores the
Mirror's forecast against the player's choice. The Mirror's prediction is a
*render* that fires identically in every arm
([`docs/ADAPTATION.md`](./ADAPTATION.md) §4); a presentation-independent player
chooses by tendency regardless of the framing or choice order they see. So
under the conservative-null population the two arms produce byte-identical
`(predicted_actions, actual_action)` decision points
([`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md) §3), and the prediction
metric — by construction — cannot separate them.

What the adaptation *does* change is the content the player reads and the
order in which they read it (see §1.1 of [`docs/ADAPTATION.md`](./ADAPTATION.md)):
the **branch framing** revealed at each slot, and the **in-scene re-ordering**
of choices. The question *"did the adaptation change the player's experience?"*
therefore needs observables that are read from those two surfaces — what was
presented, and what the player did about it — not from the prediction render.

The pieces are **already in the replay log**. This document names them, fixes
their derived values, and pre-registers the rule that decides.

## 2. The observables (the definition)

For one loop of one player's session, the experience-change definition reads
**five values, every one a direct attribute of the existing replay log**
([`game/session.py`](../game/session.py) ``LoopRecord``,
[`game/instrumentation.py`](../game/instrumentation.py) ``LoopTrace``). No new
event type is needed; no engine replay is required.

| Observable | Replay-log source (in-memory) | What it means |
|------------|-------------------------------|----------------|
| `loop_index` | `LoopRecord.loop_index` | which slot of the spine; the pairing key across arms |
| `scene_id` | `LoopRecord.offered.id` | the framing actually presented (different id ⇒ different prose) |
| `branch_key` | `LoopRecord.branch_key` | which authored framing the seam revealed (`"default"` / `"fixed"` / a tendency) |
| `offered_order` | `[c.id for c in LoopRecord.offered.choices]` | the choice ids in the order the player saw them |
| `actual_action` | `LoopRecord.result.actual_action` | the choice the player took |

These five are the canonical reduction
([`acceptance/experience_change.py`](../acceptance/experience_change.py)
`LoopPresentation`). The same five are present in the serialized trace
([`game/instrumentation.py`](../game/instrumentation.py)) under loop
`scene_id`, `input`, and — for the adaptive arm — the audited `adaptations`
records (`branch_selection.revealed`, `choice_reordering.ordering`), so a
JSON-only consumer can compute the rule too (`load_pair_log`).

### 2.1 Per-loop divergence predicates (paired A/B)

A paired observation is the *same* player run through both arms — exactly the
pairing [`game/playtest.py`](../game/playtest.py) already produces (one
population seeded through both seams). At a paired loop `i`, four predicates
are defined on the two `LoopPresentation`s:

| Predicate | Definition | What it answers |
|-----------|------------|------------------|
| `framing_diverged` | `branch_key_A ≠ branch_key_B` | did the seam reveal a different framing this loop? |
| `order_diverged` | `offered_order_A ≠ offered_order_B` | did the seam present the choices in a different order? |
| `presentation_diverged` | `framing_diverged ∨ order_diverged` | did the seam present *anything* differently? |
| `behavior_diverged` | `actual_action_A ≠ actual_action_B` | did the player make a different choice between arms? |

Pure, total, side-effect-free — the in-out signature is two `LoopPresentation`s
in, one `bool` out.

### 2.2 Per-pair aggregate

For one player's paired session of `n` paired loops, the rule's inputs are
four rates (`PairObservables`):

* `framing_divergence_rate` = `framing_diverged` count / `n`
* `order_divergence_rate` = `order_diverged` count / `n`
* `presentation_divergence_rate` = `presentation_diverged` count / `n`
* `behavior_divergence_rate` = `behavior_diverged` count / `n`

A pair is *scorable* iff `n ≥ MIN_PAIRED_LOOPS` (= 5, matching the locked
[`MIN_DECISION_POINTS`](../acceptance/predictability.py) on the prediction
gate).

## 3. The pre-registered rule

Both floors below are fixed in code in
[`acceptance/experience_change.py`](../acceptance/experience_change.py) (the
single source of truth) and mirrored here:

* `PRESENTATION_DIVERGENCE_FLOOR = 0.20` — mean per-pair fraction of loops on
  which the adaptive arm visibly differs from the baseline. Below it the seam
  is not doing the thing the type promises ([`docs/ADAPTATION.md`](./ADAPTATION.md)
  §1) — there is no experience to compare. The canonical world has five loops
  per session; a strongly-leaning player crosses the notice threshold by loop
  ~3 and triggers branch selection on the remaining slots, so one-fifth is a
  defensible *"the seam actually fired"* floor without depending on a specific
  lean.
* `BEHAVIORAL_DIVERGENCE_FLOOR = 0.05` — mean per-pair fraction of loops on
  which the player's `actual_action` differs between arms. The conservative-
  null population pins this at zero by construction (presentation-independent
  players choose the same in both arms); a nudgeable population pushes it
  above zero ([`docs/game_design.md`](./game_design.md) §4.6). So this
  threshold is precisely what separates *"the adaptation altered presentation"*
  from *"the adaptation altered the player's experience"* — the falsifiable
  claim.
* `MIN_PAIRED_SESSIONS = 30` — same population minimum as the locked A/B
  ([`docs/PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md) §3); fewer scorable pairs
  ⇒ INCONCLUSIVE by rule.

The decision rule, evaluated in order:

1. **INCONCLUSIVE** — fewer than `MIN_PAIRED_SESSIONS` *scorable* pairs.
2. **FAIL — presentation floor** — `mean_presentation_divergence` below
   `PRESENTATION_DIVERGENCE_FLOOR`: the seam did not visibly do the thing, so
   the experience question is unanswerable on this run.
3. **FAIL — behavior floor** — presentation cleared, but
   `mean_behavior_divergence` below `BEHAVIORAL_DIVERGENCE_FLOOR`: the
   adaptation changed *presentation* but not the *experience* (the
   conservative-null reading the canonical playtest produced).
4. **PASS** — both floors cleared: the seam visibly did the thing, and the
   player's choices responded to it.

## 4. Sufficiency: no later re-instrumentation

The contract is that everything above is computable from the replay log the
engine **already produces today**. Pinned by the test suite
([`acceptance/tests/test_experience_change.py`](../acceptance/tests/test_experience_change.py)):

* Every `LoopPresentation` field is a direct attribute read on a
  `LoopRecord` the engine already builds. No new instrumentation hook,
  no new event type, no Mirror replay.
* The same five values round-trip through the projection JSON shape
  (`session_observables_log` / `load_pair_log`), so a JSON-only consumer can
  apply the rule without ever holding a live `Session`.
* The pre-registered rule discriminates: the canonical conservative-null
  population (the run that produced the INCONCLUSIVE verdict on the prediction
  metric) clears the **presentation** floor and fails the **behavior** floor,
  diagnosing exactly the structural pin the prior playtest reported
  ([`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md) §3). A nudgeable
  population clears both — the rule reaches PASS through real paired sessions
  ([`docs/game_design.md`](./game_design.md) §4.6).

### 4.1 Running the rule

End-to-end on the canonical paired population, from the engine's existing log:

```
python -m acceptance.experience_change                     # canonical null -> FAIL (behavior floor)
python -m acceptance.experience_change --suggestibility 0.8   # nudgeable population -> PASS
python -m acceptance.experience_change --from-logs pair_*.json --json
```

Exit codes mirror [`game.playtest`](../game/playtest.py): `0` PASS, `1` FAIL,
`3` INCONCLUSIVE (`2` is argparse usage). `--from-logs` accepts the projection
written by `write_pair_log`, so a JSON-only consumer scores without re-running
the engine.

## 5. Relation to the locked metric

The locked Beats-Baseline Prediction Test ([`docs/THESIS.md`](./THESIS.md) §2)
is unchanged and remains the absolute thesis bar. The experience-change rule
is *additive*: it answers the question the prediction metric structurally
cannot ("did the adaptation change the experience"), in observables the
existing log already carries, so a future paired A/B can pre-register against
it without needing a new instrument. The two rules together cover the two
questions the M2 playtest asks — does the model add predictive signal (locked
metric) and does the seam carry that signal into a changed experience
(this rule).

## 6. Amending

This is the operationalization of an open question, not a metric change. To
move a floor or add an observable, edit the constants and module in
[`acceptance/experience_change.py`](../acceptance/experience_change.py),
update §§2–3 here to match, re-run the test suite, and re-date the header.
The locked metric and its thresholds are *not* touched by changes here — those
are a founder action in [`docs/THESIS.md`](./THESIS.md) §4.
