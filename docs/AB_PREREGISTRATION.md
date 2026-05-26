# Mirror Loop — A/B Decision Rule (pre-registration)

**Status:** ✅ **LOCKED** · **Date:** 2026-05-25 · **Written:** before any
future A/B playtest (binds M2 and onward).
**Approver (founder):** Aidan Kosik · **Supersedes:** nothing (first lock).
**Single source of truth (code):**
[`game/playtest.py`](../game/playtest.py) (A/B constants) +
[`acceptance/predictability.py`](../acceptance/predictability.py) (per-session
metric).
**Method (long form):** [`docs/PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md).
**Thesis (metric origin):** [`docs/THESIS.md`](./THESIS.md).

> This is a **pre-registration envelope**, not a method paper. It fixes the four
> items the company product principle names — *"the adaptive thesis is validated
> by a blind A/B with a decision rule (metric, n, effect threshold,
> kill-criteria) pre-registered before the playtest, not judged post-hoc"* — in
> one short, signed, committed document, so the rule cannot be edited to fit a
> future result. The numbers below are stated **by reference** to the code
> constants that already pin them; the test in
> [`game/tests/test_ab_preregistration_doc.py`](../game/tests/test_ab_preregistration_doc.py)
> fails if this doc and those constants drift apart.

---

## 1. Primary metric

The **Beats-Baseline Prediction Test**
([`acceptance/predictability.py`](../acceptance/predictability.py),
[`THESIS.md`](./THESIS.md) §2), applied per session and aggregated to the arm
mean.

- An arm clears the locked gate iff **mean top-1 ≥ `MIN_TOP1_ACCURACY`** *and*
  **mean margin over the most-frequent-action baseline ≥
  `MIN_MARGIN_OVER_BASELINE`**.
- The metric is **imported**, not redefined, by the harness. Changing it is a
  founder action on [`THESIS.md`](./THESIS.md), not a method edit.
- The **A/B contrast** (Δ mean top-1 between arms) is the *primary endpoint* of
  the playtest; the locked gate is the bar the *winning* arm must still clear
  (Section 4 below).

## 2. Minimum sample size

**`N_PER_ARM` sessions per arm**, paired (the same population drives both arms,
so any difference is the adaptation, not the sample). One session is one
player's full five-loop spine.

- Source of truth: `game.playtest.N_PER_ARM`.
- Below this floor in either arm ⇒ **INCONCLUSIVE by rule**, whatever the
  scores. The decision rule also requires ≥ `MIN_DECISION_POINTS` scored points
  per arm
  ([`acceptance/predictability.py`](../acceptance/predictability.py)).

## 3. Effect threshold

**`EFFECT_THRESHOLD` absolute difference in mean top-1 accuracy between arms**,
below which (in absolute value) the arms are treated as **not separated** on
this metric.

- Source of truth: `game.playtest.EFFECT_THRESHOLD`.
- Symmetric: |Δ mean top-1| < `EFFECT_THRESHOLD` ⇒ no separation; signed
  comparison only kicks in once the threshold is crossed (Section 4).

## 4. The result that would falsify the thesis

Two distinct falsifiers, both pre-committed:

1. **A/B kill-criterion (this doc).** The adaptive arm is **worse** than the
   baseline arm by at least the effect threshold —
   **Δ mean top-1 ≤ −`EFFECT_THRESHOLD`** — at the locked sample size.
   That returns **FAIL** from `game.playtest.decide` and is the adaptation
   thesis killed: the adaptation is not just neutral, it is actively
   counterproductive.
2. **Thesis FAIL ([`THESIS.md`](./THESIS.md) §2).** A real playtested session
   in which the model cannot clear the locked floor: top-1 < `MIN_TOP1_ACCURACY`
   *or* margin < `MIN_MARGIN_OVER_BASELINE`. That falsifies the *load-bearing*
   claim that a lightweight model can out-predict a trivial baseline at all.

The decision rule's full PASS / FAIL / INCONCLUSIVE order is fixed in
`game.playtest.decide` and described in
[`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md) §6. Outcomes other than the two
above (no separation, or separation with the adaptive arm below the locked
floor) are **INCONCLUSIVE**, not PASS and not FAIL — the rule deliberately does
not let an ambiguous reading be promoted to a verdict.

---

## 5. Blinding and parity

The locked metric is applied **label-blind**: each session is scored purely
from its `(predicted_actions, actual_action)` log, with no view of which arm
produced it. The two arms run through the identical
[`game.session.play_session`](../game/session.py) path with no `if arm == …`
branching on the player path — parity is **structural**, gated in CI
([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md)), not a
property the analyst remembers to check.

## 6. What this pre-registration binds

- **Any future A/B playtest** run after this document's date — including the
  human/subjective instrument deferred to a later milestone
  ([`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md) §8) — is judged against the
  rule fixed here. The first canonical simulated run
  ([`PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md), 2026-05-25) was scored
  against the same rule pre-registered concurrently in
  [`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md); this doc consolidates that rule
  into one signed envelope so subsequent runs cannot drift it.
- The constants named in §§1–3 may only be changed by editing
  [`game/playtest.py`](../game/playtest.py) (for `N_PER_ARM` /
  `EFFECT_THRESHOLD`) or [`acceptance/predictability.py`](../acceptance/predictability.py)
  (for the metric thresholds) **and** re-signing this document with a new date
  in §7. A run that has already happened is never re-scored under new numbers.

## 7. Founder sign-off

By approving this document the founder locks the A/B decision rule — primary
metric, minimum sample size, effect threshold, and falsifying result — as the
gate against which any future Mirror Loop playtest is judged.

- **Pre-registered:** §§1–4 above, by reference to the code constants in
  `game.playtest` and `acceptance.predictability`.
- **Approved by:** Aidan Kosik (founder)
- **Date:** 2026-05-25
- **Status:** APPROVED — playtests run after this date are judged against this
  rule.

_To amend: edit the constants in the code (single source of truth), update
§§1–4 here to match, re-run the test suite (the doc-pin test in
`game/tests/test_ab_preregistration_doc.py` enforces consistency), and re-sign
above with a new date._
