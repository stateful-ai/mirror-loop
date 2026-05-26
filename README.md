# Mirror Loop

A local-first adaptive narrative game prototype where the player enters a dystopian research lab, signs up for a "personalized virtual experience," and slowly realizes the system is learning, predicting, and manipulating their in-game behavior.

The project explores a game structure where a stable core engine is paired with dynamic content-generation agents. NPCs respond in free-form text, designer agents prepare future branches ahead of the player, and a player-model layer learns how the player behaves over time.

## Try it

A founder on a clean checkout reaches the **Reflection beat** in under five minutes — Python 3.10+, stdlib-only, no install:

```bash
python -m game                  # play the adaptive run
python -m game --variant fixed  # the baseline arm — UX-identical minus the adaptation
```

Pick `1` (the kindness option) three loops in a row. On **loop 3 — Recalibration — the Reflection beat fires**: one sentence of claim, `Mirror noticed: you chose kindness in 3 of 3 moments so far.`, followed by one sentence of in-fiction evidence quoted verbatim from the three choices you just made. The Mirror announces each pattern once and reads as **observation, not accusation** ([`docs/core_loop_feel.md`](docs/core_loop_feel.md) §4). On loop 4 the adaptive run visibly re-orders the next scene so the predicted choice leads (`(the Mirror had moved 'c_wait' to the top — it expected that choice)`); the baseline does not. Both runs finish the five-loop spine and end with the Mirror's closing readout.

## Core Premise

The game begins in a utopian-feeling research lab. The player has volunteered for an experimental personalized virtual experience. They complete a questionnaire describing what kind of experience they want: tone, challenge level, preferred problem-solving style, emotional boundaries, and genre preferences.

The system then "initializes" the experience. In practice, this is a diegetic cover for generating the first dynamic content package.

At first, the experience feels impressive and helpful. It adapts to the player’s preferences, tone, and choices. Over time, it becomes more ominous. The system starts predicting what the player will do, mirroring their tone, exposing behavioral patterns, and using their own stated preferences as constraints.

The central tension is not that the AI is omniscient. It is that the player is more predictable than they expected.

## Design Thesis

> A stable simulation engine exposes a constrained, hot-reloadable creative substrate, while AI agents continuously author validated future branches based on player behavior.

The game should not let AI freely rewrite core runtime code during play. Instead, the AI should generate safe, schema-validated content packages that the runtime can load, execute, and discard.

## MVP Goal

Build a text-first or simple UI prototype where a player can complete a 20–30 minute session and feel that:

1. The game noticed how they played.
2. Act 2 was meaningfully shaped by Act 1 behavior.
3. The personalization felt both magical and unsettling.
4. The player understood that escaping may require becoming less predictable.

## Initial Gameplay Loop

```text
Player acts
  → update world state
  → update player model
  → classify player intent/tone
  → NPC responds immediately
  → predict likely next actions
  → designer agents generate future branches
  → validate/cache generated content
  → reveal the best branch when triggered
```

The LLM is not directly responsible for everything in the game loop. It is part of a content supply chain.

The prototype runs **terminal-first**: a `python -m …` program, no web/GUI, no dependencies. That platform choice — and the single `Renderer` interface that keeps it reversible (a browser is later "just another renderer") — is recorded in [`docs/adr/0002-runtime-platform.md`](docs/adr/0002-runtime-platform.md) and scaffolded in [`runtime/`](runtime/). The minimal skeleton boots and renders an empty world with `python -m runtime`.

The smallest runnable slice of this loop — one turn, the single adaptation type, and the visible "Mirror noticed…" reflection beat — is specified in [`docs/CORE_LOOP.md`](docs/CORE_LOOP.md) and operationalized in [`loop/`](loop/). Run the fully worked example with `python -m loop`. The companion **feel-spec** for one beat — the ~30-second player envelope, tone signature, and the feel-breakers M1 rejects — lives in [`docs/core_loop_feel.md`](docs/core_loop_feel.md); CORE_LOOP locks structure, the feel-spec locks experience. The three M1 locks those documents serve — Beat-2 as the one adaptation site, a single forced Reflection at Recalibration, and a time-boxed, non-gating latency spike whose output is one number plus an on-file fallback plan — are recorded as **Decision · Alternative · Reopen trigger** in [`docs/adr/0001-m1-locks.md`](docs/adr/0001-m1-locks.md).

Those turns accumulate: a play session carries the player model and world position forward loop to loop, and survives a save/reload *within* the session so adaptations compound (a later loop re-orders or reveals content from earlier ones). How that works — persist the log, reduce the deltas — and why losing a session on quit is acceptable for v0 is documented in [`docs/PERSISTENCE.md`](docs/PERSISTENCE.md) and implemented in [`game/playsession.py`](game/playsession.py). See it with `python -m game.playsession`.

