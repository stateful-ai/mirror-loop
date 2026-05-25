# LLM Cost / Latency — Offline Harness & Go/No-Go

**Status:** Decided (measurement complete; go/no-go below) · **Date:** 2026-05-25
**Scope:** the offline harness that measures candidate-model cost and latency on
real prompts, the numbers it produced, and a written go/no-go for **where (if
anywhere) the LLM belongs** plus the **deterministic fallback**.
**Implemented by:** [`llmbench/`](../llmbench/) — run `python -m llmbench`.
**Not wired into the loop:** enforced by
[`llmbench/tests/test_not_wired_into_loop.py`](../llmbench/tests/test_not_wired_into_loop.py).

> This is the "answer the LLM cost/latency question offline" deliverable the M1
> plan deferred ([`docs/mirror_loop_m1_synthesis.md`](./mirror_loop_m1_synthesis.md):
> *"LLM stays out of the loop for M1; offline harness handles cost/latency later"*;
> founder brief DoD #8 "latency spike … output is a number"). It is the
> non-gating, pre-integration measurement required by the company principle
> *"v0 adaptation stays templated/deterministic; any LLM is measured in an offline
> cost/latency harness before it enters the loop."*

---

## 1. What was measured, and how

The harness ([`llmbench/`](../llmbench/)) sweeps three candidate models across the
two places the design would put an LLM, on **real prompts built from the shipped
world** ([`game/world.py`](../game/world.py)), and reports the figures the
acceptance bar names: **p50/p95 latency** and **per-adaptation / per-session
cost**.

**Real prompts, not filler.** [`llmbench/prompts.py`](../llmbench/prompts.py) walks
three consistent personas (kindness / control / defiance) through `DEFAULT_WORLD`
using the *shipped* branch-selection logic (`game.world.Slot.pick`), and at each
loop builds the prompt an LLM would actually receive — embedding the authored
scene prose, the real choice text and evidence phrases, and the real player-model
tally. The prompts also carry the design's safety contract in their instructions
(reflect in-game behavior only; never remove a door; never rewrite the engine —
[`docs/ADAPTATION.md`](./ADAPTATION.md) §4, [`docs/GUARDRAILS.md`](./GUARDRAILS.md)),
because a realistic prompt is one already constrained the way the loop would
constrain it.

**Two insertion points**, chosen to bracket the two latency regimes:

| Insertion point | What the LLM would do | Path | Output budget |
|---|---|---|---|
| **NPC reply** | the Mirror's in-character line reacting to the latest choice | **critical** — player waits every loop | ~64 tok |
| **Branch candidate** | author the next scene's tailored framing ahead of the player (generative analogue of v0's `BRANCH_SELECTION`) | **off-path** — precomputable, cacheable | ~256 tok |

**Candidate models** ([`llmbench/models.py`](../llmbench/models.py)): a fast tier
(`claude-haiku-4-5`), a balanced tier (`claude-sonnet-4-6`), and a frontier tier
(`claude-opus-4-7`).

**What is exact vs. modeled — read this before quoting numbers.**

- **Cost is exact.** It is `input_tokens × in_price + output_tokens × out_price`.
  Token counts come from the real prompt text via a documented estimator
  ([`llmbench/tokens.py`](../llmbench/tokens.py), ~4 chars/token; ±~15-20% vs. a
  real tokenizer); prices are public **list prices as of 2026-05**. So the dollars
  are sound to within the token estimate, which a live run's reported `usage` would
  pin exactly.
- **Latency is modeled, not live-measured.** With no network/credentials (the
  prototype is deliberately offline and dependency-free,
  [`docs/adr/0002-runtime-platform.md`](./adr/0002-runtime-platform.md)), each
  model carries an analytic latency profile — fixed overhead + per-token decode,
  with seeded lognormal jitter so the sampled distribution has a realistic tail.
  These are conservative published-throughput assumptions. **They are the one input
  a short live latency spike should confirm before integration.** The *qualitative*
  decision below does not depend on the exact constants (the per-tier ordering and
  the critical-vs-off-path gap are robust); the absolute milliseconds do.

Everything is deterministic in `(seed, trials)` — the tables below regenerate
byte-for-byte with `python -m llmbench` (seed 42, 200 trials/prompt).

## 2. Results

### Latency and per-adaptation cost (per model × insertion point)

"Per-adaptation cost" is the cost of **one call** — one content decision.

| Model | Insertion point | Path | in tok | out tok | p50 latency | p95 latency | cost/call |
|---|---|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5  | NPC reply        | critical | 172 | 64  | 885 ms   | 1 329 ms  | $0.00049 |
| claude-haiku-4-5  | Branch candidate | off-path | 240 | 256 | 2 617 ms | 3 963 ms  | $0.00152 |
| claude-sonnet-4-6 | NPC reply        | critical | 172 | 64  | 1 618 ms | 2 553 ms  | $0.00148 |
| claude-sonnet-4-6 | Branch candidate | off-path | 240 | 256 | 5 014 ms | 7 980 ms  | $0.00456 |
| claude-opus-4-7   | NPC reply        | critical | 172 | 64  | 2 771 ms | 4 422 ms  | $0.00738 |
| claude-opus-4-7   | Branch candidate | off-path | 240 | 256 | 9 168 ms | 15 193 ms | $0.02278 |

### Per-session cost

