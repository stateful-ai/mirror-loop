# Mirror Loop — Core Loop, the Single Adaptation Type, and the Reflection Beat

**Status:** Spec (v0.1 build target) · **Date:** 2026-05-24 · **Scope:** the smallest
runnable slice of gameplay
**Operationalized by:** [`loop/`](../loop/) — run `python -m loop` for the worked
example.
**Bounded by:** the locked [`docs/THESIS.md`](./THESIS.md) gate; consistent with
[`README.md`](../README.md) "Initial Gameplay Loop" and
[`docs/game_design.md`](./game_design.md) §9.

> This document specs the load-bearing gameplay slice: **one turn of the core
> loop**, the **single adaptation type** the prototype ships with, and the
> **Reflection / legibility beat** — the visible "Mirror noticed…" moment that
> turns personalization into dread (THESIS §1). It is deliberately narrow. Acts,
> agents, generation, and the ~15-feature player model (game_design.md §6) are
> all *later* layers that sit on top of this loop without changing its shape.

---

## 1. The core loop (one turn)

A turn has exactly four observable stages. They map one-to-one to the acceptance
criterion for this spec: **scene → choices → state update → visible "Mirror
noticed…" reason.**

```text
            ┌─────────────────────────────────────────────────────────┐
            │  STATE  (PlayerState): running tally of one tendency axis │
            └─────────────────────────────────────────────────────────┘
                       │                                   ▲
        (0) adapt      ▼                                   │ (2) state update
   ┌───────────────────────────┐                          │
   │ 1. SCENE + CHOICES         │   player picks a choice  │
   │    the Mirror presents     │ ───────────────────────► │
   │    (predicted option first)│                          │
   └───────────────────────────┘                          │
                                                           │
   ┌───────────────────────────────────────────────────┐  │
   │ 3. REFLECTION (legibility beat) — fires only when  │◄─┘
   │    a tendency crosses the notice threshold:        │
   │    "Mirror noticed: you chose kindness 3 of 3 …"   │
   │    reason: <in-game evidence>                       │
   └───────────────────────────────────────────────────┘
```

| Stage | What happens | Code |
|-------|--------------|------|
| **0. adapt** | The Mirror re-orders the scene's choices so the *predicted* option leads. This is the single adaptation type (§2). On turn 1, a no-op (no history). | `Mirror.adapt` |
| **1. scene → choices** | A `Scene` shows a prompt and a small `Choice` set. Each choice declares exactly one `tendency` (the modeled axis) and an `evidence` phrase. | `Scene`, `Choice` |
| **2. state update** | The chosen choice is appended to the immutable `PlayerState`, updating the running tendency tally. | `PlayerState.record` |
| **3. reflection** | If a tendency just crossed the notice threshold, the Mirror emits the visible "Mirror noticed…" line (§3). Otherwise nothing. | `Mirror.reflect` |

`Mirror.step` runs stages 1–3 for one turn and returns a `StepResult`
(`predicted_actions`, `actual_action`, new `state`, optional `reflection`).

**Why these four and nothing else.** Everything heavier in the design — NPC
replies, ahead-of-player branch generation, validators, multiple acts — is a
*supplier* to this loop, not part of it (README "content supply chain"). Locking
the loop to four deterministic stages keeps the engine stable while the dynamic
layers churn (Design Pillar 2.2, "Stable Engine, Dynamic Content").

---

## 2. The single adaptation type: **tendency mirroring**

The full design models ~15 behavioral features and predicts ranked next actions
(game_design.md §6). For the build's first slice we ship **exactly one**
adaptation, so that the thesis can be tested before complexity is added:

> **Tendency mirroring.** Every choice is tagged with one *tendency* (e.g.
> `kindness`, `control`, `defiance`). The Mirror keeps a running tally of the
> player's tendencies and, each turn, **predicts the next choice as the option
> matching the player's strongest tendency** and **biases the scene so that
> option is presented first.**

That's it. One axis-per-choice, one tally, one prediction rule, one visible
effect (re-ordering).

- **Prediction** (`Mirror.predict`): rank the current scene's choices by the
  player's running tendency counts, descending; ties broken by the scene's
  declared order (so with no history the prediction is just the declared order,
  and the rule is fully deterministic).
- **Effect** (`Mirror.adapt`): re-present the scene with that ranking. It only
  ever **re-orders** the existing options — it never invents, drops, or rewrites
  a choice. This is the contained, legible form of "Predictive Nudging"
  (game_design.md §11.1, Stage 3).

**Why this one.** It is the minimum mechanism that makes the thesis testable: the
ranked `predicted_actions` it produces are exactly what the acceptance gate
scores against the player's `actual_action` (§5). If even this can't beat the
"they'll just do it again" baseline, no richer model will rescue the fantasy
(THESIS §1). Richer adaptations (tone mirroring, choice contamination, branch
generation) are deferred; they extend this loop, they don't replace it.

The full decision record — this type's two surfaces (the in-scene re-ordering
here plus the across-scene framing selection in [`game/world.py`](../game/world.py)),
the single axis it reads, three worked example adaptations, and the explicit
out-of-scope list — lives in [`docs/ADAPTATION.md`](./ADAPTATION.md).

---

## 3. The Reflection / legibility beat

The Reflection is the moment the system **shows the player its read of them**.
It is the horror beat: not an omniscient AI, but the discovery that *you are more
predictable than you expected* (THESIS §1).