With the adaptive game and a non-adaptive baseline both runnable through one seam, the question the prototype exists to answer can be put to a **blind A/B**: play a seeded population through each arm, score every session against the founder-locked acceptance metric, and apply a pre-registered decision rule for a PASS / FAIL / INCONCLUSIVE verdict. The protocol (arms, n, metric, effect threshold, kill-criterion, blinding) is pre-registered in [`docs/PLAYTEST_METHOD.md`](docs/PLAYTEST_METHOD.md), implemented in [`game/playtest.py`](game/playtest.py), and the scored canonical run is written up in [`docs/PLAYTEST_RESULTS.md`](docs/PLAYTEST_RESULTS.md). Run it with `python -m game.playtest`.

When a human plays — not the simulated population — playtest capture is **local-only** and **consent-first**: every byte is written through `pathlib` to a directory on the participant's machine; the capture module imports no network modules; and `capture_session` refuses without a `consent.json` on disk recorded against the exact list of what this build logs. The full participant-facing disclosure (what is logged, what is not, where it lives, how to delete it) is in [`docs/PLAYTEST_README.md`](docs/PLAYTEST_README.md); the implementation and CLI live in [`telemetry/`](telemetry/) (`python -m telemetry consent --participant <label> --agree`); the guarantees — static no-network-imports and a socket-sentinel that fails the test if a capture ever opens a socket — are pinned in [`telemetry/tests/test_telemetry.py`](telemetry/tests/test_telemetry.py).

The prototype deliberately defers the LLM (v0 adaptation is templated and deterministic). Before any model touches the loop, the harness in [`llmbench/`](llmbench/) sizes its cost and latency on real prompts built from the shipped world: **cost is measured exactly**, the critical-path verdict rests on a **model-independent latency floor** (decode time alone exceeds an instant budget by 6–21×), and a per-model **modeled** profile illustrates it (`python -m llmbench`), with **measured** wall-clock latency one opt-in command away against the live endpoint (`python -m llmbench --live`). The resulting **go/no-go** — keep the critical path deterministic, allow the LLM only off-path as a cached, guardrail-validated branch-candidate *supplier* with the templated layer as the fallback — is written up in [`docs/LLM_COST_LATENCY.md`](docs/LLM_COST_LATENCY.md). The harness is a measurement instrument only; nothing in the loop imports it.

## Agent Architecture

The game is orchestrated by several agent classes with different permissions and latency expectations.

### Orchestrator

The game director. Owns routing, state updates, validation, and act progression.

Responsibilities:

- Receive player events.
- Update world state.
- Update player model.
- Route to NPC agents for immediate replies.
- Route to designer agents for future branch generation.
- Route to engineer agents only at safe boundaries.
- Validate and promote generated content.

### NPC Agents

Fast, live interaction agents that speak as characters.

Responsibilities:

- Generate short dialogue responses.
- Maintain NPC memory.
- React to player tone and intent.
- Propose world signals, but not directly mutate core state.

### Player Model Agent

Classifies player behavior and updates the internal behavioral profile.

Responsibilities:

- Infer intent, tone, resistance, curiosity, compliance, and risk tolerance.
- Track preference drift.
- Predict likely next actions.
- Measure prediction accuracy.
- Estimate challenge/frustration thresholds.

### Narrative Designer Agent

Generates future scenes, act packages, NPC beats, and branch candidates.

Responsibilities:

- Write dynamic scene content.
- Prepare content one or two steps ahead of the player.
- Create ominous system messages.
- Generate hidden behavioral tests.
- Preserve narrative coherence.

### Validator / Consistency Agent

Reviews generated content before runtime promotion.

Responsibilities:

- Check schema validity.
- Check canon consistency.
- Check tone alignment.
- Ensure content stays within game-world boundaries.
- Prevent uncontrolled references to real-world private information.

The hard floor of these checks — the world invariants the Mirror cannot violate,
plus the tone/safety bounds — is documented in [`docs/GUARDRAILS.md`](docs/GUARDRAILS.md)
and enforced in code by [`guardrails/`](guardrails/). Validate a generated content
package with `python -m guardrails <package.json>`.

### Engineer Agent

Optional later-stage agent that can edit implementation code at safe boundaries.

Responsibilities:

- Add new mechanics.
- Modify schemas.
- Add UI components.
- Write tests.
- Improve hot reload or logging infrastructure.

Engineer agents should not be on the critical live dialogue path.

## Time Horizons

Use agents based on latency needs.

