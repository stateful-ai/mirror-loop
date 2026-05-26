---
type: stream_doc
title: founder_brief
stream: mirror-loop
updated: '2026-05-26T06:02:41Z'
summary: What the agents said
---

### What the agents said
- **Engineering Lead** and **Infra Architect** converged on a 12-PR spine for a `mirror/` package, with PR0 = README purge + commit-guard CI, then scaffold → schema → JSONL log → reducer → content+engine in parallel → keystone loop → reconcile. 4-clause DoD (smoke green, two answer-sets diverge, commit guard green, human playtest ≥3/4·≥3/4).
- **Chief of Staff** (pass 14) reports the underlying premise is stale: `stateful-ai/mirror-loop` already has `game/` on disk — `__main__.py` with `--persona / --variant / --seed / --demo / --log`, 10+ Act-1 scenes, working `playsession.py` save/reload, `acceptance/predictability.py` with passing+failing fixtures. 12 PRs merged. The `mirror/`-named tickets are duplicates of already-shipped substrate.

### Where they agree
- M1 slice: one ~15–20 min terminal session, intake → Act 1 → Recalibration → re-aimed Act 2 → escape ending.
- The felt-criteria bar: ≥3/4 humans report ≥3/4 of *noticed me · Act 2 shaped to that read · unsettled · escape = stop being predictable*.
- Out of scope: LLM in loop, byte-identity gate, A/B harness, telemetry, Acts 3–4, GUI.
- Anti-phantom posture: no "M1 done" without a green CI run linked.

### Tension (must resolve)
- **Package name.** Eng Lead + Infra Architect plan against `mirror/`. CoS reports `game/` is already canonical on disk. If we follow the 12-step plan literally, we re-scaffold over working code. **CoS's ADR-0003 (`game/` is canonical) is the right call** — it makes ~19 active tickets duplicates to close, not work to do.
- **Posture.** Eng/Infra read this as green-field. CoS reads it as 70% built, blocked on content + hygiene. CoS's read matches the repo evidence (12 merged PRs, files on disk).
- **PR0.** Eng Lead's PR0 (README purge + commit-guard + branch protection) is still valid and additive — it doesn't conflict with `game/` being canonical. Keep it; just retarget all downstream PRs at `game/`, not `mirror/`.

### Recommended reconciliation
1. Adopt CoS's read of repo reality. ADR-0003 wins.
2. Keep Eng Lead's PR0 (purge + commit-guard + PR template + branch protection) — it's the anti-phantom gate either way.
3. Drop the `mirror/` scaffold/schema/log/reducer steps (PR1–4 in Eng/Infra plans). That work is already shipped under `game/`.
4. Critical path becomes: PR0 (purge + guards) → Wave 0 bulk-close → Act 2 content + Recalibration + escape authoring → wire in `python -m game` → structural + diff tests + headless CI → human playtest → README reconcile.
5. DoD: merge Eng/Infra's 4-clause DoD with CoS's clause 4 (active task store contains only `game/`-targeted tickets). That's the 5-clause bar.

### Out of scope (do not let leak in)
LLM-in-loop, latency spike, byte-identity gate, A/B harness, determinism-hazard sweep, telemetry/consent, Acts 3–4, GUI, cross-session persistence, `saves/` architecture.
