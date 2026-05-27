# Decisions

This log captures founder/team decisions that the codebase encodes — the
*why* behind otherwise puzzling choices. Append-only; don't rewrite past
entries.

## 2026-05 — Mirror axis = caution ↔ aggression
The first dimension the system measures is caution ↔ aggression because
it's the cleanest signal the intake fixtures can seed and the easiest to
pin in tests. Future axes will land in M2.

## 2026-05 — Determinism over richness
Adaptive behavior is gated by byte-identical replay. We prefer fewer
adaptive moves that reliably reproduce than richer adaptations that
drift run-to-run.
