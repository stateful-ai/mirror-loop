# Troubleshooting

## 'pytest' is not found
Activate the project venv first: `source .venv/bin/activate` (or run via
`./.venv/bin/python -m pytest` directly).

## Mirror predictions feel sticky
The deterministic axes only move on observed choices; long-running
sessions with low choice rate keep the prediction near the initial
intake. Increase variation in the intake fixture or run additional loops.

## Tests fail with 'fixture has changed'
Regenerate the golden fixture only after a deliberate behaviour change,
via `python -m mirror.tests.regen_golden` (or the equivalent helper).

## Stuck in a recalibration that won't fire
Check `mirror/state.py` — the threshold for the loop-3 Reflection beat
is encoded as a constant; it can be tightened/relaxed per axis there.
