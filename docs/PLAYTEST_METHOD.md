# Mirror Loop — Blind A/B Playtest Method (pre-registered)

**Status:** Locked (method) · **Date:** 2026-05-25 · **Scope:** the protocol for
the adaptive-vs-baseline A/B playtest — arms, sample size, metric, effect
threshold, kill-criterion, decision rule, blinding, and the simulated-player
population that stands in for human playtesters until they are in the loop.
**Bounded by:** the founder-locked metric in [`docs/THESIS.md`](./THESIS.md).
**Implemented by:** [`game/playtest.py`](../game/playtest.py)
(`python -m game.playtest`).
**Verified by:** [`game/tests/test_playtest.py`](../game/tests/test_playtest.py).
**Results:** [`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md).

> This document is **pre-registered**: it fixes the decision rule *before* the
> playtest is scored, per the company product principle that
> *"the adaptive thesis is validated by a blind A/B with a decision rule (metric,
> n, effect threshold, kill-criteria) pre-registered before the playtest, not
> judged post-hoc."* The numbers below are the rule; the run that judges against
> them is reported separately in [`PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md) so
> the method cannot be edited to fit the outcome. The per-session **metric** is
> not restated here — it is the founder-locked gate in [`THESIS.md`](./THESIS.md),
> *imported* by the harness so it cannot drift.

---

## 1. Question

The prototype ships one adaptation (tendency mirroring, [`docs/ADAPTATION.md`](./ADAPTATION.md))
behind a single seam with non-adaptive baselines as first-class controls
([`game/variants.py`](../game/variants.py)). This playtest asks the A/B question:

> **Does the adaptive arm (the real game) out-perform a non-adaptive baseline on
> the locked predictability metric — and does the real game clear the locked
> bar?**

The A/B *contrast* is the primary endpoint. The locked gate is the bar the
winning arm must still clear.

## 2. Arms

Both arms run through the **identical** engine and shell
([`game.session.play_session`](../game/session.py)); they differ only in the one
adaptation seam, never in a forked code path:

| Arm | Variant | Seam |
|-----|---------|------|
| **adaptive** (treatment) | `adaptive` | content is contingent on the player model |
| **baseline** (control) | `fixed` *(default)* | the identity transform: declared order, neutral framing |

The placebo `random` arm (player-independent variation — the blinding-grade
control for *human* players) is selectable with `--baseline random` and reported
when used, but the canonical control is the `fixed` identity baseline.

## 3. Sample size — **n**

**≥ 30 sessions per arm** (`N_PER_ARM = 30`). One session is one player's full
five-loop spine (five Act-2-equivalent decision points). Fewer than 30 collected
in either arm ⇒ **INCONCLUSIVE** by rule, whatever the scores. The two arms are
**paired**: the same population (same seeds) plays both, so any difference is the
adaptation, not the sample.

## 4. Metric (locked, imported — not redefined here)

Each session is scored by the **Beats-Baseline Prediction Test**
([`acceptance/predictability.py`](../acceptance/predictability.py),
[`THESIS.md`](./THESIS.md) §2) on its own decision points — the session is the
unit of analysis exactly as the thesis defines it. Per-session results are then
averaged to the arm level (the per-player most-frequent-action baseline stays
per-player, so the margin keeps its meaning rather than being diluted by pooling
players). The locked thresholds are reused verbatim for the arm aggregate:

- `MIN_TOP1_ACCURACY = 0.60`
- `MIN_MARGIN_OVER_BASELINE = 0.15`

An arm **clears the gate** iff its mean top-1 ≥ 0.60 **and** mean margin ≥ 0.15.

## 5. Effect threshold

**`EFFECT_THRESHOLD = 0.05`** absolute difference in mean top-1 accuracy between
arms. Below it (in absolute value) the arms are treated as **not separated**: the
adaptation is indistinguishable from the shell on this metric.

## 6. Decision rule (PASS / FAIL / INCONCLUSIVE)

Evaluated in order, fixed in advance:

1. **INCONCLUSIVE** — fewer than `N_PER_ARM` sessions in either arm, or fewer
   than `MIN_DECISION_POINTS` (5) scored points in either arm. *(not enough data)*
