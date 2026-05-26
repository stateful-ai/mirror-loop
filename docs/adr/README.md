# Architecture Decision Records

Each ADR records one architectural decision, its rationale, and its consequences,
so the *why* survives the diff. ADRs are append-only: to change a decision, add a
new ADR that supersedes the old one rather than editing history.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-m1-locks.md) | M1 locks (Beat-2 placement · single-forced Recalibration cadence · latency-spike scope) | Accepted |
| [0002](0002-runtime-platform.md) | Runtime / platform: terminal (CLI), rendering behind one interface | Accepted |

`0001` records the three M1 locks that make the Beats-Baseline Prediction Test
runnable: the one adaptation site (Act 1 Beat 2), the single forced Reflection
at Recalibration, and the time-boxed, non-gating, number-plus-fallback-plan
shape of the latency spike. Each lock is stated as **Decision · Alternative ·
Reopen trigger** so a later contributor can tell what would supersede it. The
ADR cites [`../core_loop_feel.md`](../core_loop_feel.md) (the canonical
30s-beat feel-spec), [`../CORE_LOOP.md`](../CORE_LOOP.md) (structure),
[`../ADAPTATION.md`](../ADAPTATION.md) (the Beat-2 swap), and
[`../latency_report_m1.md`](../latency_report_m1.md) (the measured floor and
the on-file pre-generate / cache plan) as normative inputs.
`0002` records the foundational runtime/platform choice the M1 locks build
on top of.
