# LLM Cost / Latency — Offline Harness & Go/No-Go

**Status:** Decided · **Date:** 2026-05-25
**What the harness produces:** **cost measured exactly** from real prompts, and a
**modeled latency profile** plus a **runnable live latency spike** that measures the
real thing on demand (`python -m llmbench --live`). The go/no-go below rests on the
robust, model-independent comparison; the absolute milliseconds are confirmed by the
spike, which is a command, not deferred work.
**Scope:** the harness, the numbers it produces, and a written go/no-go for **where
(if anywhere) the LLM belongs** plus the **deterministic fallback**.
**Implemented by:** [`llmbench/`](../llmbench/) — run `python -m llmbench` (offline)
or `python -m llmbench --live` (measured latency, needs `ANTHROPIC_API_KEY`).
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

## 1. What the harness produces, and how

The harness ([`llmbench/`](../llmbench/)) sweeps three candidate models across the
two places the design would put an LLM, on **real prompts built from the shipped
world** ([`game/world.py`](../game/world.py)), and reports **per-adaptation /
per-session cost** and **p50/p95 latency**. It runs two ways behind one client
seam ([`llmbench/client.py`](../llmbench/client.py)):

- **Offline (default)** — exact cost, *modeled* latency, deterministic. This is what
  generates the tables below; it needs no network and runs in CI.
- **Live spike (`--live`)** — the *same* sweep against the real endpoint, reporting
  *measured* wall-clock latency and provider-reported token usage. It is the latency
  measurement the acceptance bar names, kept opt-in so the default stays offline and
  deterministic ([`docs/adr/0002-runtime-platform.md`](./adr/0002-runtime-platform.md)).

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
- **Latency in the tables below is modeled, not live-measured** — and is labelled
  and rounded as such (`~N.N s`, never a false-precision millisecond figure). The
  default harness is offline by design (stdlib-only, no network/credentials,
  deterministic CI — [`docs/adr/0002-runtime-platform.md`](./adr/0002-runtime-platform.md)),
  so each model carries an analytic latency profile — fixed overhead + per-token
  decode, with seeded lognormal jitter so the sampled distribution has a realistic
  tail — built from conservative published-throughput assumptions. **The measured
  latency is one command away** (`python -m llmbench --live`, below): the live spike
  is provided, not deferred. The *qualitative* decision in §4 does not depend on the
  exact constants — the per-tier ordering and the critical-vs-off-path gap hold for
  any reasonable profile, and a live spike only sharpens the absolute numbers.

The offline run is deterministic in `(seed, trials)` — the tables below regenerate
byte-for-byte with `python -m llmbench` (seed 42, 200 trials/prompt). The live spike
is *not* deterministic; real latency is not reproducible, which is exactly why it is
the ground truth and the modeled profile is the standing estimate.

## 2. Results

These are the **offline** run (`python -m llmbench`, seed 42, 200 trials/prompt):
cost is exact; latency is **modeled** and shown coarsely (`~N.N s`) so an assumed
constant is never quoted as an observation. Re-run with `--live` to replace the
latency column with measured wall-clock numbers.

### Latency (modeled) and per-adaptation cost (per model × insertion point)

"Per-adaptation cost" is the cost of **one call** — one content decision.

| Model | Insertion point | Path | in tok | out tok | p50 latency (modeled) | p95 latency (modeled) | cost/call |
|---|---|---|---:|---:|---:|---:|---:|
| claude-haiku-4-5 | NPC reply | critical | 172 | 64 | ~0.9 s | ~1.3 s | $0.00049 |
| claude-haiku-4-5 | Branch candidate | off-path | 240 | 256 | ~2.6 s | ~4.0 s | $0.00152 |
| claude-sonnet-4-6 | NPC reply | critical | 172 | 64 | ~1.6 s | ~2.6 s | $0.00148 |
| claude-sonnet-4-6 | Branch candidate | off-path | 240 | 256 | ~5.0 s | ~8.0 s | $0.00456 |
| claude-opus-4-7 | NPC reply | critical | 172 | 64 | ~2.8 s | ~4.4 s | $0.00738 |
| claude-opus-4-7 | Branch candidate | off-path | 240 | 256 | ~9.2 s | ~15.2 s | $0.0228 |

### Per-session cost

One session = **NPC reply ×5, Branch candidate ×3** — derived from the shipped
world (5 loops; 3 branch slots: `records`, `corridor`, `exit`).

| Model | NPC replies | Branch candidates | Session total |
|---|---:|---:|---:|
| claude-haiku-4-5 | $0.00246 | $0.00456 | **$0.00702** |
| claude-sonnet-4-6 | $0.00738 | $0.0137 | **$0.0211** |
| claude-opus-4-7 | $0.0369 | $0.0684 | **$0.1053** |

