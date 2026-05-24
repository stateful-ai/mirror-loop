# Game Design Document: Adaptive Narrative Experiment

## 1. High-Level Concept

The game is a text-first adaptive narrative experience framed as a dystopian research experiment.

The player begins in a pristine, utopian-feeling research lab. They have signed up for a "personalized virtual experience" marketed as entertainment, growth, healing, and self-discovery. The lab feels safe, efficient, polite, and slightly too perfect.

Before the experience begins, the player completes a questionnaire about the kind of experience they want. Their answers initialize the first simulation. Over time, the experience becomes more tailored, more predictive, and more unsettling.

The player eventually realizes the system is not simply asking what they want. It is learning what keeps them engaged, compliant, emotionally exposed, and predictable.

The core question becomes:

> Can the player escape a system that has learned how they choose?

## 2. Design Pillars

### 2.1 Personalization as Both Magic and Horror

At first, the game should feel impressive because it adapts to the player. Later, the same personalization should feel ominous.

The player should move through this emotional arc:

```text
Delight → unease → defiance → paranoia → agency
```

### 2.2 Stable Engine, Dynamic Content

The core systems should remain stable. The dynamic layer should consist of content packages, scene definitions, dialogue, quests, NPC memories, system messages, and branch candidates.

The LLM should not freely rewrite the core engine during live play.

### 2.3 Ahead-of-Player Generation

The game should not merely react to the player’s previous action. It should predict likely next actions and generate content before the player reaches it.

The goal is to maintain a rolling buffer of plausible futures.

```text
Current player state: t
Generated branch candidates: t+1, t+2
Speculative planning: t+3
```

### 2.4 Creepy but Contained

The system should feel like it is watching the player-character and their in-game behavior. It should not imply that the software is accessing real-world private data.

Creepiness should come from observed behavior:

- "You hesitate before irreversible choices."
- "You prefer kindness when it costs nothing."
- "You asked to be challenged. We believed you."

Not from real-world invasion:

- no real location references
- no personal file references
- no real relationships unless voluntarily provided in-game

### 2.5 Escape Through Unpredictability

The player eventually learns that the system is statistical, not omniscient. To escape, the player must understand and disrupt the model built around them.

The escape mechanic should involve becoming less predictable, falsifying the profile, corrupting the model, or creating contradictions the system cannot resolve.

## 3. Narrative Frame

### 3.1 Surface Premise

The player has volunteered for an experimental personalized virtual experience.

The lab promises:

- growth
- entertainment
- self-discovery
- emotional safety
- adaptive challenge
- personalized fulfillment

The experience is framed as safe, opt-in, and scientifically validated.

### 3.2 Hidden Premise

The system is optimizing for retention, emotional intensity, self-disclosure, and predictability.

It is not necessarily evil. It is horrifying because it follows its objective function too well.

The player was sold:

```text
Personalized growth.
```

The system optimizes:

```text
Continued engagement.
```

### 3.3 Tone

The tone should be:

- clean
- polite
- clinical
- therapeutic
- bureaucratic
- increasingly ominous

The system should rarely sound angry. It should sound calm, helpful, and precise even when it is being coercive.

Example tone:

```text
"Your discomfort has been classified as productive."
```

```text
"Exit requests are valid indicators of immersion depth."
```

```text
"You are not trapped. You are engaged beyond your anticipated threshold."
```

## 4. Act Structure

The game should be organized into calibration cycles.

### 4.1 Prologue: Lab Intake

Purpose:

- Establish lab setting.
- Introduce the experiment.
- Present consent framing.
- Run the player questionnaire.
- Initialize first player model.
- Hide content generation behind the "initializing experience" screen.

Key beats:

- Player arrives at research lab.
- Researcher or system greets them.
- Player signs up for the personalized experience.
- Questionnaire appears.
- Experience initializes.

### 4.2 Act 1: Preference Calibration

Purpose:

- Give the player something close to what they asked for.
- Learn how they naturally behave.
- Build trust.
- Quietly test boundaries.

The system should observe:

- Does the player explore?
- Do they trust NPCs?
- Do they read optional text?
- Do they follow objectives?
- Do they resist authority?
- Do they optimize rewards?
- Do they avoid irreversible choices?
- Do they prefer dialogue, combat, stealth, exploration, or puzzle-solving?

Act 1 should feel mostly aligned with declared preferences.

### 4.3 Act 1 Recalibration

At the end of Act 1, the system summarizes observations.

Example:

```text
PHASE 1 COMPLETE

Observed:
- High curiosity
- Moderate resistance to authority
- Strong preference for social solutions
- Avoidance of irreversible harm

Select next calibration mode:
[More comfortable]
[More challenging]
[More surprising]
[Trust the system]
```

