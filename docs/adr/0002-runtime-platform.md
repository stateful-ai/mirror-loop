# ADR-0002 — Runtime / platform: terminal (CLI), rendering behind one interface

**Status:** Accepted · **Date:** 2026-05-25
**Scope:** the runtime/platform the prototype boots on, and the seam that keeps
that choice reversible.
**Grounded in:** the locked M1 runtime (Python 3.11+, stdlib-first, *no web/GUI,
no LLM in loop* — [`docs/mirror_loop_m1_founder_brief.md`](../mirror_loop_m1_founder_brief.md),
[`docs/mirror_loop_m1_synthesis.md`](../mirror_loop_m1_synthesis.md)); the locked
acceptance gate ([`docs/THESIS.md`](../THESIS.md)); and the company principle
*"keep the simulation core pure (no I/O, render, clock, entropy) and the runtime a
thin shell, making the platform choice reversible."*

> **Note on numbering.** [`0001`](./0001-m1-locks.md) records the *M1 gameplay
> locks* (mirror axis, Beat-2 adaptation, single-beat Reflection cadence). This
> ADR records the separate, foundational runtime/platform decision those
> gameplay locks build on top of.

---

## Context

The prototype must run somewhere. Two platform families were on the table:

- **Terminal / CLI** — a `python -m …` program that reads choices and prints
  scenes to a text stream.
- **Browser** — the React/Next.js text UI sketched in the README "Recommended MVP
  Stack" (a designer-facing aspiration written before the M1 slice was scoped).

The M1 slice is deliberately narrow: a deterministic, no-LLM core loop whose whole
reason to exist is to run the **Beats-Baseline Prediction Test** (THESIS §2) and
make the Reflection beat legible. Its two load-bearing CI gates are **byte-identity
replay under a fixed seed** and **structural baseline≡adaptive parity**. Whatever
platform we pick must not get in the way of those.

## Decision

**For M1 the runtime is a terminal/CLI program, and *all* player-facing output
flows through a single rendering interface — `runtime.Renderer` — that the rest of
the system depends on instead of writing output directly.**

- `runtime.WorldView` is a render-agnostic snapshot of "what the player should see
  this frame" (title, optional prompt, choices, status). The engine produces a
  `WorldView`; it never formats output itself.
- `runtime.Renderer` is the one interface (a `typing.Protocol`). M1 ships exactly
  one production implementation, `TerminalRenderer` (writes to an injected text
  stream, default `stdout`), plus `RecordingRenderer` (captures frames) so the
  seam is demonstrably swappable, not theoretical.
- `runtime.boot()` is the thin shell: it constructs a world view, hands it to a
  renderer, and returns. It is the only place output happens.

The minimal skeleton boots and renders an **empty world** today
(`python -m runtime`) — before any scenes, reducer, or adaptation exist — so the
boot path and the render seam are proven end to end first.

## Rationale

1. **Determinism and testability.** The gate is byte-identity replay. A terminal
   renderer writing to a captured stream produces output we can assert on
   exactly; there is no DOM, no async paint, no browser timing to make a run
   non-reproducible. Rendering stays a pure function of a `WorldView`.
2. **Stdlib-first, zero dependencies.** A founder reaches the Reflection beat from
   a clean checkout in under five minutes with nothing but Python — no `npm
   install`, no dev server, no build step. This is an explicit M1 lock.
3. **No web/GUI, no LLM in loop (locked).** The browser stack presumes a
   client/server split and a content-generation backend that M1 deliberately
   defers. Building it now would be scaffolding for a slice we are not yet
   shipping.
4. **Reversibility — the real point of the seam.** Choosing terminal is *cheap to
   undo* precisely because nothing renders directly. A browser, TUI, or API
   front-end is later "just another `Renderer`": the core and the engine never
   learn which one is attached. This is the company principle made concrete, and
   it mirrors the cross-project pattern of routing all rendering through one
   content-adapter contract with interchangeable implementations.

## Alternatives considered

- **Browser (React/Next.js).** Rejected for M1: adds a toolchain, a server, and
  non-deterministic rendering for no gate-relevant benefit while the loop has no
  generated content to show. Revisit when there is a player-facing experience
  worth a GUI — it slots in behind `Renderer` without touching the core.
- **A TUI library (curses / Textual / Rich).** Rejected: pulls in a dependency
  (breaks stdlib-first) and trades the trivially-captured text stream for a
  full-screen, harder-to-snapshot surface — friction against the byte-identity
  gate for cosmetics M1 does not need.

## Consequences

- The engine (reducer, reflection, adaptation — future tickets) depends on
  `runtime.WorldView` / `runtime.Renderer`, never on `print` or `sys.stdout`. A
  pre-existing entrypoint that prints directly (`game`, `loop`) is not in scope
  here; new player-facing rendering goes through this seam.
- Tests render against `RecordingRenderer` or a `StringIO`-backed
  `TerminalRenderer`, so no test depends on a console.
- A second platform later is additive: implement `Renderer`, swap it in at
  `boot()`. No core change. If that ever stops being true, this ADR is wrong and
  should be superseded rather than worked around.
