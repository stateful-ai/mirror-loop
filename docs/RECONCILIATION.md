# Mirror Loop — Design Reconciliation

**Date:** 2026-05-24 · **Inputs:** `docs/game_design.md` (seed) vs. `README.md` (current scope) · **Status:** Direction confirmed with minor amendments.

---

## 1. One-Page Summary of the Seed Design

A **text-first adaptive narrative game** framed as a dystopian research experiment. The player signs up for a "personalized virtual experience," fills out a questionnaire (which secretly seeds a player model), and moves through an emotional arc — **delight → unease → defiance → paranoia → agency** — as the system shifts from helpful personalization to predictive manipulation. The central question: *can the player escape a system that has learned how they choose?*

**Pillars:** personalization as magic-then-horror; a **stable engine with dynamic content** (LLMs never rewrite core code at runtime); **ahead-of-player generation** (a rolling buffer of t+1/t+2 branch candidates); creepy-but-contained (adapts only to *in-game* behavior, never real-world data); **escape through unpredictability** (the system is statistical, not omniscient).

**Structure:** Prologue (lab intake + questionnaire) → Act 1 Preference Calibration → Recalibration → Act 2 Challenge → Act 3 Value Conflict → Act 4 Agency Fracture → Finale (5 endings: Escape / Compliance / Merge / Sabotage / Recursive Reveal).

**Systems:** a **player model** (~15 behavioral features + a prediction loop that scores ranked next actions and self-corrects); **validated content packages** (Act/Scene/NPC/Dialogue/Choice/SystemMessage/HiddenTest/BranchCandidate); an **agent studio** — Orchestrator (showrunner), NPC actors, Designer writers, Validator, optional Engineer (sandboxed, off the live path); a **turn loop** and **act-boundary loop**; an **event log as source of truth**; compact context packets; and a hot-reload promotion flow (`draft → schema validate → consistency check → smoke test → promote`).

**MVP (seed §15):** static lab → questionnaire → initial profile → generated Act 1 → free-form input → short NPC replies → behavior classifier → event log → Act 1 recalibration → generated Act 2 → basic prediction loop → simple debug panel. Excludes 3D, combat, multiplayer, open world, unrestricted code mutation.

---

## 2. Direction: **Confirmed**

The `README.md` scope is a **faithful, MVP-focused projection of the seed**. No pillar, safety boundary, or architectural commitment is contradicted. The README's value-add is operational: it commits to a **stack** (React/Next.js, Node/FastAPI, Ollama local 3B–8B for fast tasks, optional Claude/OpenAI for slow tasks, YAML/JSON + Zod/Pydantic, SQLite/JSON log), a **repo structure**, and a **milestone ladder (v0.1–v0.5)** that sequences the seed's vision into shippable increments. Proceed on the README's milestone ladder.

---

## 3. Conflicts & Discrepancies Flagged

| # | Item | Seed (`game_design.md`) | Scope (`README.md`) | Resolution |
|---|------|-------------------------|---------------------|------------|
| 1 | Doc location | File lived at repo root | Structure specifies `/docs/game_design.md` | **Resolved** — moved to `docs/game_design.md` (README is authoritative). |
| 2 | Working title | §18 lists "Mirror **Lab**", not "Mirror Loop" | Project named **Mirror Loop** | **Amend seed** — name is decided; record "Mirror Loop" as canonical, retire the title brainstorm. |
| 3 | MVP boundary | §15 MVP ends at "generated Act 2 + basic prediction" | Same content split across **v0.1 + v0.2** | No conflict — README v0.2 == seed MVP boundary. v0.3–v0.5 are post-MVP. Stated here to prevent scope drift. |
| 4 | Act/ending coverage | Acts 3–4 + 5 endings fully specified | Mentions only Act 1 → Act 2 | Not a conflict (README is MVP-scoped). Acts 3–4 and endings remain **deferred backlog**, not dropped. |
| 5 | Multi-run memory | §17 Q5 + ending #5 (Recursive Reveal) imply persistence across runs | Silent | **Open question** — out of MVP scope; decide before designing the event-log/profile persistence schema. |

No contradictions found in safety boundaries, agent permissions, the engine/content split, or the local-first model strategy — these are **consistent across both documents**.

---

## 4. Recommended Next Actions

1. **(Done)** Relocate seed to `docs/game_design.md` so the README's structure is accurate.
2. Add "Mirror Loop" as the canonical title in `docs/game_design.md` §18 (amendment #2).
3. Treat README **v0.1** as the next implementation unit (static lab + questionnaire + generated Act 1 + NPC reply + event log).
4. Carry the **open questions** (seed §17, esp. multi-run memory) into design review before persistence work begins.