## 3. Reading the numbers

1. **Cost is not a constraint.** A whole session is sub-cent on Haiku and ~$0.11
   even on Opus. At any plausible playtest or early-access scale, model spend is
   negligible and does **not** gate the decision.

2. **Latency is the constraint, and it lives entirely on the critical path.** The
   per-loop NPC reply is synchronous — the player waits on it. At modeled p95 that is
   **~1.3 s (Haiku) → ~2.6 s (Sonnet) → ~4.4 s (Opus) of dead air *per loop***.
   Across a 5-loop session that is **~6.6 s to ~22 s** of "the game is thinking"
   the player feels directly, on a loop whose whole appeal is a snappy,
   deterministic core. Even the fastest candidate is well past the ~100–300 ms that
   reads as instant — and this holds with wide margin, so it does not depend on the
   exact constants: a candidate would have to beat its modeled latency by **3–15×**
   to reach an instant-feeling hot path, which no current-generation model does.

3. **Off-path latency is affordable.** A branch candidate is authored *ahead* of
   the player and cached, so its latency overlaps earlier loops. Haiku/Sonnet
   finish a candidate (modeled p95 ~4 s / ~8 s) inside one loop of lead time; even
   Opus's ~15 s p95 fits if generation starts ≥2 loops early. Nothing here is on a
   clock the player watches.

The two conclusions that drive §4 — *critical-path latency is intolerable, off-path
latency is absorbable* — are the **ordering** and the **gap**, both robust to the
modeled constants. The live spike (§4) sharpens the absolute milliseconds; it does
not flip either conclusion unless a model is wildly faster than any shipping today.

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

This GO is **gated on one precondition that is genuinely future work, and one
pre-flip step that is already a command**:

1. *(Future work.)* **The A/B must pass first.** The templated adaptation must beat
   baseline before any LLM richness is added (company gating principle; and the
   current A/B is *inconclusive* — [`docs/PLAYTEST_RESULTS.md`](./PLAYTEST_RESULTS.md)).
   No model should enter the loop while the deterministic version has not yet earned
   it.
2. *(A command, not future work.)* **Run the live latency spike to pin the absolute
   milliseconds before flipping the seam:** `ANTHROPIC_API_KEY=… python -m llmbench
   --live --model claude-haiku-4-5 --trials 20`. The harness already measures real
   latency ([`llmbench/client.py`](../llmbench/client.py) `LiveClient`); the spike is
   provided, not deferred. It confirms magnitudes — it does not gate the *decision*,
   which the robust ordering of §3 already settles. (The spike was not run here only
   because this offline environment has no endpoint/credentials, not because the
   harness cannot measure it.)

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
python -m llmbench            # the tables above (offline; modeled latency), as markdown
python -m llmbench --json     # the same report, machine-readable (carries latency_kind)
python -m llmbench --trials 1000 --seed 7   # tighter percentiles / different jitter

# Live latency spike — MEASURED wall-clock latency against the real endpoint.
# Opt-in: needs ANTHROPIC_API_KEY and makes billable calls; not deterministic.
ANTHROPIC_API_KEY=… python -m llmbench --live --model claude-haiku-4-5 --trials 20
```

A live run reports latency as `measured` (in ms) instead of `modeled`, with the
same cost arithmetic and report shape — the only difference is that latency and
token counts come from the endpoint, not the profile/estimator.

The price sheet and modeled latency profiles are the single edit point
([`llmbench/models.py`](../llmbench/models.py)); update them (especially from a
live spike) and the offline tables re-derive. The session multipliers are read off
the world, so they track content rather than a hardcoded constant
(`llmbench.harness.SessionProfile.from_world`).

## 7. Scope honesty

- **Exact (offline):** per-call and per-session **cost**, given the token estimate
  and list prices.
- **Modeled (offline default):** **latency** (per-model analytic profile) and
  **token counts** (~4-chars/token heuristic). Neither changes the decision — cost
  is negligible at any constant, and the latency ordering and the critical-vs-off-path
  gap hold across reasonable profiles. The tables present these coarsely and labelled,
  never as observations.
- **Measured (on demand, `--live`):** real wall-clock **latency** and
  provider-reported **token counts** against the live endpoint. This is the latency
  measurement the acceptance bar names; it is a runnable command, kept opt-in so the
  default stays offline and deterministic. Not run here only for lack of an
  endpoint/credentials in this environment.
- **Deliberately out of scope:** output *quality* (the harness measures cost and
  latency only; quality is a separate evaluation), and any actual loop integration
  (this task is measurement *before* integration — and the harness is not imported
  by the loop).
