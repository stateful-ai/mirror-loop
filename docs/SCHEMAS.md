# Mirror Loop — The Frozen Schema Set (Event · MirrorState · WorldState · Adaptation)

**Status:** Defined (M1 step 2 — "Freeze schemas") · **Date:** 2026-05-25 ·
**Scope:** the versioned, serializable types the rest of the build reduces and
records against, and the version policy that keeps a recorded session replayable.

> The M1 execution plan makes schema-freeze a serial gate before the parallel
> adaptation-seam and content work: *"Freeze schemas: Event, MirrorState,
> WorldState, Adaptation, AdaptationProvenance."* This document is the index of
> that set. Two of the five already shipped (Event, MirrorState); this doc adds
> **WorldState** and **Adaptation / AdaptationProvenance** and states the version
> policy they all share. Every field is documented in code; the tables below are
> the map, not the source of truth.

---

## 0. The architecture the schemas serve

One locked rule governs all of them (company memory; `docs/MIRROR_SCHEMA.md` §6):

> The append-only **event log is the only source of truth**. The Mirror *and* the
> world-state are **pure reductions** over it; no derived state is ever the
> authority.

with one deliberate companion rule:

> Raw events, the derived Mirror projection, and the player-facing Reflection beat
> are **separate primitives**, and the Reflection beat may render only from
> **stored adaptation provenance**, never recomputation.

So: events are recorded; MirrorState and WorldState are *recomputed* from them and
never persisted as authoritative; and an Adaptation is *recorded* at the instant
it is made (it is not a reduction — it captures a decision plus what drove it).

---

## 1. Event — what the player did (already shipped)

`mirror/log.py`. The append-only facts a session records, exactly two, one per
state transition in `mirror/state.py`:

| Event | Fields | Effect when reduced |
|-------|--------|---------------------|
| `ChoiceObserved` | `choice_id`, `signals`, `scene_id?`, `act_id?` | applies the choice's signals to the Mirror; advances the world by one slot |
| `TurnAdvanced` | — | relaxes every STATE axis one step; does **not** move the world |

Records *inputs* (signals), never *outputs* (the resulting values). Container:
`EventLog` (`events`, `schema_version`, `fingerprint`).

## 2. MirrorState — the player model (already shipped)

`mirror/schema.py` (the static eight-axis schema) + `mirror/state.py` (the runtime
values). A pure reduction of the event log; see `docs/MIRROR_SCHEMA.md`. The v0
adaptation reads a single categorical projection of this model — the dominant
*tendency* (`docs/ADAPTATION.md` §2).

## 3. WorldState — where the player is (new)

`game/worldstate.py`. A pure reduction of the **same** event log into the player's
position in the handcrafted spine (`game/world.py`).

| Type | Field | Meaning |
|------|-------|---------|
| `WorldState` | `world_name` | which world this is a position within (self-describing) |
| | `position` | loops completed = slots advanced = index of the next slot |
| | `visited` | one `VisitedSlot` per completed loop, in order |
| `VisitedSlot` | `slot_key` | the spine slot key this loop resolved to |
| | `choice_id` | the choice the player made there |

`WorldState.reduce(world, events)` folds `ChoiceObserved` events (one per slot, in
order; `TurnAdvanced` skipped) and **fails loudly** on a log that overruns the
spine or whose `scene_id` disagrees with the slot it landed on.

## 4. Adaptation / AdaptationProvenance — what the Mirror did (new)

`game/adaptation.py`. The recorded, auditable schema for one content decision.
The prototype ships one adaptation *type* (tendency mirroring) with two surfaces,
distinguished by `kind`; both serialize through one record.

| Type | Field | Meaning |
|------|-------|---------|
| `Adaptation` | `kind` | `BRANCH_SELECTION` (which framing revealed) or `CHOICE_REORDERING` (predicted choice first) |
| | `slot_key` | the slot/scene acted on |
| | `revealed` | branch key revealed (BRANCH_SELECTION); `None` otherwise |
| | `ordering` | resulting choice-id order, predicted-first (CHOICE_REORDERING); `()` otherwise |
| | **`provenance`** | **required** — the trigger snapshot + source event-seq |
| `AdaptationProvenance` | `source_event_seq` | count of log events the decision was reduced from; replay `events[:seq]` to recover the state it saw |
| | `trigger_snapshot` | the `MirrorSnapshot` read at that seq |
| `MirrorSnapshot` | `turn_count`, `tendency_counts`, `dominant` | the v0 one-axis read the decision was a function of |

