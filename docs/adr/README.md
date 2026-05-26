# Architecture Decision Records

Each ADR records one architectural decision, its rationale, and its consequences,
so the *why* survives the diff. ADRs are append-only: to change a decision, add a
new ADR that supersedes the old one rather than editing history.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-m1-locks.md) | M1 locks (mirror axis · Beat-2 adaptation · single-beat Reflection) | Accepted |
| [0002](0002-runtime-platform.md) | Runtime / platform: terminal (CLI), rendering behind one interface | Accepted |

`0001` records the three gameplay locks that fix the shape of the M1 slice — the
one mirror axis (caution↔aggression), the one adaptation site (Act 1 Beat 2),
and the single forced Reflection at Recalibration — and cites
[`../core_loop_feel.md`](../core_loop_feel.md) (the canonical 30s-beat
feel-spec) as a normative input alongside [`../CORE_LOOP.md`](../CORE_LOOP.md)
for structure and [`../ADAPTATION.md`](../ADAPTATION.md) for the Beat-2 swap.
`0002` records the foundational runtime/platform choice the gameplay locks
build on top of.
