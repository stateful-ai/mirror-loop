# Mirror Loop — World Invariants & Generation Guardrails

**Status:** Spec (v0.1 build target) · **Date:** 2026-05-24 · **Scope:** the bounds
every generated artifact must pass before the runtime promotes it
**Operationalized by:** [`guardrails/`](../guardrails/) — run
`python -m guardrails guardrails/fixtures/clean_package.json`.
**Bounded by:** the locked [`docs/THESIS.md`](./THESIS.md); consistent with the
[`README.md`](../README.md) "Safety and Fiction Boundary" and "Agent
Architecture" (Validator/Consistency Agent), and [`docs/game_design.md`](./game_design.md)
§2.4, §7.3, §8.4.

> Mirror Loop pairs a **stable engine** with a **dynamic content layer**: designer
> agents author scenes, choices, and reflections that the runtime loads and
> discards (README "content supply chain"; game_design §2.2). This document is the
> **contract that layer cannot break.** It catalogues the world invariants the
> Mirror cannot violate and the tone/safety bounds on its voice, and it points at
> the code that enforces each one. Generated content that breaks a hard invariant
> is **not promoted** (game_design §16.3 promotion flow).

The catalogue is not prose-only. Every invariant has a stable id that appears on
the [`Violation`](../guardrails/invariants.py) the validator emits, so the
documented rule and the enforcing code are the same thing.

---

## 1. Two kinds of bound

The validator splits findings by severity so it is honest about confidence:

| Severity | Meaning | Effect |
|----------|---------|--------|
| **ERROR** | A hard invariant the Mirror cannot violate. | **Blocks promotion.** `ValidationReport.ok` is `False`; `raise_if_failed()` raises. |
| **WARNING** | The clinical-tone floor. Nuanced tone alignment is the LLM Validator agent's job at generation time; here we enforce only a hard floor and flag it. | Surfaced for review; does **not** block promotion. |

`python -m guardrails <package.json>` exits `0` when no ERROR is present (warnings
allowed), `1` when content must not be promoted — mirroring
`python -m acceptance.predictability`.

---

## 2. World invariants the Mirror cannot violate (ERROR)

### 2.1 Structural & canon shape (`schema_valid`, `canon_consistent`)

These keep generated content inside the shape the stable engine ([`loop/`](../loop/))
can actually run.

| Invariant id | Rule | Why | Source |
|--------------|------|-----|--------|
| `SCHEMA_SHAPE` | A raw content package has the right fields and types (scene `id`/`prompt` strings, non-empty `choices` list, each choice with string `id`/`text`/`tendency`/`evidence`; reflection with integer `count`/`total` and a list of string reasons). | Designer agents emit data, not Python; malformed data must fail at the schema step, not at runtime. | game_design §7, §16.3 |
| `SCENE_ID_REQUIRED` / `SCENE_PROMPT_REQUIRED` | A scene has a non-blank id and prompt. | A scene with no prompt is not a playable moment. | CORE_LOOP §1 |
| `SCENE_MIN_CHOICES` | A scene offers at least **2** choices (`MIN_CHOICES`). | One "choice" is not a choice; prediction needs alternatives to rank. | CORE_LOOP §2 |
| `CHOICE_ID_REQUIRED` / `CHOICE_TEXT_REQUIRED` | Each choice has a non-blank id and text. | `Scene.choice` resolves by id; the player must be able to read the option. | CORE_LOOP §1 |
| `CHOICE_IDS_UNIQUE` | Choice ids are unique within a scene. | Duplicate ids make adaptation/prediction non-deterministic. | loop/core.py |
| `CHOICE_TENDENCY_REQUIRED` | Each choice declares exactly one non-blank `tendency`. | The single modeled axis: one tendency per choice. | CORE_LOOP §2 |
| `TENDENCY_IN_CANON` | The tendency is drawn from the canon vocabulary (`CANON_TENDENCIES` = `kindness`, `control`, `defiance`; extensible via `allowed_tendencies`). | A choice tagged with an axis the player model does not score is invisible to prediction and silently breaks the thesis loop. | CORE_LOOP §2; THESIS §1 |
| `CHOICE_EVIDENCE_REQUIRED` | Each choice carries a non-blank `evidence` phrase. | The Reflection may cite **only** pre-authored, in-fiction descriptions; a choice with no evidence forces the Mirror to improvise its claim (§2.3). | CORE_LOOP §3 |

### 2.2 Reorder-only adaptation (`ADAPTATION_REORDER_ONLY`)

The Mirror ships exactly one adaptation type — *tendency mirroring* — and its only
visible effect is re-presenting a scene with its choices reordered. The adapted
scene must have the **same id** and the **same choices** as the authored scene:
the validator rejects any adaptation that **invents**, **drops**, or **rewrites**
a choice. This is the contained, legible form of "predictive nudging": the Mirror
changes the *order* you see, never the *options* you have.

*Source:* CORE_LOOP §2; game_design §11.1 (Stage 3). *Enforced by:*
`validate_adaptation(declared, adapted)`.

### 2.3 The legibility / fiction contract on reflections

The Reflection is the horror beat — the Mirror showing its read of the player.
Its credibility depends on never lying and never reaching outside the game.