**The acceptance contract — enforced, not asserted in prose:** every `Adaptation`
records its **trigger Mirror snapshot** and its **source event-seq**.
`provenance` has no default, so an un-provenanced adaptation cannot be
constructed (`game/tests/test_adaptation.py`). `AdaptationLog` is the append-only
container of these records — the "stored adaptation provenance" the Reflection
beat is allowed to render from.

---

## 5. Version policy (shared)

Each schema carries an independent version stamped into its serialized form, and a
load **refuses** an unknown version rather than silently mis-restoring:

| Schema | Constant | Stamped on |
|--------|----------|-----------|
| Event / MirrorState | `mirror.schema.SCHEMA_VERSION` (+ `schema_fingerprint()`) | `EventLog` |
| WorldState | `game.worldstate.WORLDSTATE_SCHEMA_VERSION` | `WorldState.to_dict` |
| Adaptation | `game.adaptation.ADAPTATION_SCHEMA_VERSION` | `AdaptationLog.to_dict` |
| Canonical JSONL stream | `game.replay.JSONL_SPEC_VERSION` | the `run` header in `RunResult.to_jsonl` |

Bump a version on **any incompatible change** to that schema's serialized shape (a
new/removed/renamed field, a changed enum value, a changed snapshot shape). The
Mirror schema additionally carries a structural *fingerprint*, so a schema that
drifts **without** a version bump is still caught at reduce time — the one way a
"deterministic recompute" could silently disagree with the log it replays.

---

## 6. Canonical JSONL spec — the seeded byte-identity contract

The M1 founder brief locks the runtime spine as *"events (append-only JSONL) →
reducer → MirrorState → render"*. `game.replay.RunResult.to_jsonl` is that
spine's canonical serialization, and `fixtures/m1_canonical.jsonl` is the
committed byte-identity gate it replays against. The contract three properties
hold over:

1. **Same-seed byte-identity.** Two runs of the same `(seed, input_log,
   variant, world)` — in any process, under any `PYTHONHASHSEED` — produce
   byte-identical JSONL.
2. **No wall-clock in the JSONL.** Recorded by what the spec deliberately
   *omits* (no timestamps), and enforced upstream by the AST scan in
   `game/tests/test_replay.py::test_runtime_packages_have_no_clock_or_unsynced_randomness`
   that forbids `time`/`datetime`/`secrets`/`uuid` from the runtime packages.
3. **Insertion-order perturbation leaves canonical bytes unchanged.** The
   serializer is `sort_keys=True` so the bytes depend on the field *set*,
   not the dict's insertion order — a Python build whose dict iteration
   order shifts (or a contributor who rebuilds a record with fields in a
   different order) cannot move the bytes.

Three pinned mechanisms make those properties testable per-line, not only at
the whole-file level:

- **`canonical_dumps(record)`** is the only encoder allowed on this spine.
  It pins `sort_keys=True`, compact `(",", ":")` separators, and
  `allow_nan=False` (NaN/Infinity have no canonical JSON encoding and would
  silently emit non-roundtripping JS-only tokens; the encoder raises
  instead). Finite floats roundtrip through Python's shortest-repr, which
  is platform-independent, so a future field carrying a confidence value
  stays byte-identical across hosts.

- **`event_seq`** — a monotonic 0-based logical clock, one increment per
  record across the whole stream (header → loops → trailer). It is the
  position handle a replay reader can use without depending on line
  numbering or stream boundaries, and is the "no wall-clock" property
  expressed as a positive obligation: there *is* a clock, it just isn't the
  wall.

- **`event_id`** — a content-addressable hash (SHA-256 truncated to 16 hex
  chars) of the rest of the record's canonical bytes (the record minus
  `event_id` itself). Two runs of the same inputs produce per-line-identical
  ids; a drift in any single field is localized to the one line whose id
  moved. After `strip_adaptation` reverts an adaptive log's mutations, the
  stripped record's bytes equal the fixed-baseline arm's bytes, so its
  recomputed `event_id` matches too — which is what makes the structural
  parity gate mechanical on a per-line basis.

The `JSONL_SPEC_VERSION` constant is versioned independently of
`SCHEMA_VERSION` (the JSON-snapshot version) because the two serializations
serve different consumers — bumping one does not force the other.