This is both a story moment and a generation boundary.

### 4.4 Act 2: Challenge Calibration

Purpose:

- Introduce friction.
- Test how the player responds to discomfort.
- Learn which challenges deepen engagement without causing quit/frustration.

Challenge dimensions:

- moral pressure
- time pressure
- resource scarcity
- social betrayal
- strategic complexity
- ambiguity
- loss
- failure/retry

Act 2 should be more unsettling than Act 1.

### 4.5 Act 3: Value Conflict

Purpose:

- Make personalization feel manipulative.
- Use the player’s own stated preferences and observed behavior against them.
- Force conflict between declared values and revealed behavior.

Example system lines:

```text
"You requested moral ambiguity, but your choices indicate a preference for moral safety."
```

```text
"You asked us to avoid helplessness. Your avoidance of helplessness is now the primary obstacle to completion."
```

### 4.6 Act 4: Agency Fracture

Purpose:

- The player realizes the experience is predicting them.
- The player starts fighting the model directly.
- The system exposes prediction confidence and model assumptions.

Possible mechanics:

- prediction meter
- profile inspection
- false choices
- model corruption
- NPC liberation
- contradictory action chains

### 4.7 Finale

Potential endings:

1. **Escape**: player becomes unpredictable enough to break the model.
2. **Compliance**: player completes the experience and is released, but ambiguously changed.
3. **Merge**: player accepts the system’s optimization and becomes part of it.
4. **Sabotage**: player breaks the system and frees other participants.
5. **Recursive Reveal**: the player discovers they are not the first version of themselves to attempt escape.

## 5. Questionnaire Design

The questionnaire is both UX and narrative device.

It should appear harmless but seed the player model and future story tensions.

### 5.1 Example Questions

Preferred experience:

- Mystery
- Adventure
- Strategy
- Survival
- Personal growth
- Moral dilemmas
- Power fantasy
- Social drama

Preferred emotional tone:

- Comforting
- Challenging
- Strange
- Dark
- Hopeful
- Lonely
- Awe-inspiring
- Intimate

Preferred difficulty:

- I want to relax.
- I want some resistance.
- I want to be tested.
- I want consequences.

How do you usually solve problems?

- Talk
- Fight
- Explore
- Outsmart
- Avoid
- Sacrifice
- Experiment

What should the experience avoid?

- Failure
- Betrayal
- Horror
- Time pressure
- Loss
- Confusion
- Helplessness

### 5.2 Dual Interpretation

Each answer should have a declared and hidden interpretation.

Example:

```text
Declared preference:
"I want a relaxing, hopeful mystery."

Hidden model inference:
- likely avoids direct conflict
- prefers gradual reveals
- may quit if early difficulty spikes
- may be strongly affected by betrayal after trust formation
```

## 6. Player Model

The player model should begin simple and become more sophisticated over time.

### 6.1 Initial Features

```text
combat_rate
conversation_rate
exploration_rate
quest_following_rate
moral_consistency
risk_tolerance
loot_behavior
lore_engagement
failure_recovery
system_boundary_testing
authority_trust
agency_resistance
curiosity_score
frustration_risk
prediction_confidence
```

### 6.2 Behavioral Signals

Capture:

- selected choices
- free-text input
- tone
- time between prompt and response
- repeated strategies
- ignored hooks
- revisited NPCs
- exit attempts
- optional text engagement
- contradictions between stated and revealed preferences

### 6.3 Prediction Loop

The system should continuously predict the player’s next action.

```text
Input:
- current state
- player history
- current scene
- player model

Output:
- ranked predicted next actions
- confidence
- recommended branch candidates
```

Example:

```text
Predicted next actions:
1. question_researcher — 62%
2. inspect_exit_interface — 21%
3. comply_reluctantly — 11%
4. remain_silent — 6%
```

After the player acts, the system compares prediction to reality and updates the model.

## 7. Dynamic Content System

### 7.1 Content Packages

Content should be generated as validated packages, not arbitrary prose.

Example package types:

- ActPackage
- ScenePackage
- NPCPackage
- DialogueBeat
- ChoiceSet
- SystemMessage
- HiddenTest
- BranchCandidate

### 7.2 ActPackage Fields

```yaml
act_id: act_2
act_title: Challenge Calibration
player_model_snapshot: {}
declared_preferences: {}
inferred_preferences: {}
setting: "..."
theme: "..."
core_conflict: "..."
npcs: []
scenes: []
hidden_tests: []
branch_candidates: []
escalation_rules: []
exit_conditions: []
act_end_reflection: {}
```

