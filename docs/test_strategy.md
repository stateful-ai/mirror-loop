# Test strategy

- **Determinism gate.** Every adaptive behaviour must replay byte-identically
  under the same seed. The golden-replay fixture pins this.
- **Acceptance vs. unit.** `acceptance/` tests live close to player-facing
  behaviour and read like UX guarantees. Unit tests under `mirror/tests` /
  `game/tests` pin individual modules.
- **No mocking the schema.** Tests load the real `mirror/schema.py`.
  Mocking schema makes refactors silently safe when they shouldn't be.
- **One axis per test.** Avoid combinatorial test bodies; pick one axis
  of variation per test and rely on parametrize.
