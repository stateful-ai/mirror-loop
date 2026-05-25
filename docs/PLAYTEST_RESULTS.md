# Mirror Loop — Blind A/B Playtest Results (canonical run)

**Status:** Reported · **Date:** 2026-05-25 · **Verdict:** **INCONCLUSIVE**
**Method (pre-registered):** [`docs/PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md)
**Metric (founder-locked):** [`docs/THESIS.md`](./THESIS.md) §2
**Harness:** [`game/playtest.py`](../game/playtest.py) · reproduce with
`python -m game.playtest --seed 42`

> This is the scored run, judged against the rule fixed *before* scoring in
> [`PLAYTEST_METHOD.md`](./PLAYTEST_METHOD.md). It is deterministic: the command
> above reproduces every number here byte-for-byte.

---

## 1. Verdict

**INCONCLUSIVE.** Across 30 sessions per arm, the adaptive and baseline arms are
**identical** on the locked prediction metric (Δ mean top-1 = +0.000), so the A/B
contrast — the primary endpoint — detects no effect to attribute to the
adaptation. The result is **not** a thesis FAIL (the adaptation is not
counterproductive) and **not** a PASS (no separation, and the population mean sits
just under the locked floor). The binding adaptive-vs-shell *feel* question is out
of reach of this metric and awaits human playtesters (deferred to a later
milestone).

## 2. Run output (verbatim)

```
[INCONCLUSIVE] Blind A/B Playtest — adaptive vs. baseline
  method     : Beats-Baseline Prediction Test (docs/THESIS.md), pre-registered in docs/PLAYTEST_METHOD.md
  n per arm  : 30 sessions   seed: 42   effect threshold (Δ top-1): 0.05
  gate (locked): mean top-1 >= 0.60 AND mean margin >= 0.15   (pass-rate = fraction of sessions individually passing the gate)

  arm                     n    top-1    margin   baseline   pass-rate  gate
  -------------------------------------------------------------------------
  adaptive (adaptive)    30    0.573    +0.373      0.200       0.567  FAIL
  baseline (fixed)       30    0.573    +0.373      0.200       0.567  FAIL

  A/B contrast : Δ mean top-1 = +0.000   Δ mean margin = +0.000   arms separated: no
```

Exit code `3` (INCONCLUSIVE). The `random` placebo baseline gives the same
verdict (Δ mean top-1 = −0.027, still within the ±0.05 effect threshold; the
small offset is prediction tie-break noise from the placebo's shuffled order, not
a player-driven effect).

## 3. Why the arms are identical (the central finding)

The Mirror's prediction is a **render** of the player model — it is logged in
*every* arm, adaptive or baseline ([`docs/ADAPTATION.md`](./ADAPTATION.md) §4). A
simulated player chooses by behavioural disposition, independent of the order or
framing the Mirror presents (the conservative null). So for the same player the
two arms produce **byte-identical** `(predicted_actions, actual_action)` logs, and
the locked *prediction* metric scores them identically. This is the same
`baseline ≡ adaptive` structural parity the build already gates on in CI
([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md)). The
honest consequence: **this metric cannot, by construction, separate the arms.**
What the adaptation changes is *which framing the player reads and which choice
leads* — a presentation/feel difference the prediction metric does not see.

## 4. Evidence: the predictability gradient (adaptive arm; baseline identical)

The population is a transparent sweep of "lean" from 0.50 (weakly leaning) to 1.00
(a pure persona), balanced across the three tendencies. Predictability rises with
lean, exactly as the thesis expects — the population mean (0.573) averages over a
genuine mix rather than a hand-picked cohort:

| lean band | n | mean top-1 | mean margin | sessions passing the locked gate |
|-----------|---|-----------|-------------|----------------------------------|
| [0.50, 0.66) | 10 | 0.480 | 0.280 | 4 / 10 |
| [0.66, 0.83) | 10 | 0.460 | 0.260 | 4 / 10 |
| [0.83, 1.00] | 10 | 0.780 | 0.580 | 9 / 10 |
| **all** | **30** | **0.573** | **0.373** | **17 / 30** |

Read-out: strongly-leaning players are robustly predicted (top band 0.780 top-1,
9/10 clear the locked gate), confirming the model *does* beat the
most-frequent-action baseline by a wide margin (note mean baseline is only 0.200 —
distinct choice ids per scene mean a dumb "repeat your most-frequent action"
predictor scores ~1/5). The population mean lands just under the 0.60 floor
because half the cohort leans only weakly. That floor-relationship is a property
of the **population and the five-loop session length**, not of the adaptation —
and since the arms are identical, it is shared by both. The locked gate's binding
use remains a single *real* playtested session ([`THESIS.md`](./THESIS.md) §2),
which this simulation does not substitute for.

## 5. The harness is not blind to an effect

To show the decision rule is discriminating and not structurally pinned to
INCONCLUSIVE, the same population was re-run with the player model's
`suggestibility` raised to 0.8 — the game's own predictive-nudging hypothesis
([`docs/game_design.md`](./game_design.md) §4.6), where an off-primary player is
pulled toward the first-surfaced choice (the prediction, in the adaptive arm):

| population | adaptive top-1 | baseline top-1 | Δ top-1 | adaptive gate | verdict |
|------------|---------------|----------------|---------|---------------|---------|
| canonical (suggestibility 0.0) | 0.573 | 0.573 | +0.000 | FAIL | **INCONCLUSIVE** |
| nudgeable (suggestibility 0.8) | 0.780 | 0.693 | +0.087 | PASS | **PASS** |

When players are nudgeable, the adaptive arm pulls ahead by more than the effect
threshold *and* clears the locked gate → the rule returns **PASS**. So the
canonical INCONCLUSIVE is a true reading of the conservative-null population, not
an artifact of a rule that can never say anything else. (This nudge run is a
*what-if* for harness validation; it is not the locked canonical result.)

## 6. Conclusions

1. **Acceptance bar met for this task.** ≥30 sessions per arm were collected per
   the locked method, scored against the locked metric, with a written
   pass/fail/inconclusive verdict and the evidence above.
2. **The verdict is INCONCLUSIVE**, and honestly so: on the locked *prediction*
   metric the adaptive and baseline arms are indistinguishable by construction, so
   this A/B cannot attribute the experience to the adaptation.
3. **What is established:** the predictability engine works where the thesis says
   it should — strongly-leaning players are predicted well above the
   most-frequent-action baseline (top band: 0.780 top-1, +0.580 margin).
4. **What is not established:** that the *adaptation* (vs. the shell) is what
   carries the feeling. That is a subjective/feel question
   ([`game/variants.py`](../game/variants.py)) the prediction metric structurally
   cannot answer.
5. **Recommendation:** to make this A/B decisive, introduce the deferred
   instrument that the arms can actually differ on — human playtesters (or a
   subjective/feel measure), played against the `random` placebo for blinding.
   The harness, decision rule, and locked metric are in place and proven
   discriminating; only the human signal is missing.
