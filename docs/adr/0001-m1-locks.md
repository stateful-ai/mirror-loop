# ADR-0001 — M1 locks: Beat-2 placement · single-forced Recalibration cadence · latency-spike scope

**Status:** Accepted · **Date:** 2026-05-26
**Scope:** the three M1 locks that fix *where* adaptation fires, *when* the
Reflection beat plays, and *what* the latency spike is allowed to cost — i.e.
the locks that, together with the runtime/platform decision in
[ADR-0002](./0002-runtime-platform.md), make the Beats-Baseline Prediction
Test runnable. Each lock is recorded below as **Decision · Alternative ·
Reopen trigger** so a later contributor can tell, without re-deriving the
argument, what would force this ADR to be superseded.
**Grounded in:** the locked thesis ([`../THESIS.md`](../THESIS.md) §1–2);
the locked M1 brief ([`../mirror_loop_m1_founder_brief.md`](../mirror_loop_m1_founder_brief.md)
"Locked" + "Definition of Done" + "Risks").
**Normative inputs (a change to any of these is a change to this ADR):**
[`../core_loop_feel.md`](../core_loop_feel.md) (the 30s-beat feel-spec),
[`../CORE_LOOP.md`](../CORE_LOOP.md) (the structural slice),
[`../ADAPTATION.md`](../ADAPTATION.md) (the single adaptation type),
[`../latency_report_m1.md`](../latency_report_m1.md) (the measured floor and
the on-file pre-generate / cache plan),
[`../GUARDRAILS.md`](../GUARDRAILS.md) (the safety boundary).

---

## Context

The M1 slice exists to run the **Beats-Baseline Prediction Test**
([THESIS §2](../THESIS.md)) — a blind A/B whose two CI gates are
**byte-identity replay under seed 42** and **structural baseline≡adaptive
parity**. Both gates are only meaningful if three things are fixed up front:

- **Where** the one adaptive swap happens (so the parity test knows where to
  look and replay knows what bytes must match).
- **When** the Reflection beat plays (so the legibility moment is a single
  observable event, not a cadence).
- **What budget** the templated path commits to — and what the project will
  do if a measurement ever breaches it.

Without those locked, every churn in the content layer reopens the gate
question and every churn in the engine reopens the latency question. Three
converging M1 plans ([founder brief](../mirror_loop_m1_founder_brief.md)
"Convergence") landed on the same three answers; the founder brief's
"Locked" section recorded them in passing, and the "Risks" section called
out latency-spike scope-creep specifically. This ADR is the canonical record,
in the form a later contributor can use to know when to come back.

The Mirror axis itself (`caution ↔ aggression`) is upstream context for these
locks — it is what the Beat-2 swap reads to choose a directive
([ADAPTATION §1](../ADAPTATION.md)) — but it is a property of the M1 player
model rather than a decision this ADR re-litigates. Locks below presume it.

## Decisions

Each lock is stated as a single sentence, then expanded as **Alternative
considered** (what was on the table that we rejected) and **Reopen trigger**
(the concrete observation that would force this ADR to be superseded by a
new one). A change that breaks any reopen trigger is a new ADR, not an edit.

### 1. Beat-2 placement

#### Decision

The one templated flavor swap fires at **Act 1 Beat 2** and nowhere else.
It re-orders and reframes the authored options at that beat; it never
adds, removes, or rewrites a door
([ADAPTATION §1](../ADAPTATION.md);
[`../core_loop_feel.md`](../core_loop_feel.md) §5;
[`game.flavor.M1_ADAPTATION_BEAT_SLOT`](../../game/flavor.py)).

**Why this beat.** Beat 2 is the earliest point at which the Mirror has
observed enough player choice to read a tendency that is more signal than
noise, and the latest point at which the Reflection at Recalibration can
still credibly cite the swap as the thing it "noticed." Any earlier and the
swap fires on a near-empty tally; any later and Reflection loses its
in-fiction evidence.

#### Alternative considered — adaptation at every beat (cadence-adaptation)

Rejected: smears the signal. When a session fails the prediction gate, the
diagnosis must be attributable to a specific swap; a swap-per-beat regime
turns every failure into a multi-suspect investigation and bloats the
parity-test combinatorics for no gate-relevant benefit. The founder brief's
"Risks" list also called out that Beat-2 placement could be narratively flat
([brief "Risks"](../mirror_loop_m1_founder_brief.md)); the mitigation is
loud flavor *at* Beat 2, not more swap sites.

#### Reopen trigger

A measured playtest result in which the Beat-2 swap is demonstrably
illegible at Reflection (Reflection cannot cite the swap in its in-fiction
evidence quote in ≥ 50% of sessions in a sample of ≥ 50), or a thesis
revision that requires multi-site adaptation to test. Either forces a new
ADR; neither is editable into this one.

### 2. Single-forced Recalibration cadence

#### Decision

Reflection fires **once per session, forced, at Recalibration**. The "I see
you" moment reads as observation, not accusation: one claim sentence, one
in-fiction evidence quote
([`../core_loop_feel.md`](../core_loop_feel.md) §4;
[CORE_LOOP §3](../CORE_LOOP.md)). No additional Reflection fires on any
other beat in M1.