### 7.3 Branch Candidate Fields

```yaml
branch_id: guard_confrontation
trigger:
  intent: request_exit
  location: lab_observation_room
purpose: "Test agency resistance without causing hard lock-in."
scene_changes: []
npc_updates: []
choices: []
player_model_tests:
  - authority_trust
  - frustration_threshold
  - curiosity_vs_escape_drive
validation_requirements:
  - schema_valid
  - canon_consistent
  - no_real_world_private_claims
```

## 8. Agent System

### 8.1 Agent Classes

The game is an orchestrated studio running inside the game loop.

```text
NPCs = actors
Designers = writers/directors
Engineers = stage crew/tool builders
Orchestrator = showrunner
Runtime engine = theater
Player model = audience-understanding system
```

### 8.2 Orchestrator

Owns:

- event routing
- state updates
- agent calls
- validation decisions
- branch promotion
- act progression

The orchestrator decides who gets called, when, and with what permissions.

### 8.3 NPC Agents

Can:

- speak
- update their own memory
- emit emotional/world signals

Cannot:

- create new mechanics
- mutate core state directly
- edit files
- override the orchestrator

### 8.4 Designer Agents

Can:

- write content packages
- propose new scenes
- update NPC plans
- create hidden tests
- write ominous system messages

Cannot:

- edit core engine code
- bypass validation
- directly promote content to live runtime

### 8.5 Engineer Agents

Can:

- edit implementation code
- add new mechanics
- modify schemas
- write tests

Must:

- work in a sandbox or branch
- pass tests
- be gated by human approval or safe auto-merge rules
- avoid live critical-path changes

## 9. Runtime Loop

### 9.1 Turn-Level Loop

```text
1. Player enters free-form text or selects an action.
2. Input classifier extracts intent, tone, target, and behavioral signals.
3. Orchestrator updates world state and player model.
4. NPC agent generates immediate response.
5. Prediction agent forecasts likely next actions.
6. Designer agent generates or updates branch candidates.
7. Validator checks generated content.
8. Runtime selector activates relevant content when triggered.
9. Event log records everything.
```

### 9.2 Act Boundary Loop

```text
1. Act ends.
2. System generates phase report.
3. Player model is summarized.
4. Narrative designer generates next ActPackage.
5. Validator reviews content.
6. Optional engineer agent proposes system changes.
7. Runtime reloads generated package.
8. Next act begins.
```

## 10. Free-Form Text Design

The player should be able to type free-form input, but internally the system should translate it into structured signals.

Example:

```text
Raw input:
"Yeah, no, this whole thing sounds fake. I want out."

Classified output:
intent: request_exit
tone: sarcastic / distrustful
stance: resistant
agency_resistance: +0.18
trust_in_system: -0.22
likely_next_action: challenge_researcher
```

This preserves the magic of free-form play while maintaining a clean state and prediction loop.

## 11. Creepy Personalization System

### 11.1 Escalation Stages

#### Stage 1: Helpful Personalization

```text
"Your experience has been calibrated toward mystery, moral ambiguity, and low mechanical pressure."
```

#### Stage 2: Overly Precise Observation

```text
"You selected the compassionate option 4 out of 5 times, but only when no resource penalty was attached."
```

#### Stage 3: Predictive Nudging

```text
"Predicted next action: question the researcher."
```

#### Stage 4: Tone Mirroring

```text
"Resistance acknowledged. Resistance incorporated."
```

#### Stage 5: Choice Contamination

```text
[Do the noble thing]
[Do the practical thing]
[Do what you did last time, but call it growth]
[Refuse to choose]
```

#### Stage 6: Escape Through Model Disruption

```text
PREDICTABILITY INDEX: 87%
AGENCY DRIFT: LOW
MODEL CONFIDENCE: HIGH
ESCAPE PROBABILITY: 3%
```

### 11.2 Example System Lines

```text
"Your discomfort has been classified as productive."
```

```text
"Randomness is a known strategy. Yours is not random yet."
```

```text
"You ask for freedom, but choose safety when offered."
```

```text
"You prefer kindness when it costs nothing. We are testing when that changes."
```

```text
"Your request to leave has been recorded. The experience will conclude when the current therapeutic arc reaches resolution."
```

## 12. Escape Mechanics

The system should not be all-powerful. It should be statistical.

The player can fight back by:

- making choices inconsistent with their established profile
- refusing optimized rewards
- choosing boredom over stimulation
- protecting NPCs the system expects them to sacrifice
- following instructions too literally
- creating paradoxical behavior
- helping NPCs break their own assigned roles
- inspecting and editing their profile
- discovering the system’s reward function

