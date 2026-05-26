# ADR-0001 — M1 locks: mirror axis · Beat-2 adaptation · single-beat Reflection

**Status:** Accepted · **Date:** 2026-05-26
**Scope:** the three gameplay decisions that fix the shape of the M1 slice — the
*one axis* the Mirror reads, the *one place* adaptation fires, and the *one
moment* the Reflection beat plays. These predate this directory (they were
locked in the [`mirror_loop_m1_founder_brief.md`](../mirror_loop_m1_founder_brief.md)
"Locked" section); this ADR records them in the canonical location so the
*why* survives the diff.
**Grounded in:** the locked thesis ([`../THESIS.md`](../THESIS.md) §1–2);
the locked M1 brief ([`../mirror_loop_m1_founder_brief.md`](../mirror_loop_m1_founder_brief.md)
"Locked" + "Definition of Done").
**Normative inputs (a change to any of these is a change to this ADR):**
[`../core_loop_feel.md`](../core_loop_feel.md) (the 30s-beat feel-spec),
[`../CORE_LOOP.md`](../CORE_LOOP.md) (the structural slice),
[`../ADAPTATION.md`](../ADAPTATION.md) (the single adaptation type),
[`../GUARDRAILS.md`](../GUARDRAILS.md) (the safety boundary).

---

## Context

The M1 slice exists to run the **Beats-Baseline Prediction Test**
([THESIS §2](../THESIS.md)) — a blind A/B whose two CI gates are
**byte-identity replay under seed 42** and **structural baseline≡adaptive
parity**. Both gates are only meaningful if the *shape* of the adaptive arm is
fixed: which axis is read, where the swap fires, and when the Reflection beat
plays. Without those locked, every churn in the content layer reopens the gate
question.

Three converging M1 plans ([founder brief](../mirror_loop_m1_founder_brief.md)
"Convergence") landed on the same three locks. This ADR is the canonical record.

## Decision

**For M1, the gameplay shape is fixed on three axes:**

1. **One mirror axis — caution ↔ aggression.** The PlayerState is a single
   tendency tally on this axis ([CORE_LOOP §1](../CORE_LOOP.md);
   [ADAPTATION §1](../ADAPTATION.md)). The richer shipped tendencies (kindness /
   control / defiance) and the ~15-feature player model
   ([`../game_design.md`](../game_design.md) §6) are *later* layers that sit on
   top without changing M1's shape.
2. **One adaptation, at Act 1 Beat 2 — a templated flavor swap.** Adaptation is
   tendency mirroring ([ADAPTATION §1](../ADAPTATION.md)) realized as exactly
   one templated flavor swap at Act 1 Beat 2. It re-orders and reframes the
   authored options; it never adds, removes, or rewrites a door
   ([`../core_loop_feel.md`](../core_loop_feel.md) §5).
3. **One Reflection — a single forced beat at Recalibration.** The "I see you"
   moment fires *once* per session, at Recalibration, and reads as observation,
   not accusation: one claim sentence, one in-fiction evidence quote
   ([`../core_loop_feel.md`](../core_loop_feel.md) §4;
   [CORE_LOOP §3](../CORE_LOOP.md)).

The 30-second player envelope, tone signature, and explicit feel-breakers that
each beat must hit live in [`../core_loop_feel.md`](../core_loop_feel.md) and
are normative for this ADR: a change to the feel-spec is a change to what these
locks deliver.

## Rationale

1. **Gate-relevance.** Byte-identity replay and baseline-parity both presume a
   *single* adaptation seam in a *known* place. Multiple swaps, multiple
   Reflections, or a sliding axis would each force the parity test to grow
   special cases — and the gate stops meaning what it says.
2. **Smallest slice that can answer the thesis.** One axis, one swap, and one
   Reflection are the minimum surface on which the Beats-Baseline Prediction
   Test produces a verdict. Anything richer is post-M1 expansion and is held out
   on purpose ([ADAPTATION §4 "explicitly held out"](../ADAPTATION.md)).
3. **Reflection-once preserves the spell.** Nagging breaks legibility
   ([CORE_LOOP §3](../CORE_LOOP.md);
   [`../core_loop_feel.md`](../core_loop_feel.md) §5). One forced beat at
   Recalibration is the load-bearing legibility moment; further Reflections are
   a v1 question, not an M1 one.
4. **Templated, not generated.** M1 has no LLM in the loop
   ([ADR-0002](./0002-runtime-platform.md); [LLM_COST_LATENCY](../LLM_COST_LATENCY.md)).
   The Beat-2 swap is a deterministic content selection over a flavor pack so
   that replay stays byte-identical and the latency floor stays at the measured
   ~150 ms ([`../latency_report_m1.md`](../latency_report_m1.md)).

## Alternatives considered

- **Two-axis mirror (e.g., caution↔aggression *and* kindness↔control) for M1.**
  Rejected: doubles the adaptation surface and the parity-test combinatorics for
  no gate-relevant benefit. Multi-axis lives in the shipped slice
  ([`../game_design.md`](../game_design.md) §6); M1 is the *one-axis* proof.
- **Adaptation at every beat.** Rejected: smears the signal — when a session
  fails the prediction gate it must be diagnosable to a specific swap. A single
  swap at a known beat keeps the gate legible.
- **Reflection on a cadence (every N beats).** Rejected: cadence-Reflection is
  the failure mode `core_loop_feel.md` §5 names ("a Reflection that fires twice
  for the same pattern"). One forced beat at Recalibration is the minimum that
  makes the legibility moment real without becoming nag.

## Consequences

- The reducer, adaptation seam, and reflection renderer
  ([founder brief module layout](../mirror_loop_m1_founder_brief.md))
  collapse around a single axis, a single seam, and a single render — keeping
  the simulation core pure ([ADR-0002 "Reversibility"](./0002-runtime-platform.md)).
- The baseline arm is the adaptive arm with the seam in identity mode; the
  parity test asserts that and nothing more.
- A change that breaks any of the three locks (a second axis, a second
  adaptation site, a second Reflection) supersedes this ADR rather than editing
  it. Post-M1 expansion of the player model and adaptation surface
  ([`../game_design.md`](../game_design.md) §6;
  [ADAPTATION §4](../ADAPTATION.md)) is expected and will arrive as ADR-0003+.
- The feel-spec ([`../core_loop_feel.md`](../core_loop_feel.md)) is the
  authoritative source for what each beat must *feel like* under these locks.
  If a beat hits the structure but fails the feel, the bug is in the content,
  not in this ADR.
