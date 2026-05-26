---
type: stream_doc
title: founder_brief
stream: mirror-loop
updated: '2026-05-26T07:58:26Z'
summary: Consensus (all three agents)
---

### Consensus (all three agents)
- **Plan shape locked**: 8 PRs / 4 waves on `stateful-ai/mirror-loop`, all targeting `game/` per ADR-0003. W0 hygiene (PR0/PR0a/PR0b) → W1 verify+snapshot (PR1) → W2 content ∥ engine (PR2+PR3 ∥ PR4+PR5) → W3 playtest gate (PR6 solo → PR7 3-human).
- **DoD**: clean-checkout `python -m game --variant adaptive --seed 42 --persona caution_first` plays full arc; loader rejects untagged scenes; CI smoke asserts run-log content not just exit 0; ≥3/4 humans report ≥3/4 felt criteria; ticket store free of `mirror/`/`saves/`/cross-stream tickets.
- **Out of scope** (do not rebuild, do not ticket): LLM in loop, byte-identity replay as branch-protected gate, cross-session persistence, ahead-of-player generation, Acts 3–4, A/B harness, telemetry/consent, schema migrations, renaming `game/`→`mirror/`.

### Tensions / dissent
- **None substantive.** Eng Lead emitted 5 candidates; Infra Architect and CoS both explicitly refused to re-emit them ("would be the duplicate-task planning bug"). This is the system working — Eng surfaces, Infra/CoS de-dupe. The 5 are real; they're just waiting on founder approval.
- **CoS recurrence signal**: "cross-stream task leak" now seen x7 — flagged as highest-leverage company-os change. Not blocking M1 but worth noting.

### What's actually blocking
1. Founder approval of Eng's 5 pending candidates (already in active queue but not yet absorbed into PRs).
2. PR0 hasn't landed — until branch protection on `main` requires commit-guard + headless-smoke checks, every other PR is in phantom-completion risk.
3. PR1 is the real falsifiability point for ADR-0003's "substrate already on disk" claim. If `python -m game` doesn't run on a clean checkout, the whole "we just need content + arc" framing is wrong and we re-plan.

### Approved-decision constraint check
- ADR-0003 (`game/` is canonical, `mirror/` rename is out of scope) is treated as binding by all three agents. No conflict with input.
