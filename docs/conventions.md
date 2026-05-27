# Conventions

## File layout
- `mirror/` is the engine (intake, schema, state, log, play).
- `game/` is content/data (act1, adaptation, flavor).
- `acceptance/` holds player-facing acceptance tests.
- `fixtures/` holds golden inputs (seed42_answers*.json).

## Vocabulary
- The Mirror *axis* is the dimension measured (caution ↔ aggression).
- The Mirror *prediction* is the system's bet on the next choice.
- The *Reflection beat* is loop 3's narrative recognition moment.

## Tests
- One axis of variation per test; rely on parametrize.
- Determinism gate: every adaptive behaviour byte-identical replay.

## Commits
- Imperative subject; body explains the *why*.
