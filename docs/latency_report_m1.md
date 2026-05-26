# Templated Beat Loop — Latency Spike (M1)

**Status:** Measured · **Date:** 2026-05-26 · **Scope:** the wall-clock floor of
the M1 templated beat loop, with a written **pre-generate / cache plan** kept on
file in case future work pushes the loop over budget.
**Implemented by:** [`latency/`](../latency/) — run `python -m latency` (markdown)
or `python -m latency --json` (machine-readable).
**Not wired into the runtime:** the harness is opt-in measurement code, same
posture as [`llmbench/`](../llmbench/) and [`telemetry/`](../telemetry/); no game
module imports it.

> This is the founder-brief DoD #8 latency spike
> ([`docs/mirror_loop_m1_founder_brief.md`](./mirror_loop_m1_founder_brief.md):
> *"Latency spike has written one number into … (non-gating)."*). The brief
> calls for a number; the synthesis
> ([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md) "Open
> decisions") accepts the spike into M1 as a one-engineer-day, non-gating
> risk check. This document is that number, the methodology that produced it,
> and — per the acceptance criterion — the pre-generate / cache plan that
> would be enacted if the measured loop missed the 150 ms per-beat budget.

---

## TL;DR

| stat | value (ms) | budget (ms) | clears? |
|---|---:|---:|:--:|
| **median (p50)** | **0.048** | 150 | yes (≈ 3 000× headroom) |
| **p95** | **0.053** | 150 | yes (≈ 2 800× headroom) |

**Verdict.** The templated beat loop clears the 150 ms per-beat budget by ~3 000×
on both the median and the p95. A pre-generate / cache plan is **not needed**
for M1 — but one is written out in §5 below so it sits ready if a later change
ever pushes the loop near the line.

Measured on the maintainer's dev box (one trial = one full Act 1 walk, 14 beats),
200 trials × 14 beats = **2 800 samples**, seed 42:

```text
min        median (p50)   mean        p95         max
0.036 ms   0.048 ms       0.046 ms    0.053 ms    0.380 ms
```

The max outlier (~0.38 ms) is one beat in 2 800 — typical OS-scheduling noise on
a sub-millisecond microbenchmark; still ~400× under budget.

---

## 1. What "the templated beat loop" means here

The **beat** is the work the engine does between the player making one choice
and seeing the next prompt — one iteration of the M1 spine the slice walks
today ([`game/act1.py`](../game/act1.py) `play_act1`). The acceptance criterion
asks for the "templated beat loop's" beat-to-beat time, so the measurement
fence encloses the whole per-beat critical section:

1. **Offer the scene.** `offer_scene` runs the variant's scene selection
   (`game.world.Slot.pick`) and the Mirror's in-scene re-ordering
   (`loop.core.Mirror.adapt`) — the single adaptation seam
   ([`docs/ADAPTATION.md`](./ADAPTATION.md), [`game/variants.py`](../game/variants.py)
   `ADAPTIVE`).
2. **Templated flavor swap (at the M1 beat slot).** At
   `game.flavor.M1_ADAPTATION_BEAT_SLOT`, the M1 brief's one locked adaptation
   runs: `select_directive(mirror_state, seed)` reads the typed
   `MirrorState` axes, picks an `AdaptationDirective`, and
   `M1_BEAT2_FLAVOR_PACK.render(directive)` produces the flavored prompt body
   (`game.flavor`).
3. **Policy.** The seeded policy
   ([`game.act1.seeded_policy`](../game/act1.py)) draws a tendency and picks
   the matching choice.
4. **Record the loop.** `record_loop` runs `Mirror.step` (predict → record →
   reflect) and the system-voice template render (`game.templates.adapt_message`).
5. **MirrorState update.** `mirror.state.MirrorState.apply_choice` advances
   the typed M1 player-model axes (so the next beat's `select_directive` sees
   real, non-neutral state); `MirrorState.tick` runs the per-turn STATE-axis
   relaxation step.

Everything here is **templated and deterministic**: no LLM, no network, no I/O
on the hot path. Scene files load once, before timing begins
([`latency/harness.py`](../latency/harness.py) — `measure_beat_latency`).

This deliberately measures one beat of the **shipped** M1 walk, not a synthetic
microbenchmark. The number is the floor a future LLM integration would have to
live inside — and cross-references the critical-path NO-GO in
[`docs/LLM_COST_LATENCY.md`](./LLM_COST_LATENCY.md) §4, which uses the
synchronous decode-only floor (640 tok/s for an "instant" budget) to settle
the LLM-on-the-hot-path question on first principles.

---

## 2. Methodology

The harness ([`latency/harness.py`](../latency/harness.py)
`measure_beat_latency`) mirrors `play_act1`'s body and brackets each iteration
with `time.perf_counter_ns` — the monotonic, process-local clock, so the
samples are not affected by NTP/wall-clock skew.

- **One sample = one beat.** Bracketing the full per-beat critical section
  (steps 1–5 above) rather than the loop body as a whole — so the latency is
  attributable to one beat, not amortised across a run.
- **Scene I/O outside the fence.** `load_act1_world()` runs once before timing
  starts; a real session loads scenes at boot, not per beat. Counting disk
  reads inside the per-beat number would over-report a cost the engine does
  not actually pay every beat.
- **No artificial work.** The policy is `seeded_policy(42)`, identical to the
  M1 byte-identity gate ([`game.replay.DEFAULT_SEED`](../game/replay.py)). The
  `MirrorState` is advanced per beat with a representative per-tendency signal
  so `select_directive` is doing real work on real state, not on a blank
  `MirrorState.new()`.
- **Deterministic work, jittered latency.** The same `(seed, trials)` produces
  the same input log byte-for-byte — only the wall-clock-jitter component
  varies. That is the property the percentile is measuring.
- **Nearest-rank percentile.** `p95` is the 95th sample in rank order with
  `ceil(n * q)` (same shape as [`llmbench/metrics.py`](../llmbench/metrics.py))
  — a reported number is always one of the samples we actually observed.

Default run: **50 trials × 14 beats = 700 samples** (cheap enough for CI;
percentiles already stable). The TL;DR's numbers come from a longer
**200 trials × 14 beats = 2 800 samples** run; the table is reproducible to
within wall-clock jitter with `python -m latency --trials 200 --seed 42`.

---

## 3. Result

```
n        = 2800            (200 trials × 14 beats, seed 42)
min      = 0.036 ms
median   = 0.048 ms   ← p50
mean     = 0.046 ms
p95      = 0.053 ms
max      = 0.380 ms
budget   = 150 ms      (median + p95 must both clear)
verdict  = within budget by ~3 000×
```

The whole distribution is sub-millisecond. Even the max — a single OS-scheduling
glitch out of 2 800 samples — is ~400× under budget. The templated path is
"effectively free" at the per-beat scale: a player on this loop is bottlenecked
by their own reaction time, not by the engine.

This is consistent with what the path *should* cost on first principles. Per
beat, it does: one dict lookup + comparison (variant.select_scene),
~3 `tendency_counts` reads and a `sorted(3-element-list)` (`Mirror.adapt` /
`record_loop`), ~6 short string formats (`adapt_message`), a ~30-attribute
deepcopy of `MirrorState.readings`, and (once per session) a constant-time
`select_directive` scan over the typed axes. The expected ballpark is
"microseconds, not milliseconds" and that is what was measured.

---

## 4. Why this number is honest

A latency spike is only useful if the thing it timed is the thing the player
will see. Three properties make this one honest:

1. **It measures the shipped walk, not a stub.** The harness uses
   `game.act1.load_act1_world`, `seeded_policy`, `offer_scene`, `record_loop`,
   `MirrorState`, and the real `M1_BEAT2_FLAVOR_PACK`. Replacing any of those
   with a mock would have measured something other than the M1 beat loop.
2. **The fence is the whole critical section.** The naive way to instrument
   this — `on_loop` callback on `play_act1` — fires *between* beats and
   silently elides the next beat's `offer_scene` cost. The harness inlines
   the loop body so the fence brackets all five steps from §1.
3. **Templated only.** No network, no LLM, no clock-bound work other than the
   measurement fence itself — so the number is a clean read of the templated
   floor, not a noisy read of templated + LLM + network. That is the floor a
   future LLM integration would have to clear, and the basis on which the
   cross-doc NO-GO in [`docs/LLM_COST_LATENCY.md`](./LLM_COST_LATENCY.md) §4
   stands.

---

## 5. Pre-generate / cache plan (kept on file)

The plan below would be enacted **if** the templated beat loop ever missed the
150 ms budget — i.e. if a future change pushed median or p95 over the line.
Today's number is ~3 000× inside budget so none of this is needed; it is
written down here so the response is pre-decided and prioritised rather than
improvised under pressure.

The plan, in priority order:

1. **Pre-generate the per-beat content at session start.** Each beat's
   `(directive → prompt body)` mapping is fully authored offline (see
   `game.flavor.M1_BEAT2_FLAVOR_PACK`). Render the full mapping for every
   slot × directive into an in-memory table once during `play_act1` boot, then
   look it up at beat time. This converts the templated render from a per-beat
   cost into a one-shot startup cost — off the player's clock by definition.
   Storage cost is trivial (≤ 14 slots × ≤ 4 directives × ≤ 2 KB ≈ tens of KB).

2. **Cache the offer.** `offer_scene`'s output is a pure function of
   `(variant, slot, state)`, and `state` only changes at choice time. Memoise
   per `(slot.key, tendency_tally_signature)`; a second hit on the same offer
   is a dict lookup. Eviction is bounded by the number of distinct tendency
   tallies reachable in one session — small (≤ a few dozen).

3. **Hoist the system-voice template render out of the hot path.**
   `game.templates.adapt_message` is template substitution over a small set of
   shape-discriminating booleans (`just_noticed`, `model_locked`,
   `predicted_hit`, `is_finale`) plus a dominant tendency. Precompute the
   message shells for each input tuple at module load and only fill the
   counts / totals at beat time.

4. **Last-resort: degrade the adaptation seam to the identity transform.** If
   (1)–(3) are not enough, drop the seam to `game.variants.FIXED` (the
   canonical control — neutral framing, declared choice order) until the
   templated path clears the budget on its own. The structural
   `baseline ≡ adaptive` parity gate
   ([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md) "Gates"
   §) guarantees the engine is byte-identical without the seam, so this is a
   safe fallback rather than a content change.

Order of operations if the budget is ever breached: re-run `python -m latency`
after each step and **stop at the first one that brings p95 inside budget**.
Anything further is over-engineering against a problem the measurement no
longer shows.

---

## 6. Reproducing

```bash
python -m latency                         # default: 50 trials × 14 beats, seed 42
python -m latency --json                  # same report, machine-readable
python -m latency --trials 200 --seed 42  # the TL;DR's 2 800-sample run
python -m latency --budget-ms 50          # tighter budget (e.g. for a regression gate)
```

The harness uses no network and no credentials. Its only inputs are
`(trials, seed, budget_ms)`; its only output is the per-beat distribution and
the verdict. Re-runs will not be byte-identical — wall-clock latency is
inherently jittered — but the percentiles are stable to within a few µs at
`--trials 200` and above.

---

## 7. Scope honesty

- **Measured (not modeled):** real wall-clock latency on the maintainer's
  machine, via `time.perf_counter_ns`, against the shipped Act 1 walk.
- **Single machine:** the numbers will vary across hardware. The acceptance
  criterion is order-of-magnitude (150 ms), not micro-tuning, and the headline
  result clears that bar by orders of magnitude on every machine the
  templated path has been exercised on. The harness re-runs locally in any
  CI environment with the same defaults.
- **Per-beat, not per-session:** the per-session cost is `~50 µs × 14 ≈ 0.7 ms`
  for a whole Act 1 walk on this machine — well inside any "felt instant"
  budget for a whole session, let alone one beat.
- **Out of scope (and intentionally so):** LLM cost / latency — that has its
  own harness and a separate decision document
  ([`docs/LLM_COST_LATENCY.md`](./LLM_COST_LATENCY.md)). This document is the
  templated floor; that document is the LLM ceiling. The two together pin
  both ends of the integration question.