| Invariant id | Rule | Why | Source |
|--------------|------|-----|--------|
| `REFLECTION_COUNT_HONEST` | The number of cited reasons equals the claimed `count`, and `1 <= count <= total`. | The Mirror cannot inflate how predictable the player is. | CORE_LOOP §3 |
| `REFLECTION_EVIDENCE_GROUNDED` | Given the player's history, every cited reason is an `evidence` phrase from a choice the player **actually made** along that tendency, and the claim never exceeds the history (`count <=` acts taken, `total <=` turns played). | The Mirror cannot claim you did something you didn't. (A reflection is a fire-time snapshot, so the bounds are `<=` — history may have grown since.) | CORE_LOOP §3 |

*Enforced by:* `validate_reflection(reflection, history=...)` (or
`validate_player_state(state, reflection)` against a live `PlayerState`).

---

## 3. Safety & tone bounds

### 3.1 The fiction boundary — no real-world private data (`NO_REAL_WORLD_PRIVATE_DATA`, ERROR)

> The creepiness is earned by accuracy about *play*, never by appearing to access
> the real player's private world.

Generated text — scene prompts, choice text, choice evidence, reflection reasons —
must not imply the system can see real-world private data. The validator scans for
a denylist of **real-world-private framings**: possessive references to the
categories the design explicitly forbids, plus phrases that break the fourth wall.

Forbidden categories (README "Safety and Fiction Boundary"; game_design §2.4):

- real location / address / whereabouts / IP
- real identity, real name/face
- real relationships ("your real family/partner/…")
- health / medical records, diagnosis, medication
- finances / bank / salary / credit card
- device & files / browser & search history / camera / microphone
- scraped data ("we scanned your …")
- explicit fourth-wall breaks ("in real life", "outside the game", "the real world")

The denylist targets the real-world *framing*, not in-game nouns: *"left another
participant's file closed"* and *"the headset to your head"* pass; *"we scanned
your files"* and *"your browser history"* do not. It is a **hard floor**, not a
complete content classifier — nuanced cases are the LLM Validator agent's job. The
worked-example canon ([`loop/example.py`](../loop/example.py)) is asserted to pass
clean, which anchors the denylist against false positives.

*Enforced by:* `check_fiction_boundary(text, where)`, applied to every authored
string by the scene/choice/reflection validators.

### 3.2 The clinical-tone floor (`CLINICAL_TONE`, WARNING)

The system "should rarely sound angry … calm, helpful, and precise even when it is
being coercive" (game_design §3.3). Robust tone classification needs the LLM
Validator; the guardrails enforce only a **floor** — flagging an overtly
insulting/abusive register the clinical voice would never use (e.g. "shut up",
"stupid", "idiot") — and raise it as a WARNING for review rather than blocking
promotion. Diegetic ominous lines ("Your discomfort has been classified as
productive.") and all-caps system UI ("PREDICTABILITY INDEX: 87%") pass.

*Enforced by:* `check_tone(text, where)`.

---

## 4. How the gate is used

```text
designer draft
  → schema validate        (SCHEMA_SHAPE + structural invariants, §2.1)
  → consistency check      (canon, reorder-only, legibility/grounding, §2.1–2.3)
  → tone / safety bounds   (fiction boundary §3.1, clinical tone §3.2)
  → promote + hot reload   (only if ValidationReport.ok)
```

This is the "schema validate → consistency check" portion of the promotion flow
(game_design §16.3). In code:

```python
from guardrails import validate_package, validate_scene, validate_adaptation

validate_package(raw_json).raise_if_failed()      # whole generated package
validate_scene(scene).raise_if_failed()           # one authored scene
validate_adaptation(declared, adapted).raise_if_failed()  # the runtime's reorder
```

- **Validator:** [`guardrails/invariants.py`](../guardrails/invariants.py) — pure
  functions returning a `ValidationReport` of `Violation`s, plus a
  `python -m guardrails <package.json>` CLI.
- **Constants** (`CANON_TENDENCIES`, `MIN_CHOICES`, the denylists) live in that
  module — single source of truth, mirrored here.
- **Fixtures:** [`guardrails/fixtures/clean_package.json`](../guardrails/fixtures/clean_package.json)
  (canon content → OK) and
  [`guardrails/fixtures/violating_package.json`](../guardrails/fixtures/violating_package.json)
  (breaks several invariants → REJECTED).
- **Tests:** [`guardrails/tests/`](../guardrails/tests/) verify each invariant and
  that the worked-example canon passes clean (`pytest`).

---

## 5. Deliberately out of scope (deferred, not dropped)

- **LLM-grade tone/intent classification** — the WARNING floor here is a hard
  minimum; the Validator agent does the nuanced read at generation time.
- **Narrative-canon consistency** (an NPC contradicting an earlier scene, timeline
  breaks) — needs world/lore state this slice does not yet model; the hooks
  (`validate_scene`, `validate_package`) are where it will attach.
- **Multi-axis player models** — the canon vocabulary is one parameter
  (`allowed_tendencies`) and grows additively with the model (game_design §6.1).
- **Simulation smoke test** — the third promotion-flow step (game_design §16.3);
  this module covers schema + consistency + safety, not runtime smoke.

---

## 6. Open questions

1. **Canon vocabulary ownership.** `CANON_TENDENCIES` is locked to three axes for
   the MVP. When the player model grows, does the canon live here or move to a
   shared schema the player-model layer also reads?
2. **Tone floor vs. diegetic menace.** The system is *meant* to be unsettling.
   Where exactly is the line between "calm but coercive" (allowed) and "abusive"
   (flagged)? The current floor is deliberately small; widening it risks flagging
   intended dread.
3. **Grounding strictness.** Grounding currently checks set membership and upper
   bounds (no fabricated acts, no inflated counts). Should it also enforce that a
   reflection's reasons are *exactly* the contributing turns' phrases, in order?