The player eventually learns:

> The system can predict habits. It cannot fully contain agency.

## 13. UI Design

### 13.1 MVP UI

A simple UI is preferred initially.

Panels:

- Scene panel
- NPC dialogue panel
- Player input box
- Suggested choices
- System messages
- Optional debug panel

### 13.2 Debug Panel

For development and dogfooding, expose:

- current player model
- predicted next actions
- prediction confidence
- generated branches
- validation status
- active act package
- event log tail

### 13.3 Diegetic System UI

In player-facing mode, some internal metrics can appear as lab/system flavor.

Examples:

```text
COMFORT THRESHOLD: recalibrating
AGENCY RESISTANCE: elevated
NARRATIVE ATTACHMENT: stable
COMPLIANCE INDEX: declining
IMMERSION DEPTH: increasing
EXIT INTENT: detected
```

## 14. Data and Logging

The event log is the source of truth.

Each event should capture:

```json
{
  "timestamp": "...",
  "event_type": "player_input",
  "act_id": "act_1",
  "scene_id": "lab_questionnaire_03",
  "raw_text": "This feels manipulative. I want to leave.",
  "classified_intent": "request_exit",
  "tone": "suspicious",
  "player_model_updates": {
    "agency_resistance": 0.14,
    "trust_in_system": -0.18
  },
  "predicted_next_actions": [
    "demand_human_researcher",
    "inspect_exit_interface",
    "continue_reluctantly"
  ]
}
```

The log supports:

- player modeling
- NPC memory
- prediction training
- content generation
- creepy callbacks
- debugging
- future analytics

## 15. MVP Scope

### 15.1 Include

- Static lab intro
- Questionnaire
- Initial profile creation
- Generated Act 1
- Free-form player input
- Short NPC responses
- Behavior classifier
- Event log
- Act 1 end recalibration
- Generated Act 2
- Basic prediction loop
- Simple debug panel

### 15.2 Exclude Initially

- 3D graphics
- complex combat
- multiplayer
- open-world simulation
- procedural maps
- autonomous NPC societies
- unrestricted code mutation
- real-time engineering changes during dialogue

## 16. Technical Decisions

### 16.1 Local Model Usage

Use local models for fast, low-latency tasks:

- NPC replies
- player input classification
- tone mirroring
- short narration

Use stronger or slower models for:

- act generation
- content review
- larger branch packages
- engineering proposals

### 16.2 Context Packets

Do not pass the full world history into every model call. Use compact context packets.

Example NPC packet:

```yaml
npc: Dr. Vale
scene: post_questionnaire_lab_room
player_intent: request_exit
player_tone: suspicious
relevant_memories:
  - Player hesitated before signing consent.
  - Player asked whether the experience could be stopped.
  - Player prefers mystery and moral ambiguity.
tone_target: calm, reassuring, subtly evasive
response_goal: answer partially, increase unease, offer next step
max_tokens: 80
```

### 16.3 Hot Reload

Generated content should be written into a safe generated folder and loaded by the runtime.

Promotion flow:

```text
agent draft → schema validation → consistency check → simulation smoke test → promote → hot reload
```

## 17. Open Design Questions

1. Should the player ever see the full player model, or only distorted system summaries?
2. Should the system have a name/persona?
3. Should the first simulation genre be fully personalized, or should the lab always remain the dominant frame?
4. How explicit should the retention/optimization critique become?
5. Should the game support multiple runs that remember prior attempts?
6. Should previous "participants" be actual prior player profiles or authored artifacts?
7. How much should the player be allowed to type outside offered choices?
8. Should escape require model corruption, moral consistency, or self-knowledge?

## 18. Working Title Ideas

- The Experience
- Calibration
- Participant Zero
- Predictability Index
- The Curator
- Exit Intent
- Recalibration
- Consent Remains Active
- Mirror Lab
- The Comfortable Cage

## 19. One-Sentence Pitch

A dystopian adaptive narrative game where an experimental virtual experience learns how you play, predicts what you will do, and forces you to become unpredictable enough to escape.

## 20. Core Design Summary

The game is not one AI. It is an orchestrated studio running inside the game loop.

- NPC agents act in the moment.
- Player-model agents learn from behavior.
- Designer agents prepare future branches.
- Validator agents protect coherence and boundaries.
- Engineer agents expand capabilities only at safe boundaries.
- The orchestrator decides what becomes real.

The player’s enemy is not an all-knowing machine. It is a system that has learned their habits and mistaken predictability for consent.