One session = **NPC reply ×5, Branch candidate ×3** — derived from the shipped
world (5 loops; 3 branch slots: `records`, `corridor`, `exit`).

| Model | NPC replies (×5) | Branch candidates (×3) | **Session total** |
|---|---:|---:|---:|
| claude-haiku-4-5  | $0.00246 | $0.00456 | **$0.0070** |
| claude-sonnet-4-6 | $0.00738 | $0.01367 | **$0.0211** |
| claude-opus-4-7   | $0.03690 | $0.06835 | **$0.1053** |

## 3. Reading the numbers

1. **Cost is not a constraint.** A whole session is sub-cent on Haiku and ~$0.11
   even on Opus. At any plausible playtest or early-access scale, model spend is
   negligible and does **not** gate the decision.

2. **Latency is the constraint, and it lives entirely on the critical path.** The
   per-loop NPC reply is synchronous — the player waits on it. At p95 that is
   **1.3 s (Haiku) → 2.6 s (Sonnet) → 4.4 s (Opus) of dead air *per loop***.
   Across a 5-loop session that is **~6.6 s to ~22 s** of "the game is thinking"
   the player feels directly, on a loop whose whole appeal is a snappy,
   deterministic core. Even the fastest candidate is well past the ~100–300 ms that
   reads as instant.

3. **Off-path latency is affordable.** A branch candidate is authored *ahead* of
   the player and cached, so its latency overlaps earlier loops. Haiku/Sonnet
   finish a candidate (p95 ~4 s / ~8 s) inside one loop of lead time; even Opus's
   ~15 s p95 fits if generation starts ≥2 loops early. Nothing here is on a clock
   the player watches.

## 4. Go / No-Go decision

**NO-GO on the critical path.** Do **not** place any synchronous LLM call in the
per-loop hot path (an NPC line rendered while the player waits). No candidate
clears a tolerable hot-path latency budget, cost notwithstanding. The hot path
stays the deterministic templated layer.

**Conditional GO off the critical path**, for **ahead-of-player branch authoring**
— the generative analogue of v0's `BRANCH_SELECTION` — under these conditions:

- It runs **behind the content-adapter contract**, as an interchangeable content
  *supplier* (templated vs. LLM are two implementations of one seam; cost arm off
  until a model is actually in the loop — the cross-project content-adapter
  principle).
- It is **precomputed and cached** during earlier loops, never blocking the turn
  the player is on.
- Every candidate is **validated by guardrails** ([`guardrails/`](../guardrails/);
  reorder-only / agency-preserving / in-game-only) and **promoted only on pass**.
- The **deterministic templated selection is the fallback** whenever a candidate is
  late, missing, or fails validation (see §5).
- **Recommended tier:** Haiku or Sonnet for off-path authoring (latency headroom +
  quality); reserve Opus for generations with ≥2 loops of lead time.

This GO is **gated on two preconditions**, neither yet met:

1. **The A/B must pass first.** The templated adaptation must beat baseline before
   any LLM richness is added (company gating principle; and the current A/B is
   *inconclusive* — [`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md)). No model
   should enter the loop while the deterministic version has not yet earned it.
2. **A live latency spike must confirm the modeled numbers** (§1). The dollars are
   sound; the milliseconds are assumptions until measured against a real endpoint.

**Where the LLM belongs, in one line:** off the critical path, as a cached,
guardrail-validated *supplier* of branch framings (and, later, NPC lines
precomputed for the predicted choice), never as a step the player waits on.

## 5. The deterministic fallback

The fallback is not new code — it is the **shipped production path**: tendency
mirroring by templated selection and ordering
([`game/world.py`](../game/world.py) `Slot.pick`; [`loop/core.py`](../loop/core.py)
`Mirror.adapt`; producer [`game/adapt.py`](../game/adapt.py)). It is instantaneous,
deterministic, byte-identical under replay, and already the thing the A/B scores.

The integration posture this implies: the LLM sits **beside** the templated layer,
not in front of it. The loop always has the templated answer in hand at zero added
latency; a generated candidate is used **only** if it arrived in time and passed
validation, otherwise the templated selection is presented unchanged. The player
never blocks on a model, and a generation failure degrades to exactly today's
behavior rather than to a stall.

## 6. Reproducing & maintaining

```
python -m llmbench            # the tables above, as markdown
python -m llmbench --json     # the same report, machine-readable
python -m llmbench --trials 1000 --seed 7   # tighter percentiles / different jitter
```

The price sheet and latency profiles are the single edit point
([`llmbench/models.py`](../llmbench/models.py)); update them (especially from a
live spike) and the tables re-derive. The session multipliers are read off the
world, so they track content rather than a hardcoded constant
(`llmbench.harness.SessionProfile.from_world`).

## 7. Scope honesty

- **Exact:** per-call and per-session **cost**, given the token estimate and list
  prices.
- **Modeled:** **latency** (per-model analytic profile) and **token counts**
  (~4-chars/token heuristic). Neither changes the decision — cost is negligible at
  any constant, and the latency ordering and the critical-vs-off-path gap hold
  across reasonable profiles — but both should be pinned by a **live latency
  spike** before code is wired in.
- **Deliberately out of scope:** output *quality* (the harness measures cost and
  latency only; quality is a separate evaluation), and any actual loop integration
  (this task is measurement *before* integration — and the harness is not imported
  by the loop).
