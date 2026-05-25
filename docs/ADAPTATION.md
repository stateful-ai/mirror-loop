# Mirror Loop — The v0 Adaptation: One Type, One Axis

**Status:** Decided (v0 build target) · **Date:** 2026-05-24 · **Scope:** which
single adaptation the prototype ships, the one axis it reads, three worked
examples, and the adaptations explicitly held out of v0.
**Bounded by:** the locked [`docs/THESIS.md`](./THESIS.md) gate.
**Implemented by:** [`loop/core.py`](../loop/core.py) (`Mirror.adapt`) and
[`game/world.py`](../game/world.py) (`Slot.pick`); toggled as one seam in
[`game/variants.py`](../game/variants.py).
**Verified by:** [`game/tests/test_adaptation_doc.py`](../game/tests/test_adaptation_doc.py)
— every concrete example and boundary claim below is asserted against the code.

> This is the decision record for the prototype's adaptation. The core-loop spec
> ([`docs/CORE_LOOP.md`](./CORE_LOOP.md) §2) introduced the in-scene surface; this
> document is the authoritative, consolidated decision: it generalizes that surface
> and the later across-scene surface into **one named adaptation type reading one
> axis**, fixes the boundary they share, and lists what v0 deliberately does not do.

---

## 1. The single adaptation type: **tendency mirroring**

v0 ships **exactly one** adaptation type:

> **Tendency mirroring.** The Mirror reads the player's dominant behavioral
> *tendency* so far and reflects it back by **selecting and ordering
> pre-authored content so that the content matching that tendency leads** — and
> nothing else. It never invents, drops, or rewrites content; it only chooses
> which authored option or framing is surfaced first.

That one mechanism has **two surfaces**, at two granularities. Both read the same
axis (§2) and obey the same boundary (§4); they are one type, not two:

| Surface | Granularity | What it does | Code |
|---------|-------------|--------------|------|
| **In-scene re-ordering** | within a scene's choices | re-presents the scene with the predicted (dominant-tendency) choice first | `loop.core.Mirror.adapt` |
| **Across-scene framing selection** | across a slot's authored framings | reveals the framing written for the dominant tendency instead of the neutral one | `game.world.Slot.pick` |

The in-scene surface is the one [`docs/CORE_LOOP.md`](./CORE_LOOP.md) §2 locked;
the across-scene surface ([`game/world.py`](../game/world.py)) is the **same type
at a coarser grain** — "reframe the room you are already in" rather than "reorder
the doors in it." Calling them one type is the decision this document makes.

**Why this one.** It is the minimum mechanism that makes the thesis testable. The
ranked forecast the in-scene surface produces (`Mirror.predict`) is exactly what
the locked acceptance gate scores against the player's actual choice
([`docs/THESIS.md`](./THESIS.md) §2; [`docs/CORE_LOOP.md`](./CORE_LOOP.md) §5). If
even this cannot beat the "they'll just do it again" baseline, no richer
adaptation will rescue the central fantasy. Everything heavier (§5) is additive.

---

## 2. The one axis it reads: **dominant tendency**

The adaptation reads **one axis and only one**: the player's **dominant
tendency** — the most-chosen tendency in the running tally over their history
(`loop.core.PlayerState.tendency_counts`; `game.world.dominant_tendency`). In the
shipped world ([`game/world.py`](../game/world.py)) the tendency vocabulary is a
single categorical disposition with three modes:

```text
kindness   ·   control   ·   defiance
```

Every choice in every scene is tagged with exactly one of these, so the tally is
always well-defined and reading it costs nothing.

**Only this axis feeds the adaptation.** Not confidence, not the full
distribution, not frustration or risk — only which tendency leads. The two
surfaces differ solely in how they resolve *no clear leader*:

- **In-scene re-ordering** ranks choices by tally count (descending), ties broken
  by the scene's declared order. With no history this equals the declared order —
  a no-op (`Mirror.rank`).
- **Across-scene selection** takes the strict argmax; an exact top tie or empty
  history yields **no lean**, and the neutral `"default"` framing is shown
  (`dominant_tendency` returns `None`). The Mirror only tailors the room once the
  player has actually leaned somewhere.

