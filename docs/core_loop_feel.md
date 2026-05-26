# Mirror Loop — Core Loop Feel-Spec (the 30s beat)

**Status:** Canonical (M1) · **Date:** 2026-05-26 · **Scope:** the player-perceived
feel of one core-loop beat — what a single turn must *be like* in seat, distinct
from the structural slice locked in [`docs/CORE_LOOP.md`](./CORE_LOOP.md).
**Grounded in:** the locked thesis ([`docs/THESIS.md`](./THESIS.md) §1); the
locked M1 brief ([`docs/mirror_loop_m1_founder_brief.md`](./mirror_loop_m1_founder_brief.md)
"Locked"); the tone bible ([`docs/game_design.md`](./game_design.md) §3.3); the
safety boundary ([`docs/GUARDRAILS.md`](./GUARDRAILS.md)).
**Referenced by:** ADR-0001 (M1 locks — planned, [`docs/adr/README.md`](./adr/README.md)).

> A **beat** is one core-loop turn — scene → choices → state update → optional
> Reflection ([`docs/CORE_LOOP.md`](./CORE_LOOP.md) §1). CORE_LOOP locks the
> *structure*; this doc locks the *feel*. The two read in parallel: if the engine
> is doing what CORE_LOOP says and the player still doesn't feel what is below,
> the bug is here, not there.

---

## 1. The 30-second envelope

One beat is a **~30-second player envelope**, not a compute budget. It is the
time a player spends *inside* a beat: read the prompt, weigh three choices, pick
one, see the state advance, and — when it fires — read the Reflection line. A
session is **3–5 beats** ([`docs/SESSION.md`](./SESSION.md) §1), so a founder
cold-run reaches Reflection in well under five minutes ([founder brief
DoD §7](./mirror_loop_m1_founder_brief.md)).

| Phase of the beat | Player-perceived budget | What the player is doing |
|---|---:|---|
| Read prompt (2–4 short lines) | ~10 s | Take in the room |
| Weigh choices (3, each one tendency-tagged) | ~15 s | Recognise which "you" each option asks for |
| Pick + state advance | ~2 s | Commit; the world acknowledges, no animation |
| Reflection (when it fires) | ~3 s | Read the Mirror's one-sentence read of them |

The compute floor underneath this envelope is **150 ms per beat** and the
shipped loop clears it by ~3 000× ([`docs/latency_report_m1.md`](./latency_report_m1.md)).
Compute is invisible. The 30 s is the only number the player feels.

## 2. Tone signature (per beat)

Every beat must hit, in order: **clean → polite → clinical → faintly off**.
Bureaucratic warmth that does not quite cover the measurement underneath
([`game_design.md`](./game_design.md) §3.3). If a beat reads as theatrical,
angry, or whimsical, it is wrong for M1 and must be re-flavored, not patched
with a Reflection.

## 3. What each beat must deliver

- **One legible axis of choice.** Each of the 3 choices is tagged with exactly
  one tendency (caution / aggression in M1; kindness / control / defiance in the
  shipped slice). A reader who skims must still be able to tell which "you" each
  option asks for ([`docs/ADAPTATION.md`](./ADAPTATION.md) §1).
- **State that moved.** The PlayerState tally changed by exactly one. The player
  does not see the number, but the next beat *uses* it (re-ordering, framing).
- **No new rules.** A beat never teaches a mechanic. The mechanic is the beat.
- **No real-world reach.** Prompts, choices, and Reflections cite only in-game
  acts ([`docs/GUARDRAILS.md`](./GUARDRAILS.md); [`README.md`](../README.md)
  "Safety and Fiction Boundary"). Creepiness comes from accuracy about play, not
  from reaching outside it.

## 4. The Reflection beat — feel

The single forced Reflection at Recalibration ([founder
brief](./mirror_loop_m1_founder_brief.md) "Locked") is the only moment the
system says *"I see you."* It must read as **observation, not accusation**: one
sentence of claim (`tendency in count of total`), one sentence of in-fiction
evidence quoted verbatim from the choices the player just made. It announces
each pattern **once**; nagging breaks the spell ([`docs/CORE_LOOP.md`](./CORE_LOOP.md) §3).

## 5. Feel-breakers (rejected for M1)

- A beat longer than ~45 s of reading (prose creep).
- A choice whose tendency a careful reader cannot name.
- A Reflection that paraphrases instead of quoting `evidence`.
- A Reflection that fires twice for the same pattern.
- Any adaptation that *adds* or *removes* a door — re-ordering and reframing
  only ([`docs/ADAPTATION.md`](./ADAPTATION.md) §4).
- Tone drift into theatrical, angry, or whimsical.

---

When this doc and [`docs/CORE_LOOP.md`](./CORE_LOOP.md) disagree, CORE_LOOP wins
on structure and this doc wins on feel. ADR-0001 (M1 locks) cites both.