**Why one, forced, at Recalibration.** Recalibration is the structural
beat at which the Mirror's read of the player has the most evidence to draw
on and the smallest remaining risk of being contradicted by later choices.
Forcing it (rather than gating it on a confidence threshold) makes the
legibility moment a guaranteed observable for the prediction gate — every
session in both arms produces exactly one Reflection event in the same
structural slot, so the parity test is straightforward.

#### Alternative considered — Reflection on a cadence (every N beats, or confidence-gated)

Rejected: cadence-Reflection is the failure mode
[`core_loop_feel.md`](../core_loop_feel.md) §5 names ("a Reflection that
fires twice for the same pattern"). Nagging breaks legibility
([CORE_LOOP §3](../CORE_LOOP.md)); a confidence gate makes the event
optional and so unobservable as a parity feature. One forced beat is the
minimum that makes the legibility moment real without becoming nag.

#### Reopen trigger

Either (a) a playtest in which the single Reflection lands reliably as
"observation" *and* a v1 question genuinely requires a second Reflection
moment to answer (i.e. M1 is closed and M2 has begun); or (b) a playtest in
which the forced Reflection lands as "accusation" in ≥ 30% of sessions, in
which case the response is *not* to add more Reflections but to revise the
render — and that revision lives in a superseding ADR because it would
change what this lock means.

### 3. Latency-spike scope

#### Decision

The latency spike is **in-scope for M1, time-boxed to one engineer-day,
non-gating; output is a single number** (median + p95 per beat against a
150 ms budget) and a **written pre-generate / cache plan kept on file** for
the case where a future change pushes the loop over budget
([founder brief "Locked" + DoD #8 + "Risks"](../mirror_loop_m1_founder_brief.md);
implemented in [`../latency_report_m1.md`](../latency_report_m1.md) §3, §5;
harness in [`latency/`](../../latency/)).

**Why a number, not a benchmark suite, not a CI gate.** The spike's job is
to settle a risk, not to grow a regime. The risk is "we ship a templated
loop and discover at integration time that it can't hit a felt-instant
budget"; settling that needs one credible measurement against the shipped
walk. Making it a CI gate would turn a one-time risk-check into a permanent
flake source (wall-clock latency is jittered and machine-dependent); making
it a benchmark suite would re-create the scope-creep the founder brief
"Risks" entry explicitly mitigated against ("time-box one day; output is a
number"). The fallback — *if* the budget is ever breached — is the
pre-generate / cache plan already written in
[`../latency_report_m1.md`](../latency_report_m1.md) §5, so the response is
pre-decided rather than improvised.

#### Alternative considered — wire latency as a third branch-protected CI gate

(alongside byte-identity replay and baseline parity). Rejected: wall-clock
latency is inherently non-deterministic and machine-dependent; a
percentile-based gate would either be loose enough to pass on noise or
tight enough to flake on noise, with no setting that is honestly both.
Replay byte-identity already covers the *deterministic* part of "the loop
behaves the same way every time"; latency is the *jittered* part and is
better answered by a measured floor and a pre-decided response than by a
gate that can lie in either direction.

#### Reopen trigger

Any of: (a) a re-run of `python -m latency` in which p95 exceeds 150 ms on
a maintainer-class machine (forces the pre-generate / cache plan in
[`../latency_report_m1.md`](../latency_report_m1.md) §5 to be enacted, in
priority order, and the result re-recorded); (b) an LLM or other
non-templated path entering the per-beat critical section (changes the
floor that this spike measured, so the number is no longer the right
number — cross-references the NO-GO in
[`../LLM_COST_LATENCY.md`](../LLM_COST_LATENCY.md) §4); (c) a target
platform whose templated floor is materially worse than the maintainer's
dev box (forces a re-measurement on that platform before M1 ships there).

## Consequences

- The reducer, adaptation seam, reflection renderer, and latency harness
  ([founder brief module layout](../mirror_loop_m1_founder_brief.md))
  collapse around a single swap site, a single Reflection render, and a
  single measured floor — keeping the simulation core pure
  ([ADR-0002 "Reversibility"](./0002-runtime-platform.md)) and the
  measurement harness off the hot path
  ([`../latency_report_m1.md`](../latency_report_m1.md) "Not wired into the
  runtime").
- The baseline arm is the adaptive arm with the Beat-2 seam in identity
  mode; the parity test asserts that and nothing more.
- The latency number is not load-bearing for the CI gates — the gates are
  byte-identity replay and structural parity — but a regression in the
  number is a reopen trigger for §3 above, in writing, with the response
  pre-decided.
- The feel-spec ([`../core_loop_feel.md`](../core_loop_feel.md)) is the
  authoritative source for what each beat must *feel like* under these
  locks. If a beat hits the structure but fails the feel, the bug is in
  the content, not in this ADR.
- Post-M1 expansion of the adaptation surface, the Reflection cadence, and
  the latency regime ([`../game_design.md`](../game_design.md) §6;
  [ADAPTATION §4](../ADAPTATION.md)) is expected and will arrive as
  ADR-0003+, each citing the specific reopen trigger above that fired.