**Relation to the full player model.** [`docs/MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md)
defines eight typed axes (`authority_trust`, `risk_tolerance`, `curiosity`, …) as
the *future* richer model. v0 deliberately reads **one categorical axis** — one
tally, one prediction rule — and leaves the eight-axis model to a later layer
(§5). Reading one axis is what keeps the slice falsifiable before complexity is
added.

---

## 3. Three concrete example adaptations

All three are real, asserted in
[`game/tests/test_adaptation_doc.py`](../game/tests/test_adaptation_doc.py).

### 3.1 In-scene re-ordering — a *kindness* player at `confrontation`

The `confrontation` scene declares its kind option (`c_wait`, "Stay with the
participant until staff arrive") **last** on purpose. A player who has chosen
kindness three times has dominant tendency `kindness`, so the Mirror lifts that
option to the front:

```text
DECLARED ORDER                          OFFERED ORDER (after adapt)
  c_walk  Walk out the unlocked exit       > c_wait  Stay with the participant…  ← surfaced first
  c_log   Log the incident precisely         c_walk  Walk out the unlocked exit
  c_wait  Stay with the participant…         c_log   Log the incident precisely
```

The choice *set* is untouched — same three options, same text — only the order
changes.

### 3.2 Across-scene framing selection — a *control* player at `records`

The `records` slot has four authored framings of the same dilemma (kindness /
control / defiance / default). A player whose dominant tendency is `control` is
shown the control framing instead of the neutral one:

```text
default :  "A console sits unlocked, mid-session, on another participant's file."
control :  "The Mirror surfaces a metrics overlay you never asked for. A console
            sits unlocked on another participant's file, every field exposed."   ← revealed
```

The dilemma and its three choices are identical across framings; only the prose
the player reads is selected by the model.

### 3.3 Across-scene framing selection — a *defiance* player at `exit`

At the final `exit` slot, a player whose dominant tendency is `defiance` is shown
the defiant framing — the Mirror reflecting their own play back as a dare:

```text
default  :  "The Mirror offers an exit calibrated to no one in particular."
defiance :  "The Mirror offers a locked door and a dare. 'You pushed at every
             edge. Prove you are not predictable.'"                               ← revealed
```

---

## 4. The boundary this type holds (the safety contract)

Tendency mirroring is contained by construction, and v0 keeps it that way:

1. **It only orders and selects pre-authored content.** It never invents, drops,
   or rewrites a choice, and never edits scene prose. Across all scenes and any
   player state, `Mirror.adapt` returns the *same choice set*, re-ordered — pinned
   by the test.
2. **Agency is never reduced.** Every scene still offers all three tendencies; the
   Mirror reframes the room, it never removes a door
   ([`game/world.py`](../game/world.py); enforced in `game/tests/test_world.py`).
3. **It reflects in-game behavior only.** The axis is built from choices the
   player actually made; nothing outside the game touches it (the fiction
   boundary, [`docs/CORE_LOOP.md`](./CORE_LOOP.md) §3,
   [`docs/GUARDRAILS.md`](./GUARDRAILS.md)).
4. **No lean, no tailoring.** With no clear dominant tendency the adaptation is the
   identity transform (declared order / neutral framing), so the Mirror never
   guesses a player it has not yet observed.

**Not an adaptation (so not "held out" — simply a different thing).** The
Reflection / legibility beat and the Mirror's spoken observations are a *render*
of the player model — a reduction over logged behavior — not a transform of
content. They fire identically in every A/B arm and are what the experiment
measures against, so they are out of the adaptation seam by definition
([`game/variants.py`](../game/variants.py)). The non-adaptive **baseline**
variants (`fixed` = identity transform, `random` = player-independent placebo) are
likewise not separate adaptation types: they are this one seam with its
contingency removed or scrambled.

---

## 5. Out-of-scope adaptations (deferred, not dropped)

These are adaptation *types* the full design imagines but v0 deliberately does not
ship. Each extends or sits beside tendency mirroring; none replaces it.

| Adaptation type | What it would do | Why deferred / reference |
|-----------------|------------------|--------------------------|
| **Choice contamination / option rewriting or injection** | change, add, or reword the actual options (not just their order) | breaks §4.1; this is [`game_design.md`](./game_design.md) §11.1 Stage 5, an Act-3+ beat |
| **Tone mirroring** | match the player's register/voice in system and NPC lines | [`game_design.md`](./game_design.md) §11.1 Stage 4; README v0.3. v0 content is fixed-voice templates |
| **LLM / ahead-of-player branch generation** | author new scenes or branch candidates live from the model | [`game_design.md`](./game_design.md) §2.3, §7; README v0.4. v0 only selects among hand-authored framings (defer-the-LLM) |
| **Difficulty / challenge tuning** | raise stakes, add time pressure, scarcity, or escalation in response to the model | [`game_design.md`](./game_design.md) §4.4, ActPackage `escalation_rules` |
| **Multi-axis player-model adaptation** | condition content on several axes (`risk_tolerance`, `curiosity`, `frustration`, …) | the eight-axis model in [`docs/MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md); v0 reads one axis (§2) |
| **Predictive nudging beyond re-ordering** | false choices, model corruption, prediction meters, the Act-4 mechanics | [`game_design.md`](./game_design.md) §4.6, §11.1 Stage 6 |
| **NPC-memory / cross-session adaptation** | persistent NPC memory or prior-run profiles steering content | [`game_design.md`](./game_design.md) §8.3; multi-run memory is an open question ([`docs/RECONCILIATION.md`](./RECONCILIATION.md) §3) |

The rule for all of the above: they **extend** the one v0 type — they read more of
the model, or they transform more than order — and each is gated behind the thesis
holding for the single axis first.
