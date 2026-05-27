# Architecture

Mirror Loop is a Python package split into focused subpackages:

- 'mirror' — the adaptive narrative engine; intake, schema, play, state, log.
- 'game' — the game data and scene content; act1, adaptation, flavor, playtest.
- 'loop' — the main game loop driver.
- 'runtime' — runtime services around the loop.
- 'acceptance' — acceptance tests that pin the player-facing behavior.
- 'fixtures' — golden fixtures used by the determinism-pinned tests.

Each subpackage stays single-concern; cross-package imports flow one way
(data -> engine -> loop). The two intake fixtures
(fixtures/seed42_answers.json and seed42_answers_aggression.json) anchor
the Mirror axis tests.
