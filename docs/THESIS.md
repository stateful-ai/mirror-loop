# Mirror Loop — Locked Thesis & Acceptance Test

**Status:** ✅ **LOCKED** · **Date:** 2026-05-24 · **Written:** before build (pre-v0.1)
**Approver (founder):** Aidan Kosik · **Supersedes:** nothing (first lock)

> This document is a **pre-build gate**. The thesis below is the single claim the
> prototype exists to prove, and the acceptance test below is the single,
> falsifiable, pass/fail check that decides whether it did. Both are locked
> *before* any engine code is written so that the build is judged against a fixed
> target rather than a moving one. Changing either requires explicit founder
> re-approval (update the sign-off block and bump the date).

---

## 1. Thesis (locked)

Mirror Loop's bet is that a single player's in-game behavior, observed over one
~25-minute session, is **predictable enough that a lightweight player model can
forecast their next choice better than a naive baseline** — and that surfacing
that prediction back to the player is precisely what turns "helpful
personalization" into dread. The horror is not an omniscient AI; it is the
discovery that *you are more predictable than you expected*. If the model cannot
out-predict a trivial baseline on real play, the central fantasy has no engine
and the rest of the design (creepy callbacks, predictive nudging, escape-through-
unpredictability) rests on nothing. Everything else is content; this is the
load-bearing wall.

---

## 2. Acceptance Test (single, falsifiable, pass/fail)

**Name:** Beats-Baseline Prediction Test
**Subject:** observed player behavior (measured from the event log; not a survey,
not a feeling).
**When:** run against **one complete playtested session** — Prologue → Act 1 →
recalibration → Act 2 — scored at **Act 2 decision points** (the model has had
all of Act 1 to learn the player before it is graded).

**Procedure.** At each Act 2 decision point the event log records the model's
ranked `predicted_actions` (highest-confidence first) and the player's
`actual_action`. Compute:

- **top-1 accuracy** = fraction of decision points where `predicted_actions[0] ==
  actual_action`.
- **baseline accuracy** = the accuracy of the trivial "always guess the single
  most-frequent action this player took" predictor over the same decision points.
- **margin** = top-1 accuracy − baseline accuracy.

**PASS** if and only if **both** hold:

| Gate | Threshold |
|------|-----------|
| top-1 accuracy | **≥ 0.60** |
| margin over most-frequent-action baseline | **≥ 0.15** |

**FAIL** otherwise (including too few decision points to score; see
`MIN_DECISION_POINTS`).

**What falsifies the thesis.** A FAIL — in particular a player who is either (a)
genuinely unpredictable (low top-1 accuracy) or (b) so repetitive that a dumb
baseline matches the model (margin near zero). The margin gate is the important
one: it stops us from congratulating ourselves for "predicting" a player who only
ever does one thing. The model must add real signal over "they'll just do it
again."

**Why these numbers.** 0.60 top-1 is well above chance for a typical 3–5 option
choice set yet achievable by a lightweight local model; 0.15 margin is a
defensible "the model is doing work, not riding the baseline" floor for an MVP.
They are deliberately concrete so the test is falsifiable. Moving them requires
founder re-approval (Section 4).

---

## 3. Executable specification

This test is not prose-only. It is operationalized as runnable code so the gate
can be executed against any session log:

- **Evaluator:** [`acceptance/predictability.py`](../acceptance/predictability.py)
  — pure functions (`top1_accuracy`, `baseline_accuracy`, `evaluate`) plus a
  `python -m acceptance.predictability <session.json>` CLI that prints PASS/FAIL.
- **Thresholds** live in that module (`MIN_TOP1_ACCURACY`,
  `MIN_MARGIN_OVER_BASELINE`, `MIN_DECISION_POINTS`) — single source of truth,
  kept next to the thesis on purpose.
- **Fixtures:** [`acceptance/fixtures/passing_session.json`](../acceptance/fixtures/passing_session.json)
  (a predictable-and-modelled player → PASS) and
  [`acceptance/fixtures/failing_session.json`](../acceptance/fixtures/failing_session.json)
  (a repetitive player the baseline matches → FAIL).
- **Tests:** [`acceptance/tests/test_predictability.py`](../acceptance/tests/test_predictability.py)
  verify the evaluator and both fixtures (`pytest`).

The future build "passes the gate" when a **real playtest session log**, run
through this evaluator, returns PASS. Until then the fixtures prove the gate
itself is correct and discriminating.

---

## 4. Founder sign-off

By approving this document the founder locks the thesis and the acceptance test
as the success criterion for the prototype build.

- **Thesis locked:** §1 above.
- **Acceptance test locked:** §2 above, operationalized in §3.
- **Approved by:** Aidan Kosik (founder)
- **Date:** 2026-05-24
- **Status:** APPROVED — build may proceed against this gate.

_To amend: edit §1/§2, update the thresholds in `acceptance/predictability.py`
to match, re-run `pytest`, and re-sign here with a new date._
