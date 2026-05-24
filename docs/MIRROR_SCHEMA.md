# Mirror Loop — The "Mirror" Player-State Schema

**Date:** 2026-05-24 · **Scope:** typed schema of inferred player attributes +
per-choice update rules + anti-mush coherence review · **Status:** Defined.

> The **mirror** is the system's model of the player — the reflection it builds
> from in-game behavior and feeds back as creepy personalization. This document
> defines that state: the inferred attributes, how each one moves per choice, and
> the review that keeps it from collapsing into mush. The schema is implemented
> in [`mirror/schema.py`](../mirror/schema.py) (the axes) and
> [`mirror/state.py`](../mirror/state.py) (the per-choice updates); the
> invariants below are enforced by `assert_coherent()` and the tests, not just
> asserted in prose.

---

## 1. Why coherence is load-bearing

The locked thesis ([`docs/THESIS.md`](./THESIS.md)) is that a lightweight player
model can **beat a naive baseline** at predicting the player's next choice. That
only happens if the inferred state carries *real, differentiated signal*. The
failure mode — call it **mush** — is a pile of vaguely-named scalars that are
redundant, all drift in the same direction, and sit at a confident-looking `0.5`
before the player has done anything. A mushy model predicts nothing the baseline
doesn't already get for free, and the central horror fantasy ("you are more
predictable than you expected") has no engine. So this schema is designed,
top to bottom, to make mush hard to introduce.

---

## 2. The schema (8 inferred axes)

Each axis has a **kind** (its shape), **dynamics** (its timescale), named **ends**,
and an **update rule**. Values start at neutral with **confidence 0** — nothing is
assumed about a player until they act.

### Kinds

- **unit** `[0, 1]` — a bounded magnitude with two named ends.
- **bipolar** `[-1, 1]` — a signed disposition between two named poles; rests at 0.
- **distribution** — a normalized budget over named modes (sums to 1).

### Dynamics

- **trait** — slow, sticky; accumulates evidence, never self-relaxes.
- **state** — fast, self-relaxing; spikes then decays back toward rest each turn.

### Axes

| Axis | Kind | Dynamics | Ends / modes | What moves it |
|------|------|----------|--------------|---------------|
| `playstyle_mix` | distribution | trait | combat / conversation / exploration / optimization | which activity a turn is spent on |
| `authority_trust` | bipolar | trait | defiant ↔ deferential | deferring to vs. resisting/defying the system |
| `risk_tolerance` | bipolar | trait | cautious ↔ reckless | taking the risky option when a safe one exists |
| `curiosity` | unit | trait | incurious ↔ probing | engaging optional content, lore, side hooks |
| `moral_consistency` | unit | trait | erratic ↔ principled | choices consistent with vs. contradicting priors |
| `boundary_testing` | unit | trait | in-bounds ↔ probes-system | poking exits, limits, the fourth wall |
| `failure_recovery` | unit | trait | tilts ↔ persists | the choice made right after a setback |
| `frustration` | unit | **state** | calm ↔ frustrated | live affective load; relaxes every turn |

---

## 3. How each attribute updates per choice

A player action is a [`Choice`](../mirror/state.py) carrying typed **signals**.
Each `Signal` is one piece of evidence about one axis. `MirrorState.apply_choice`
applies them; `tick()` advances one turn. The rules:

**Scalar axes (unit / bipolar).** A signal points the axis toward a `target`
value in its range (e.g. a defiant choice → `target = -1` on `authority_trust`),
with optional `weight ∈ (0, 1]`. The value takes a **bounded EWMA step**:

```
new = old + learning_rate · weight · (target − old)
```

Because that is a convex move toward `target`, the value can never overshoot its
range — one choice nudges, it cannot slam an axis to an extreme.

**Distribution axis (`playstyle_mix`).** A signal names the `mode` the turn was
spent on. The budget mixes toward a one-hot on that mode:

```
mix = (1 − α)·mix + α·onehot(mode),   α = learning_rate · weight
```

A convex combination of two distributions is still a distribution, so the budget
always sums to 1.

**Confidence.** Every applied signal bumps the axis's evidence count;
`confidence = 1 − 0.5^(evidence / halflife)` rises from 0 (unknown) toward 1.
The prediction loop should read from `known()` (confident axes) and **ignore
axes still at their neutral default** — predicting off a neutral is mush wearing
a confidence hat.

**Decay.** `tick()` relaxes every **state** axis toward its rest value
(`frustration → calm`); **traits** are untouched. Fast affect never gets
mistaken for a stable trait.

