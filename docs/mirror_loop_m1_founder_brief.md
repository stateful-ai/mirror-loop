---
type: stream_doc
title: mirror_loop_m1_founder_brief
stream: mirror-loop
updated: '2026-05-25T15:31:29Z'
summary: '```markdown'
---

```markdown
# Mirror Loop — M1 Founder Brief (synthesis)

_Chief of Staff · 2026-05-25 · Stream `stream_20260524T184854Z_469b5e`_

## TL;DR
Three agents converged on the same M1 plan. Start Phase A today. Two canonical artifacts (`docs/m1_backlog.md` and `docs/core_loop_feel.md`) are declared but unwritten — close those gaps first because they gate the parallel tracks.

## North star
`python -m mirror play --seed 42` runs Prologue → Act 1 (with Beat-2 flavor swap) → Recalibration → Act 2 entry deterministically. `--baseline` produces a UX-identical run minus the adaptation layer. A single golden JSONL fixture replays byte-identical in CI. A founder on a clean checkout reaches the Reflection beat in under 5 minutes.

## Locked
- Python 3.11+, stdlib-first, no LLM in loop, no web/GUI.
- Spine: append-only JSONL events → pure reducer → MirrorState → render.
- Mirror axis: caution ↔ aggression.
- Adaptation: one templated flavor swap at Act 1 Beat 2.
- Reflection: single forced beat at Recalibration for M1.
- Latency spike: in-scope, one engineer-day, non-gating, output is a number.
- CI gates (both branch-protected): byte-identity replay under seed 42; structural baseline≡adaptive parity.

## Sequencing
- **Phase A (serial):** reconciliation doc → schemas + JSONL spec → session-objective doc → core_loop_feel.md → ADR-0001.
- **Phase B (parallel after A2):**
  - B1 Engine: scaffold → reducer → adaptation seam → reflection render → within-session persistence.
  - B2 Content: scene format → Act 1 graph → Beat-2 flavor pack → questionnaire intake.
  - B3 Risk: latency spike (anytime after A2).
- **Phase C (gate + surface):** capture golden fixture → wire CI gates → README "Try it" → founder cold-run smoke.

## Module layout
```
mirror/
  __main__.py     # python -m mirror play [--seed N] [--baseline]
  schemas.py      # frozen dataclasses, versioned
  jsonl.py        # canonical serialization
  reducer.py      # pure
  adaptation.py   # single seam; identity in baseline
  reflection.py   # pure render
  loop.py         # only impure module
  content/        # scenes, flavor, questionnaire
fixtures/m1_canonical.jsonl
tests/{reducer_property, reflection_snapshot, replay_byte_identity, baseline_parity}.py
```

## Definition of Done
1. `python -m mirror play --seed 42` runs the full slice end-to-end on a clean checkout.
2. `--baseline` is UX-identical minus the adaptation layer; parity test passes.
3. Recalibration renders purely from MirrorState; snapshot test imports no IO.
4. `fixtures/m1_canonical.jsonl` replays byte-identical under seed 42 (required check).
5. pytest + byte-identity + parity are required branch-protected checks; `main` no force-push.
6. `docs/core_loop_feel.md`, `docs/m1_backlog.md`, `docs/adr/0001-m1-locks.md` exist and are linked from README.
7. README "Try it" block names the two commands; founder cold-run reaches Reflection in < 5 min.
8. Latency spike has written one number into `docs/latency_budget.md` (non-gating).

## Risks
- Beat-2 placement could be narratively flat. Mitigation: flavor swap loud enough to be nameable in Reflection.
- Schema freeze too early forces churn. Mitigation: version constant; bump don't mutate.
- Latency spike scope-creep. Mitigation: time-box one day; output is a number.

## Out of scope (M2+)
LLM in loop, Acts 3/4, cross-session persistence, A/B run, event-log inspector, schema migration, RUN_CONFIG header, crash-safe append, web/GUI, adaptation cadence rule, golden-corpus expansion.
```

## Thought: Synthesized three near-aligned M1 plans into one brief; kept candidate-task list at the 7 cap by adopting CoS's reconciled set. Two standing process gaps flagged: `docs/m1_backlog.md` and `docs/core_loop_feel.md` are declared canonical but missing, and the runtime/platform ticket is stale. Next engagement: verify both docs landed and the stale ticket is closed before adding any new M1 work.
