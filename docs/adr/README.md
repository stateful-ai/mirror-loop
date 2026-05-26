# Architecture Decision Records

Each ADR records one architectural decision, its rationale, and its consequences,
so the *why* survives the diff. ADRs are append-only: to change a decision, add a
new ADR that supersedes the old one rather than editing history.

| ADR | Title | Status |
|-----|-------|--------|
| 0001 | M1 locks (mirror axis · Beat-2 adaptation · single-beat Reflection) | Planned — not yet written (execution plan §A5) |
| [0002](0002-runtime-platform.md) | Runtime / platform: terminal (CLI), rendering behind one interface | Accepted |

`0001` is intentionally reserved: the M1 locks predate this directory and have
their own ticket. When written, ADR-0001 cites
[`../core_loop_feel.md`](../core_loop_feel.md) (the canonical 30s-beat feel-spec)
as a normative input — alongside [`../CORE_LOOP.md`](../CORE_LOOP.md) for
structure and [`../ADAPTATION.md`](../ADAPTATION.md) for the Beat-2 swap — so
the feel decisions the ADR locks have a single source of truth. `0002` records
the foundational runtime/platform choice, which the gameplay locks build on top
of.