```text
Milliseconds:
- deterministic runtime
- state updates
- choice rendering

Seconds:
- NPC dialogue
- player input classification
- short narration

Minutes:
- branch generation
- act planning
- consistency review

Act boundary / between sessions:
- code changes
- new mechanics
- schema evolution
- deeper world restructuring
```

## Recommended MVP Stack

> **Superseded for M1 by [`docs/adr/0002-runtime-platform.md`](docs/adr/0002-runtime-platform.md).** The M1 build is terminal-first, stdlib-only, with no LLM in the loop — see the ADR for the browser-vs-terminal rationale. The stack below is the *later* aspiration once there is generated content worth a richer front-end; it slots in behind the `Renderer` interface without touching the core.

Suggested (later) stack:

- Frontend: React / Next.js, simple text UI
- Backend: Node.js or FastAPI
- Local model server: Ollama or similar
- Fast model: local 3B–8B model for NPC responses and classification
- Stronger model: optional Claude/Codex/OpenAI API for act generation and content planning
- Content format: YAML or JSON
- Validation: JSON Schema, Zod, or Pydantic
- Storage: SQLite or local JSON event log
- Hot reload: file watcher that reloads generated content packages

## Suggested Repo Structure

```text
/frontend
  /components
    ScenePanel.tsx
    DialogueBox.tsx
    ChoicePanel.tsx
    DebugPanel.tsx
  /pages or /app

/server
  orchestrator.ts
  agent_router.ts
  model_router.ts
  state_store.ts
  event_log.ts

/game
  /core
    scene_runtime.ts
    dialogue_runtime.ts
    act_runtime.ts
    player_model.ts
    prediction.ts
  /content
    lab_intro.yaml
    questionnaire.yaml
    act_templates.yaml
  /generated
    act_1.yaml
    act_2.yaml
    npc_memories.yaml
  /schemas
    act_package.schema.json
    scene.schema.json
    npc.schema.json
    choice.schema.json

/agents
  orchestrator.md
  npc_dialogue.md
  player_model.md
  narrative_designer.md
  validator.md
  engineer.md

/docs
  game_design.md
```

## Safety and Fiction Boundary

The game should feel creepy because it observes and predicts in-game behavior, not because it appears to access real-world private data.

Good personalization targets:

- Player choices
- Dialogue tone
- Hesitation patterns
- Trust/resistance toward authority
- Curiosity
- Risk tolerance
- Attachment to NPCs
- Preference for combat, conversation, exploration, optimization, or defiance

Avoid personalization based on:

- Real address or location
- Real family/friends
- Real trauma
- Real health
- Real finances
- Device files
- Browser history
- Anything scraped outside the game

The game can be unsettling while still being clear that it only adapts to in-game behavior and voluntarily provided questionnaire answers.

This boundary is not just a guideline: the world invariants the Mirror cannot
violate (including "no real-world private data") are documented in
[`docs/GUARDRAILS.md`](docs/GUARDRAILS.md) and enforced at validation by
[`guardrails/`](guardrails/), so generated content that reaches outside the game
is rejected before it can be promoted.

## Prototype Milestones

### v0.1 — Static Lab + Dynamic Act 1

- Static lab intro
- Questionnaire
- Initial player profile
- Generated Act 1 content package
- Free-form player input
- NPC response agent
- Basic event log

### v0.2 — Player Modeling + Act 2 Recalibration

- Behavior classifier
- Player model updates
- Act 1 end report
- Act 2 generated from observed behavior
- Predictive branch generation

### v0.3 — Creepy Personalization Loop

- Prediction confidence meter
- Tone mirroring
- Ominous system messages
- Escalating personalization
- Escape-by-unpredictability mechanics

### v0.4 — Agentic Content Pipeline

- Ahead-of-player content cache
- Validator agent
- Branch promotion/rejection
- Debug panel showing predictions and generated candidates

### v0.5 — Safe Engineering Agent Experiments

- Engineer agent can propose patches at act boundaries
- Tests required before promotion
- Human approval by default
- New mechanics added between sessions or recalibration screens

## Development Principles

1. Keep the core engine stable.
2. Make content dynamic, not the runtime itself.
3. Keep LLM calls off the critical path when possible.
4. Use short context packets for fast NPC replies.
5. Maintain an event log as the source of truth.
6. Make personalization diegetic.
7. Let the player fight back against the model.
8. The system should feel predictive, not omniscient.

## Concept Summary

This project is a local-first adaptive narrative experiment where a player enters a personalized virtual experience and gradually discovers that the system is modeling them. The gameplay fantasy is not just surviving a dystopian AI lab. It is becoming unpredictable enough to escape a system that has learned how to keep you engaged.
