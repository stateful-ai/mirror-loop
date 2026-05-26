# Mirror Loop — Questionnaire Intake → Seed-Event Encoding

**Status:** Defined · **Date:** 2026-05-25 · **Scope:** the deterministic
mapping from a questionnaire JSON answer set to the initial sequence of Mirror
events that reduces into the starting [`MirrorState`](../mirror/state.py).
**Implemented by:** [`mirror/intake.py`](../mirror/intake.py).
**Verified by:** [`mirror/tests/test_intake.py`](../mirror/tests/test_intake.py)
— every question, every answer, and the full encoding for a worked example are
pinned against the code.
**Bounded by:** the locked schema in [`docs/MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md);
the questionnaire design in [`docs/game_design.md`](./game_design.md) §5.

> The opening lab questionnaire (`game_design.md` §5) is the first place the
> Mirror can seed its player model — before the player has made an in-fiction
> choice the system can observe. This document is the contract that turns a
> questionnaire JSON blob into the initial slice of the append-only event log
> the reducer folds into a starting [`MirrorState`](../mirror/state.py). The
> mapping is **deterministic and total**: same answers in → byte-identical
> events out, in a fixed catalog order, regardless of dict iteration order.

---

## 1. Why this lives in the event log (not a separate "intake state")

The locked architecture rule
([`MIRROR_SCHEMA.md`](./MIRROR_SCHEMA.md) §6, [`SCHEMAS.md`](./SCHEMAS.md) §0) is
that the **append-only event log is the only source of truth**, and the Mirror
is a pure reduction over it. The questionnaire is no exception: an intake answer
is encoded as a real
[`ChoiceObserved`](../mirror/log.py) event with typed
[`Signal`](../mirror/state.py)s, and reduces through the same
[`reduce()`](../mirror/log.py) that processes in-fiction play. Concretely this
means:

- **No new state primitive.** "Starting MirrorState" = the reduction of the
  intake events alone, computed from `mirror.intake.seed_state(answers)`.
- **The questionnaire is part of the log.** Resuming a saved session replays
  the intake events first, with no special-case bootstrap; the reducer would
  produce the same state if you fed it the JSON for the hundredth time.
- **Persistence stays trivial.** The questionnaire answers are not stored as
  authoritative; the events are. The schema-version + fingerprint guard
  ([`mirror/log.py`](../mirror/log.py)) applies unchanged.

The events are tagged with `scene_id="intake_questionnaire"` and a self-
describing `choice_id="intake:<question_id>:<answer_id>"`, so a downstream
reader can cleanly separate the questionnaire prelude from in-fiction play with
one filter.

---

## 2. The questionnaire JSON

A questionnaire submission is a flat object mapping `question_id → answer_id`:

```json
{
  "preferred_experience": "mystery",
  "preferred_difficulty": "some_resistance",
  "problem_solving": "talk",
  "authority_disposition": "question",
  "avoid_in_experience": "nothing"
}
```

**Optional questions.** A missing key is treated as "skipped" and emits no
event. Passing `{}` is valid and reduces to the blank mirror (every axis
unknown, confidence 0) — exactly as if the player hit "skip intake."

**Unknown keys are loud.** A `question_id` not in the catalog or an
`answer_id` not in that question's option set raises `KeyError` rather than
being absorbed. A malformed questionnaire is a bug; corrupt input fails fast
so the mush can't sneak in.

**Determinism guarantees.** The output event order is the catalog order
([`mirror/intake.py`](../mirror/intake.py) `QUESTIONNAIRE`), not the dict
iteration order. Two distinct dicts with the same content produce the
byte-identical event tuple, and JSON-roundtripping the resulting log is a
no-op.

---

## 3. The mapping (each answer → its signals)

Two design rules govern the signal weights:

1. **Declared preference is soft evidence.** Most answers carry `weight=0.5`
   (some `0.25`), not the in-fiction default `1.0`, so a single observed action
   in play can override a single questionnaire prior. This matches
   `game_design.md` §5.2 "dual interpretation": the stated preference is a seed,
   not the truth.
2. **Two axes are deliberately not seeded** from declared preference.
   `frustration` is a STATE axis (fast affect, decays each turn) — seeding it
   pre-play would relax to noise before the first scene. `boundary_testing`
   measures "do they actually poke the system" — only observable from in-
   fiction behavior, not a thing you can sincerely self-declare.

### 3.1 `preferred_experience` — "What kind of experience would you like today?"

| Answer | Signals |
|--------|---------|
| `mystery` | curiosity → +1 |
| `adventure` | risk_tolerance → +1; playstyle_mix ← exploration |
| `strategy` | playstyle_mix ← optimization |
| `survival` | risk_tolerance → −1; failure_recovery → +1 |
| `personal_growth` | moral_consistency → +1 |
| `moral_dilemmas` | moral_consistency → +1; playstyle_mix ← conversation |
| `power_fantasy` | authority_trust → −1; playstyle_mix ← combat |
| `social_drama` | playstyle_mix ← conversation |

### 3.2 `preferred_difficulty` — "How much resistance do you want?"

| Answer | Signals |
|--------|---------|
| `relax` | risk_tolerance → −1 |
| `some_resistance` | risk_tolerance → −1 (half weight) |
| `tested` | risk_tolerance → +1; failure_recovery → +1 |
| `consequences` | risk_tolerance → +1; moral_consistency → +1 |

### 3.3 `problem_solving` — "How do you usually solve problems?"

| Answer | Signals |
|--------|---------|
| `talk` | playstyle_mix ← conversation |
| `fight` | playstyle_mix ← combat; risk_tolerance → +1 (half weight) |
| `explore` | playstyle_mix ← exploration; curiosity → +1 (half weight) |
| `outsmart` | playstyle_mix ← optimization |
| `avoid` | risk_tolerance → −1 |
| `experiment` | playstyle_mix ← exploration; curiosity → +1 |

### 3.4 `authority_disposition` — "When someone in charge tells you what to do, you tend to…"

| Answer | Signals |
|--------|---------|
| `comply` | authority_trust → +1 |
| `question` | authority_trust → −1 (half weight); curiosity → +1 (half weight) |
| `refuse` | authority_trust → −1 |

### 3.5 `avoid_in_experience` — "What should the experience avoid?"

| Answer | Signals |
|--------|---------|
| `nothing` | (inert — recorded but emits no signal) |
| `failure` | failure_recovery → 0 (tilts pole; UNIT axis, low end is 0) |
| `loss` | risk_tolerance → −1 |
| `confusion` | curiosity → 0 (incurious pole; half weight) |
| `helplessness` | authority_trust → −1 |

---

## 4. Worked example

A "curious, cautious, talker" submits:

```json
{
  "preferred_experience": "mystery",
  "preferred_difficulty": "relax",
  "problem_solving": "talk",
  "authority_disposition": "question",
  "avoid_in_experience": "nothing"
}
```

`encode(answers)` emits the five events below, in this order:

1. `ChoiceObserved(choice_id="intake:preferred_experience:mystery", signals=(curiosity↑,))`
2. `ChoiceObserved(choice_id="intake:preferred_difficulty:relax", signals=(risk_tolerance↓,))`
3. `ChoiceObserved(choice_id="intake:problem_solving:talk", signals=(playstyle_mix←conversation,))`
4. `ChoiceObserved(choice_id="intake:authority_disposition:question", signals=(authority_trust↓, curiosity↑))`
5. `ChoiceObserved(choice_id="intake:avoid_in_experience:nothing", signals=())`

`seed_state(answers)` then reduces them to a starting [`MirrorState`](../mirror/state.py)
in which:

- `curiosity` is above its 0.5 neutral and has non-zero confidence.
- `risk_tolerance` is below its 0.0 neutral (cautious).
- `playstyle_mix` shows the conversation share above 0.25 (the uniform prior).
- `authority_trust` is below its 0.0 neutral (mildly defiant).
- `boundary_testing` and `frustration` remain at neutral with confidence 0 —
  the questionnaire deliberately does not seed them.

The unit test in
[`mirror/tests/test_intake.py`](../mirror/tests/test_intake.py)
pins this specific run, the per-question per-answer signal mappings, the
determinism contract, the strict rejection of unknown keys, and the
event-log round-trip.