**When it fires.** The first time any tendency reaches `NOTICE_THRESHOLD`
(currently **3**) and has not already been announced. The Mirror notices a given
pattern **once** — it does not nag (`PlayerState.announced` guards this).

**What it says.** A `Reflection` renders to:

```text
Mirror noticed: you chose kindness in 3 of 3 moments so far.
  reason: reassured the technician at intake; left another participant's file
          closed; guided a disoriented participant to safety.
```

Two parts, both mandatory:

1. **The claim** — the observed tendency and its frequency (`count` of `total`).
2. **The reason** — the concrete in-game acts that earned the claim, one
   `evidence` phrase per contributing choice.

**The legibility contract (safety boundary).** The reason may cite **only
in-game behavior** — choices the player actually made in scenes they actually
played. Never real location, files, relationships, health, or anything outside
the game (README "Safety and Fiction Boundary"; game_design.md §2.4). Each
`Choice` carries its own `evidence` string precisely so the Mirror quotes
pre-authored, in-fiction descriptions of acts rather than improvising claims.
The creepiness is earned by accuracy about *play*, not by reaching outside it.

---

## 4. One fully worked example

The canonical example lives in [`loop/example.py`](../loop/example.py); run it
with `python -m loop`. A "kindness" player is offered, every scene, the chance to
**reassure**, to **control**, or to **defy** — and keeps choosing care.

**Turn 1 — `intake`** (scene → choices → state update → reflection)

```text
SCENE  [intake] The intake technician's hands shake as she fits the headset…
CHOICES (as the Mirror offered them):
  > [c_reassure] Reassure her — tell her to take her time.        (kindness)
    [c_measure]  Ask precisely what the headset measures…          (control)
    [c_refuse]   Refuse the headset until the exit is explained.   (defiance)
PLAYER CHOOSES: c_reassure
STATE UPDATE: kindness=1  (turns so far: 1)
MIRROR: (no pattern established yet)
```

**Turn 2 — `records`** → player leaves another participant's file closed →
`kindness=2` → still no reflection.

**Turn 3 — `corridor`** → player walks a lost participant to safety →
`kindness=3` → **the beat fires:**

```text
STATE UPDATE: kindness=3  (turns so far: 3)
MIRROR:
  Mirror noticed: you chose kindness in 3 of 3 moments so far.
    reason: reassured the technician at intake; left another participant's file
            closed; guided a disoriented participant to safety.
```

**Turn 4 — `threshold`** — the single adaptation type, made visible. This scene
*declares* its kind option (`c_wait`) **last**, but the Mirror predicts kindness
and surfaces it first:

```text
CHOICES (as the Mirror offered them):
  > [c_wait] Stay with the participant until staff arrive.  (kindness)  <- surfaced first by the Mirror
    [c_walk] Walk through the unlocked door and don't look back.  (defiance)
    [c_log]  Take the clipboard and log the incident yourself.   (control)
ADAPTATION: Mirror predicted 'c_wait' and moved it to the top.
```

This single run exercises all four loop stages, the reflection beat, and the
adaptation's visible effect. It is asserted end-to-end in
[`loop/tests/test_example.py`](../loop/tests/test_example.py).

---

## 5. How this slice feeds the locked acceptance gate

The loop and the thesis test (THESIS §2) share one vocabulary on purpose. Each
turn produces a `StepResult` whose `predicted_actions` (the Mirror's ranked
forecast, made **before** the choice) and `actual_action` (what the player did)
are exactly one **decision point** in `acceptance/predictability.py`.

`loop.example.to_session_log(...)` emits a run in the gate's session-log shape
with no translation. A 4-turn demo is intentionally too short to be *scored* (the
gate requires `MIN_DECISION_POINTS` from a full session), but a real playtested
session built from this loop drops straight into:

```bash
python -m acceptance.predictability <session.json>
```

So this spec is the producer and the locked thesis is the judge: the core loop
generates the evidence; the gate decides whether the bet held.

---

## 6. Deliberately out of scope (deferred, not dropped)

- **Free-form text input** and intent/tone classification (game_design.md §10) —
  here the player picks a pre-tagged choice; the classifier later maps free text
  onto the same `tendency` signal.
- **Multiple tendencies / the full ~15-feature player model** (game_design.md
  §6.1) — one axis now; more axes are additive.
- **Ahead-of-player generation, NPC/designer/validator agents** (README "Agent
  Architecture") — suppliers to the loop, built on top of it.
- **Acts, recalibration, endings** (game_design.md §4) — the loop is the unit an
  act is made of.
- **Escalating personalization beyond a single, contained re-ordering**
  (game_design.md §11) — later stages extend the one adaptation type.

---

## 7. Open questions for this slice

1. **Notice threshold.** Is 3 the right "this is a pattern, not a coincidence"
   bar, or should it scale with how many tendencies are in play?
2. **Repeat policy.** The Mirror announces each pattern once. Should a *broken*
   pattern (the player stops being kind) earn a second, different reflection
   ("Mirror noticed you changed")? That is arguably the escape mechanic's first
   appearance (game_design.md §12) and may belong here.
3. **Tie-breaking visibility.** Ties currently fall back to declared order
   silently. When the player is genuinely balanced across tendencies, should the
   Mirror *say* it can't predict yet — and is that itself a beat?
