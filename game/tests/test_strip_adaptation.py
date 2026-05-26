"""Adaptation provenance tagging + ``strip_adaptation`` — the parity gate.

The structural ``baseline ≡ adaptive`` parity gate (``docs/adr/0001-m1-locks.md``
§1; ``docs/mirror_loop_m1_synthesis.md``) is the claim that the adaptive arm is
the baseline arm with the adaptation seam enabled — nothing else. These tests
pin the mechanism that makes the claim mechanically checkable from the log
alone:

1. **Provenance tagging is total.** Every loop the adaptation layer emitted or
   mutated content on carries a ``provenance`` block; every loop it did not
   leaves the loop record byte-identical to the baseline's. So the log answers
   "where did the adaptation fire?" without re-running the engine.
2. **The projection is byte-identical.** ``strip_adaptation`` inverts every
   tagged emission/mutation and reverts the ``run`` header's variant, producing
   a JSONL byte-for-byte equal to the fixed (identity) baseline arm's JSONL on
   the same seed and inputs. This is the structural-parity property in
   testable form.
3. **The projection is local.** Stripping is a pure function of the log
   (no engine call, no world look-up beyond a sanity check), idempotent, and a
   no-op on a baseline log that carries no provenance.
"""

from __future__ import annotations

import json

import pytest

from game.replay import (
    CANONICAL_INPUT_LOG,
    DEFAULT_SEED,
    RunResult,
    run,
    strip_adaptation,
)
from game.variants import ADAPTIVE, FIXED
from game.world import DEFAULT_WORLD


# Two contrasting input logs so the property is exercised across actual
# adaptations (a kind player triggers branch selections + a reordering at
# confrontation) and a different lean (a defiant player triggers different
# branches), not only one walk.
DEFIANT_INPUT_LOG = ("c_refuse", "c_breach", "c_doors", "c_walk", "c_break")


# --- the provenance contract: every emission/mutation is tagged ----------------


@pytest.mark.parametrize(
    "input_log",
    [CANONICAL_INPUT_LOG, DEFIANT_INPUT_LOG],
    ids=["kind", "defiant"],
)
def test_every_adaptation_layer_event_carries_a_provenance_tag(input_log):
    # The acceptance contract: "every event the adaptation layer emits or
    # mutates carries a provenance tag". A loop is tagged iff its content was
    # bent by the layer — a non-baseline branch_key or a non-declared offering.
    result = run(DEFAULT_SEED, input_log, variant=ADAPTIVE.name)
    snapshot = result.snapshot()
    for loop in snapshot["loops"]:
        bent = (
            loop["branch_key"] not in ("fixed", "default")
            or loop["offered_order"] != loop["declared_order"]
        )
        assert bent == ("provenance" in loop), (
            f"loop {loop['loop_index']}: bent={bent} but provenance="
            f"{'present' if 'provenance' in loop else 'absent'}"
        )


def test_provenance_block_carries_the_adaptation_records_with_trigger_snapshot():
    # The block re-uses the audited :class:`Adaptation` schema (kind +
    # slot_key + revealed/ordering + provenance), so the log's provenance and
    # the in-memory adaptation log are the same primitive.
    snapshot = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).snapshot()
    records_loop = next(loop for loop in snapshot["loops"] if loop["scene_id"] == "records")
    prov = records_loop["provenance"]
    assert prov["adaptations"][0]["kind"] == "branch_selection"
    assert prov["adaptations"][0]["revealed"] == "kindness"
    assert prov["adaptations"][0]["slot_key"] == "records"
    trigger = prov["adaptations"][0]["provenance"]["trigger_snapshot"]
    # The decision is a function of the *pre-loop* state (one prior choice).
    assert trigger["turn_count"] == 1
    assert trigger["dominant"] == "kindness"


def test_confrontation_reordering_is_logged_as_choice_reordering():
    # The one in-scene re-ordering in the canonical kind walk: confrontation
    # declares kindness last, so a kind player's predicted choice (c_wait) is
    # surfaced first. The tag must reflect that surface, not branch selection.
    snapshot = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).snapshot()
    conf = next(loop for loop in snapshot["loops"] if loop["scene_id"] == "confrontation")
    kinds = [a["kind"] for a in conf["provenance"]["adaptations"]]
    assert kinds == ["choice_reordering"]
    assert conf["provenance"]["adaptations"][0]["ordering"][0] == "c_wait"


def test_baseline_arms_carry_no_provenance():
    # Provenance is the adaptation layer's audit trail; the baseline arms run
    # the same engine with the seam in identity / placebo mode and the layer
    # emits nothing, so its log MUST stay tag-free. This is what keeps the
    # canonical baseline fixture (``m1_canonical.jsonl``) byte-stable.
    for variant in ("fixed", "random"):
        snapshot = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=variant).snapshot()
        for loop in snapshot["loops"]:
            assert "provenance" not in loop, (
                f"variant={variant!r} loop {loop['loop_index']} has provenance"
            )


# --- the projection: byte-identical to the baseline ----------------------------


@pytest.mark.parametrize(
    "input_log",
    [CANONICAL_INPUT_LOG, DEFIANT_INPUT_LOG],
    ids=["kind", "defiant"],
)
def test_strip_adaptation_yields_byte_identical_baseline(input_log):
    # The headline parity claim: an adaptive JSONL log stripped of its
    # adaptation tags is byte-identical to a fixed-baseline JSONL on the
    # same seed and input log. This is the mechanism the parity gate relies on.
    adaptive = run(DEFAULT_SEED, input_log, variant=ADAPTIVE.name).to_jsonl()
    fixed = run(DEFAULT_SEED, input_log, variant=FIXED.name).to_jsonl()
    assert strip_adaptation(adaptive) == fixed


