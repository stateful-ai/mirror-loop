# Runbook

## Local dev loop
- Run: `python -m game` (adaptive) or `python -m game --variant fixed` (baseline).
- Tests: `pytest`.

## Determinism gate
- Golden fixtures live under `fixtures/`. If a test fails on a fixture,
  inspect the diff before regenerating — usually you've changed
  behaviour you didn't mean to.

## Common issues
- See docs/troubleshooting.md.

## When you're stuck
Open a discussion or draft PR with the smallest reproducer you can find.