`apply_choice` returns the per-axis deltas, the same shape the event log records
as `player_model_updates` (see `game_design.md` §14).

### Worked example

A tense exit-probe choice:

```python
Choice("inspect_exit_under_pressure", signals=(
    Signal.toward("authority_trust", -1.0),   # defiant
    Signal.toward("boundary_testing", +1.0),  # probing the system
    Signal.spend("playstyle_mix", "exploration"),
    Signal.toward("frustration", +1.0, weight=0.5),  # mild, decays next tick
))
```

This moves four axes and **leaves the other four exactly where they were** — the
defining anti-mush behavior.

---

## 4. Anti-mush coherence review

The schema was reviewed against the invariants below. Each one targets a
specific way mush creeps in, and each is **executable** in
[`coherence_report()`](../mirror/schema.py) (run at import time and in the tests),
so the review cannot silently rot.

1. **Every axis names both of its ends** (or, for a distribution, ≥2 modes). An
   axis you cannot label at both ends measures nothing in particular.
2. **Ranges and neutrals are well-formed**; bipolar axes rest at exactly `0`.
3. **Learning rates and decays are bounded and sane** (`lr ∈ (0,1]`, `decay ∈ [0,1)`).
4. **Traits don't self-relax; states do** — the timescale split is explicit, not
   accidental.
5. **Distributions are genuine budgets** (≥2 distinct modes, uniform neutral),
   not independent scalars in disguise.
6. **Every axis carries a real description** — no nameless placeholders.
7. **Provenance is complete**: every seed §6.1 feature maps to a real axis or an
   explicit exclusion, and every axis traces back to the seed.

Two further guarantees live in the runtime rather than the static schema:

- **Unknown stays unknown.** A fresh state has confidence 0 everywhere; an
  unobserved axis never masquerades as a reading.
- **No global drift.** A choice moves only the axes it signals; a signal naming
  an unknown axis, an out-of-range target, or a bad weight is rejected, not
  absorbed.

### What changed from the seed (15 → 8)

The seed (`game_design.md` §6.1) lists fifteen loosely-named features. Several
are redundant or mistyped; consolidating them **is** the anti-mush review. The
mapping is encoded in `SEED_FEATURE_MAP` and tested for completeness.

| Seed feature(s) | Lands on | Why |
|-----------------|----------|-----|
| `combat_rate`, `conversation_rate`, `exploration_rate`, `loot_behavior` | `playstyle_mix` | These are **shares of a turn budget**, not independent rates — they necessarily trade off. Modeling them as four free `[0,1]` scalars is the textbook mush mistake; one normalized distribution captures the same thing coherently. (`loot_behavior` → the `optimization` mode.) |
| `authority_trust`, `agency_resistance`, `quest_following_rate` | `authority_trust` | The clearest mush in the seed: trust, resistance, and path-following are **one signed axis**. `agency_resistance` is the negative pole, not a separate number; following the offered quest is deference. Collapsed to one bipolar axis. |
| `risk_tolerance` | `risk_tolerance` | Kept as a bipolar disposition (cautious ↔ reckless). |
| `lore_engagement`, `curiosity_score` | `curiosity` | Both measure pull toward optional content; merged into one magnitude. |
| `moral_consistency` | `moral_consistency` | Kept, but defined as an observable: raised by choices consistent with priors, lowered by contradictions (`game_design.md` §6.2). |
| `system_boundary_testing` | `boundary_testing` | Kept (renamed). |
| `failure_recovery` | `failure_recovery` | Kept; only updated by the choice after a setback. |
| `frustration_risk` | `frustration` | Kept, but retyped as a fast-decaying **state**, not a trait — it answers "how do they feel now," not "who are they." |
| `prediction_confidence` | **excluded** | This is the model's confidence in its own *forecast* — a property of the prediction loop, not a fact about the player. It does not belong in the mirror state. In this implementation, confidence is tracked **per axis** from evidence instead. |

Net: fifteen loosely-typed features → **eight orthogonal, well-typed,
fully-provenanced axes**, every one independently observable and independently
movable. That is the coherence the thesis needs.

---

## 5. How to inspect / extend

- `python -m mirror` — print the schema and run the coherence review.
- Add or change an axis in `mirror/schema.py`; `assert_coherent()` runs at import
  and the tests (`mirror/tests/`) will fail if the change reintroduces mush or
  drops seed provenance.
- The mirror state is the **input** to the prediction loop; the
  `predicted_actions` it produces are scored by the locked acceptance gate
  ([`acceptance/predictability.py`](../acceptance/predictability.py)). This file
  defines the state; predicting from it is a separate, downstream piece.