@pytest.mark.parametrize("seed", [0, 1, 42, 9999])
def test_strip_adaptation_holds_across_seeds(seed):
    # The adaptive arm is seed-invariant (content is driven by the player
    # model, not the RNG), and so is its fixed projection; the parity must
    # hold for any seed value the run header echoes back.
    adaptive = run(seed, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    fixed = run(seed, CANONICAL_INPUT_LOG, variant=FIXED.name).to_jsonl()
    assert strip_adaptation(adaptive) == fixed


def test_strip_adaptation_is_idempotent():
    # A baseline log already has no provenance and the run header is already
    # 'fixed', so stripping it is the identity. Stripping the adaptive run
    # twice equals stripping it once, by the same argument.
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    once = strip_adaptation(adaptive)
    assert strip_adaptation(once) == once

    fixed = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=FIXED.name).to_jsonl()
    assert strip_adaptation(fixed) == fixed


def test_strip_adaptation_relabels_only_the_adaptive_variant():
    # The run header's ``variant`` is the one run-level field the seam choice
    # controls; the projection relabels exactly that one and leaves random/
    # fixed alone (so a non-adaptive log is preserved verbatim).
    for variant in ("fixed", "random"):
        log = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=variant).to_jsonl()
        header = json.loads(log.splitlines()[0])
        stripped_header = json.loads(strip_adaptation(log).splitlines()[0])
        assert stripped_header == header


def test_strip_adaptation_preserves_player_model_fields_verbatim():
    # The fields that are pure functions of the player model — prediction,
    # reflection, system message, tendency tally, the action the player took
    # — must pass through unchanged. They are what the locked acceptance gate
    # scores, and the strip projection has no business touching them.
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).snapshot()
    stripped_text = strip_adaptation(
        run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    )
    stripped = [json.loads(line) for line in stripped_text.splitlines()]
    stripped_loops = [r for r in stripped if r.get("type") == "loop"]
    assert len(stripped_loops) == len(adaptive["loops"])
    for raw, projected in zip(adaptive["loops"], stripped_loops):
        for field in (
            "predicted_actions",
            "actual_action",
            "reflection",
            "system_message",
            "tendency_counts",
            "turn_count",
            "loop_index",
            "scene_id",
            "declared_order",
        ):
            assert raw[field] == projected[field], (
                f"loop {raw['loop_index']}: field {field!r} changed under strip"
            )


def test_strip_adaptation_removes_provenance_field_entirely():
    # Byte-identity requires the provenance field be *removed*, not just
    # nulled. An empty provenance block would change the bytes.
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    stripped = strip_adaptation(adaptive)
    for line in stripped.splitlines():
        assert "provenance" not in json.loads(line)


def test_strip_adaptation_is_a_pure_function_of_the_log():
    # The projection takes only text and returns only text; called twice on
    # the same input it produces the same output (no hidden state, no clock,
    # no RNG). A regression that smuggled engine state in would fail here.
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    assert strip_adaptation(adaptive) == strip_adaptation(adaptive)


def test_strip_adaptation_rejects_a_log_against_an_unknown_world():
    # An alien world cannot be re-projected against this build's spine, so
    # the strip must fail loudly rather than emit a not-quite-baseline log.
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    head, *rest = adaptive.splitlines()
    head_dict = json.loads(head)
    head_dict["world"] = "no-such-world"
    bad = "\n".join([json.dumps(head_dict, sort_keys=True, separators=(",", ":"))] + rest) + "\n"
    with pytest.raises(ValueError, match="unknown world"):
        strip_adaptation(bad)


def test_strip_adaptation_tolerates_trailing_blank_lines():
    adaptive = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).to_jsonl()
    fixed = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=FIXED.name).to_jsonl()
    # A log with stray trailing newlines still projects to the same baseline.
    assert strip_adaptation(adaptive + "\n\n") == fixed


# --- threading: provenance reflects the *pre-loop* mirror read -----------------


def test_source_event_seq_equals_pre_loop_turn_count():
    # The decision provenance is "events consumed *before* the decision was
    # taken". For one-choice-per-loop play that is the loop's index, not the
    # post-state turn count — and the snapshot it holds must match.
    snapshot = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name).snapshot()
    for loop in snapshot["loops"]:
        prov = loop.get("provenance")
        if prov is None:
            continue
        for adaptation in prov["adaptations"]:
            seq = adaptation["provenance"]["source_event_seq"]
            assert seq == loop["loop_index"]
            assert adaptation["provenance"]["trigger_snapshot"]["turn_count"] == seq


# --- the JSON form: provenance round-trips through the snapshot ----------------


def test_run_result_json_round_trips_under_adaptive_arm():
    # The snapshot JSON is canonical (sorted keys, trailing newline) regardless
    # of whether provenance fields are present, so the adaptive variant's
    # serialization is stable under reparse + re-serialize.
    result = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name)
    text = result.to_json()
    assert text.endswith("\n")
    reparsed = json.loads(text)
    assert json.dumps(reparsed, indent=2, sort_keys=True) + "\n" == text
    # And the snapshot's loops carry provenance entries (this is the adaptive
    # arm, after all) — at minimum on the records branch.
    assert any("provenance" in loop for loop in reparsed["loops"])


def test_run_result_emits_real_run_result_instance():
    result = run(DEFAULT_SEED, CANONICAL_INPUT_LOG, variant=ADAPTIVE.name)
    assert isinstance(result, RunResult)
    assert result.world_name == DEFAULT_WORLD.name