2. **FAIL — kill-criterion** — the adaptive arm is **worse** than baseline by at
   least the effect threshold (Δ mean top-1 ≤ −0.05): the adaptation is actively
   counterproductive; the thesis is killed.
3. Arms **separate** in the adaptation's favour (Δ mean top-1 ≥ +0.05):
   - **PASS** if the adaptive arm also **clears the locked gate** — the adaptation
     adds real, attributable predictive signal *and* meets the thesis bar.
   - **INCONCLUSIVE** otherwise — the effect is real but the adaptive arm is still
     below the locked floor; the bar is not yet met.
4. Arms **do not separate** (|Δ mean top-1| < 0.05) → **INCONCLUSIVE**: on the
   locked prediction metric the adaptation cannot be distinguished from the
   baseline shell, whatever the (shared) absolute score.

The absolute per-arm gate status is always reported as evidence, even when the
verdict is driven by the contrast.

## 7. Blinding

The locked metric is applied **label-blind**: each session is scored purely from
its `(predicted_actions, actual_action)` log, with no view of which arm produced
it (the data is self-labelling for analysis; the scorer is not). Because the two
arms share one code path with no `if arm == …` branching on the player path,
parity is **structural**, not a property we remember to check.

## 8. Players — the population (and a known limitation)

There is no human and no LLM in the M1/M2 loop
([`docs/adr/0002-runtime-platform.md`](./adr/0002-runtime-platform.md)), so the
population is a deterministic, seeded set of `SimulatedPlayer` policies standing
in for human playtesters:

- **n** players, balanced across the three primary tendencies
  (kindness / control / defiance), with a **lean** swept from `LEAN_MIN = 0.50`
  (weakly leaning) to `LEAN_MAX = 1.00` (a pure persona). The floor sits above
  chance on purpose: the fully-erratic player is the *escape exception*
  ([`docs/game_design.md`](./game_design.md) §12), not the typical playtester.
- Each player chooses by **disposition**: with probability `lean` they take their
  primary tendency, otherwise one of the others. The choice is resolved by
  *tendency*, so by default it is **independent of how the Mirror presents the
  scene** — the conservative null that the adaptation has no behavioural pull.

**Consequence, stated up front.** The model's prediction is a *render* that fires
in **every** arm, and a presentation-independent player's choices do not change
with the arm. So under the canonical (null) population the two arms produce
**identical** decision points and the locked *prediction* metric **cannot
separate them by construction** — exactly the `baseline ≡ adaptive` structural
parity the build already gates on
([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md)). The
binding adaptive-vs-shell **feel** question is therefore *out of reach of this
metric* and awaits a subjective/human instrument (deferred to M2+ per the M1
scope proposal). This playtest still runs and scores both arms and states
honestly what the metric can and cannot conclude.

To show the harness is **not blind to an effect** when one exists, the player
model carries an optional `suggestibility` (a primacy pull toward the
first-surfaced choice — the prediction, in the adaptive arm; the game's own
predictive-nudging thesis, [`game_design.md`](./game_design.md) §4.6). It is
`0.0` for the locked canonical run; positive values are a *what-if* used only to
prove the decision rule reaches PASS when the adaptive arm genuinely pulls ahead.

## 9. Reproducing

```
python -m game.playtest                 # canonical run: n=30, seed=42, fixed baseline
python -m game.playtest --baseline random   # placebo control
python -m game.playtest --n 60          # larger sample
python -m game.playtest --json          # machine-readable result
```

Deterministic and offline: the same `(n, seed, baseline)` reproduces the same
verdict byte-for-byte, in any process. Exit code: `0` PASS, `1` FAIL,
`3` INCONCLUSIVE.

## 10. Amending

This is the method, not the metric. To change **n**, the **effect threshold**,
the **population**, or the **decision rule**, edit the constants in
[`game/playtest.py`](../game/playtest.py) (the single source of truth), update
§§3–8 here to match, re-run the suite, and re-date the header. To change the
**metric/thresholds**, that is a founder action in [`THESIS.md`](./THESIS.md) §4.
