"""Tests for the M1 orchestration loop in :mod:`mirror.loop`.

These pin the founder-brief acceptance contract for the playable slice:
``python -m mirror play --seed 42`` runs Prologue → Act 1 → Recalibration →
Act 2 entry by loading scenes via the loader, appending each beat to the JSONL
log, invoking the single adaptation seam (identity in ``--baseline``), and
rendering Recalibration from :class:`MirrorState`. The tests below assert each
clause individually so a regression points at the specific contract it broke.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from mirror import __main__ as cli
from mirror import loop as mloop
from mirror.intake import seed_state
from mirror.log import ChoiceObserved, EventLog, TurnAdvanced
from mirror.play import load_answers
from mirror.schema import SCHEMA_VERSION, schema_fingerprint
from mirror.state import MirrorState

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED42_FIXTURE = REPO_ROOT / "fixtures" / "seed42_answers.json"
SEED42_AGGRESSION_FIXTURE = REPO_ROOT / "fixtures" / "seed42_answers_aggression.json"


# --- structural: the slice schedule honours the brief's sequence -------------


def test_slice_sequence_matches_the_founder_brief_phases():
    """The slice walks Prologue → Act 1 → Recalibration → Act 2 entry, in order."""
    phases = [b.phase for b in mloop.SLICE]
    # The first run of the same phase appears in the documented order.
    first_seen = []
    for p in phases:
        if p not in first_seen:
            first_seen.append(p)
    assert first_seen == ["prologue", "act1", "recalibration", "act2_entry"]
    # Recalibration is a single beat between Act 1 and Act 2 entry — the M1
    # contract is one Recalibration beat, not several.
    assert phases.count("recalibration") == 1
    assert phases.count("act2_entry") == 1


def test_slice_scene_files_exist_under_scenes_dir():
    """Every scheduled beat names a real ``.scene`` file the loader can read."""
    for beat in mloop.SLICE:
        path = mloop.SCENES_DIR / beat.filename
        assert path.exists(), f"missing scene file for beat {beat}"


# --- the adaptation seam: identity in baseline, re-order otherwise -----------


def test_adapt_is_identity_in_baseline_mode():
    """``baseline=True`` is the structural identity, regardless of state."""
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_01_intake.scene")
    state = MirrorState.new()
    # No state would normally trigger adaptation, but baseline=True must be the
    # identity even with a confident state below.
    assert mloop.adapt(scene, state, baseline=True) is scene


def test_adapt_in_baseline_is_identity_even_with_confident_lean():
    """A confident lean would re-order in adaptive mode; baseline must not."""
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_14_act2_entry.scene")
    # Force a confident, strong cautious lean.
    state = seed_state(load_answers(SEED42_FIXTURE))
    for _ in range(8):
        state.apply_choice(
            __import__("mirror").state.Choice(
                id="x",
                signals=mloop.signals_for_tendency("kindness"),
            )
        )
    # Sanity check: the lean is now well past the confidence floor.
    assert mloop.predict_target_tendency(state) == "kindness"
    # And yet baseline still returns the scene unchanged.
    assert mloop.adapt(scene, state, baseline=True) is scene


def test_adapt_reorders_predicted_tendency_to_the_top():
    """With a confident reckless lean, defiance choices lead in adaptive mode."""
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_14_act2_entry.scene")
    state = seed_state(load_answers(SEED42_AGGRESSION_FIXTURE))
    for _ in range(8):
        state.apply_choice(
            __import__("mirror").state.Choice(
                id="x",
                signals=mloop.signals_for_tendency("defiance"),
            )
        )
    offered = mloop.adapt(scene, state, baseline=False)
    # The first offered choice is one whose tendency matches the prediction.
    assert mloop.predict_target_tendency(state) == "defiance"
    assert offered.choices[0].tendency == "defiance"
    # Re-order only: same choice ids, just permuted.
    assert {c.id for c in offered.choices} == {c.id for c in scene.choices}


def test_adapt_falls_back_to_declared_order_when_no_lean():
    """A blank state yields no prediction; the seam returns the scene unchanged."""
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_01_intake.scene")
    state = MirrorState.new()
    assert mloop.predict_target_tendency(state) is None
    assert mloop.adapt(scene, state, baseline=False) is scene


# --- the policy: deterministic-by-seed, position-biased ----------------------


def test_seeded_policy_is_deterministic_for_a_given_seed():
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_01_intake.scene")
    state = MirrorState.new()
    pa = mloop.seeded_policy(42)
    pb = mloop.seeded_policy(42)
    # Two identical policies given identical inputs return identical choices.
    a = [pa(scene, state, i) for i in range(20)]
    b = [pb(scene, state, i) for i in range(20)]
    assert a == b


def test_seeded_policy_is_position_biased_toward_the_first_offered():
    """The position bias is what makes the seam visible in the trajectory."""
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_01_intake.scene")
    state = MirrorState.new()
    policy = mloop.seeded_policy(0)
    counts = {c.id: 0 for c in scene.choices}
    for i in range(2000):
        counts[policy(scene, state, i)] += 1
    # Heavily over 1/3 share for position 0, well under 1/3 for the last.
    first_id = scene.choices[0].id
    last_id = scene.choices[-1].id
    assert counts[first_id] > 2000 * 0.5, counts
    assert counts[last_id] < 2000 * 0.2, counts


# --- recalibration: rendered from MirrorState --------------------------------


def test_recalibration_summary_handles_blank_state():
    state = MirrorState.new()
    text = mloop.recalibration_summary(state)
    assert "MIRROR // RECALIBRATION" in text
    assert "no clear lean" in text


def test_recalibration_summary_names_the_axes_the_player_leaned_on():
    state = seed_state(load_answers(SEED42_AGGRESSION_FIXTURE))
    # Push the state firmly into reckless / defiant via in-fiction beats.
    for _ in range(10):
        state.apply_choice(
            __import__("mirror").state.Choice(
                id="x",
                signals=mloop.signals_for_tendency("defiance"),
            )
        )
    text = mloop.recalibration_summary(state)
    assert "reckless" in text
    assert "defiant" in text


def test_render_recalibration_prompt_prepends_summary_to_authored_prompt():
    scene = mloop.load_scene(mloop.SCENES_DIR / "act1_13_recalibration.scene")
    state = MirrorState.new()
    rendered = mloop.render_recalibration_prompt(scene, state)
    # Same id and choice set — only the prompt body changes.
    assert rendered.id == scene.id
    assert tuple(c.id for c in rendered.choices) == tuple(c.id for c in scene.choices)
    # The summary line is at the head; the authored prompt follows verbatim.
    assert rendered.prompt.startswith("MIRROR // RECALIBRATION")
    assert scene.prompt in rendered.prompt


# --- play_slice: the end-to-end orchestration --------------------------------


def test_play_slice_walks_every_beat_in_order():
    run = mloop.play_slice(seed=42)
    assert len(run.beats) == len(mloop.SLICE)
    for i, (record, scheduled) in enumerate(zip(run.beats, mloop.SLICE)):
        assert record.beat_index == i
        assert record.phase == scheduled.phase
        # The recorded scene_id is the same one the file declared (the loader's
        # parse pinned the file's `id:` field).
        assert record.scene_id == scheduled.filename.removesuffix(".scene")


def test_play_slice_records_two_events_per_beat_after_intake():
    """Each beat appends exactly one ChoiceObserved + one TurnAdvanced."""
    run = mloop.play_slice(seed=42)
    expected_count = 2 * len(mloop.SLICE)
    assert len(run.log.events) == expected_count
    # Pairs in order: choice, tick, choice, tick, ...
    for i, event in enumerate(run.log.events):
        if i % 2 == 0:
            assert isinstance(event, ChoiceObserved)
        else:
            assert isinstance(event, TurnAdvanced)


def test_play_slice_intake_answers_seed_the_starting_state():
    """With intake_answers, the slice log starts with the intake events."""
    answers = load_answers(SEED42_FIXTURE)
    run = mloop.play_slice(seed=42, intake_answers=answers)
    intake_count = len(answers)
    # The first `intake_count` events are the questionnaire ChoiceObserved
    # records, with the documented intake scene_id.
    intake_events = run.log.events[:intake_count]
    assert all(isinstance(e, ChoiceObserved) for e in intake_events)
    assert all(e.scene_id == "intake_questionnaire" for e in intake_events)


def test_play_slice_is_deterministic_under_a_fixed_seed():
    a = mloop.play_slice(seed=42)
    b = mloop.play_slice(seed=42)
    assert mloop.render_jsonl(a) == mloop.render_jsonl(b)
    # And the underlying log is structurally equal too.
    assert a.log == b.log


def test_play_slice_different_seeds_produce_different_runs():
    a = mloop.play_slice(seed=42)
    b = mloop.play_slice(seed=43)
    # Pick at least one beat where the simulated player chose differently.
    assert [r.actual_choice for r in a.beats] != [r.actual_choice for r in b.beats]


def test_baseline_run_never_reorders_choices():
    """The seam-is-identity property: ``baseline=True`` ⇒ no reordered beats."""
    run = mloop.play_slice(seed=42, baseline=True)
    assert all(not r.reordered for r in run.beats)
    assert all(r.declared_order == r.offered_order for r in run.beats)


def test_adaptive_and_baseline_share_the_same_beat_schedule():
    """Parity: same scene ids, same phase sequence — adaptation is the only diff."""
    adaptive = mloop.play_slice(seed=42)
    baseline = mloop.play_slice(seed=42, baseline=True)
    assert [b.scene_id for b in adaptive.beats] == [b.scene_id for b in baseline.beats]
    assert [b.phase for b in adaptive.beats] == [b.phase for b in baseline.beats]


def test_adaptive_run_reorders_at_least_one_beat_under_seed_42():
    """Pins that the M1 caution/aggression axis actually fires under seed 42."""
    # Seed 42 with no intake still develops a kindness-leaning state after a
    # few beats (the kindness-tagged choice is offered first 60% of the time
    # by the position bias, so confidence rises and the seam re-orders later
    # beats). If the axis weights or confidence floor drift such that this
    # never fires, the adaptation has gone silent on the canonical seed and
    # we want to know.
    run = mloop.play_slice(seed=42)
    assert any(r.reordered for r in run.beats)


def test_recalibration_summary_is_function_of_pre_recalibration_state():
    """The captured summary equals what `recalibration_summary` returns on the
    log reduced up to (but not including) the Recalibration beat — i.e. the
    summary is what the player *was shown*, not what later beats produced."""
    run = mloop.play_slice(seed=42, intake_answers=load_answers(SEED42_FIXTURE))
    recal_index = next(b.beat_index for b in run.beats if b.phase == "recalibration")
    intake_count = len(load_answers(SEED42_FIXTURE))
    # Events before the recalibration beat: intake + 2 per prior beat.
    head = intake_count + 2 * recal_index
    prefix_log = EventLog(events=run.log.events[:head], schema_version=run.log.schema_version, fingerprint=run.log.fingerprint)
    expected = mloop.recalibration_summary(prefix_log.reduce())
    assert run.recalibration_summary == expected


def test_recalibration_beat_renders_summary_into_prompt():
    """The Recalibration beat's *played* scene has the summary in its prompt.

    We can verify this by stubbing the policy with one that captures the
    offered scene; the offered scene is what the simulated player saw.
    """
    seen: list = []

    def capturing_policy(scene, state, beat_index):
        seen.append((beat_index, scene))
        return scene.choices[0].id

    mloop.play_slice(seed=42, policy=capturing_policy)
    recal_index = next(
        i for i, beat in enumerate(mloop.SLICE) if beat.phase == "recalibration"
    )
    _, recal_scene = seen[recal_index]
    assert "MIRROR // RECALIBRATION" in recal_scene.prompt


# --- JSONL: the byte-stable output -------------------------------------------


def test_jsonl_lines_each_parse_as_json():
    """JSONL contract: every line is a self-contained JSON object."""
    run = mloop.play_slice(seed=42)
    for line in mloop.jsonl_lines(run):
        assert line.endswith("\n")
        json.loads(line.rstrip("\n"))


def test_jsonl_starts_with_run_started_header_and_ends_with_run_completed():
    run = mloop.play_slice(seed=42)
    lines = list(mloop.jsonl_lines(run))
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    assert first["event_type"] == "run_started"
    assert first["seed"] == 42
    assert first["baseline"] is False
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["fingerprint"] == schema_fingerprint()
    assert last["event_type"] == "run_completed"
    # The footer carries the rendered Recalibration summary so a JSONL consumer
    # can verify the M1 "Recalibration rendered from MirrorState" property
    # without re-walking the slice.
    assert last["recalibration_summary"] == run.recalibration_summary
    assert last["final_state"] == run.final_state.snapshot()


def test_jsonl_choice_observed_carries_beat_metadata():
    """ChoiceObserved lines carry beat_index/phase/offered_order/etc."""
    run = mloop.play_slice(seed=42)
    lines = [json.loads(line) for line in mloop.jsonl_lines(run)]
    choice_lines = [
        line for line in lines if line.get("event_type") == "choice_observed"
    ]
    # One per beat (intake is off for this test — no intake_answers passed).
    assert len(choice_lines) == len(mloop.SLICE)
    for i, line in enumerate(choice_lines):
        assert line["beat_index"] == i
        assert line["phase"] in {"prologue", "act1", "recalibration", "act2_entry"}
        assert "offered_order" in line
        assert "declared_order" in line


def test_jsonl_keys_are_sorted_within_each_line():
    """Byte-stable: every payload is dumped with ``sort_keys=True``."""
    run = mloop.play_slice(seed=42)
    for line in mloop.jsonl_lines(run):
        obj = json.loads(line)
        keys = list(obj.keys())
        assert keys == sorted(keys)


def test_write_jsonl_to_stream_matches_render_jsonl_string():
    run = mloop.play_slice(seed=42)
    buf = io.StringIO()
    mloop.write_jsonl(run, buf)
    assert buf.getvalue() == mloop.render_jsonl(run)


# --- the log itself: round-trips through the reducer -------------------------


def test_event_log_reduces_to_the_recorded_final_state():
    """The log is the source of truth: re-reducing it equals ``final_state``.

    This is the M1 "byte-identity replay" property at the structural level.
    """
    run = mloop.play_slice(seed=42, intake_answers=load_answers(SEED42_FIXTURE))
    rereduced = run.log.reduce()
    assert rereduced.to_dict() == run.final_state.to_dict()


# --- CLI: ``python -m mirror play [--seed N] [--baseline]`` ------------------


def test_cli_play_with_seed_writes_jsonl_to_stdout(capsys):
    rc = cli.main(["play", "--seed", "42"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    lines = captured.out.splitlines()
    # Header + one ChoiceObserved + one TurnAdvanced per beat + footer.
    assert json.loads(lines[0])["event_type"] == "run_started"
    assert json.loads(lines[-1])["event_type"] == "run_completed"


def test_cli_play_with_baseline_flag_emits_no_reorderings(capsys):
    rc = cli.main(["play", "--seed", "42", "--baseline"])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.splitlines()]
    choice_lines = [line for line in lines if line.get("event_type") == "choice_observed"]
    assert all(not line["reordered"] for line in choice_lines)


def test_cli_play_with_intake_seeds_the_slice(capsys):
    rc = cli.main(["play", "--seed", "42", "--intake", str(SEED42_FIXTURE)])
    assert rc == 0
    captured = capsys.readouterr()
    lines = [json.loads(line) for line in captured.out.splitlines()]
    # Some of the early ChoiceObserved lines are the intake scenes.
    intake_lines = [
        line for line in lines if line.get("scene_id") == "intake_questionnaire"
    ]
    assert intake_lines, "intake events should be present in the slice JSONL"


def test_cli_play_writes_jsonl_to_out_path(tmp_path, capsys):
    out = tmp_path / "slice.jsonl"
    rc = cli.main(["play", "--seed", "42", "--out", str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    # Nothing on stdout when --out is given.
    assert captured.out == ""
    content = out.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert json.loads(lines[0])["event_type"] == "run_started"
    assert json.loads(lines[-1])["event_type"] == "run_completed"


def test_cli_play_with_seed_42_is_byte_identical_across_runs(tmp_path):
    """The byte-identity replay gate at the CLI surface."""
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    cli.main(["play", "--seed", "42", "--out", str(a)])
    cli.main(["play", "--seed", "42", "--out", str(b)])
    assert a.read_bytes() == b.read_bytes()


def test_cli_play_intake_only_mode_preserved(capsys):
    """``--answers`` continues to produce the legacy intake-only JSON output.

    The fixture-capture / CI path. Pins backward compatibility so existing
    pipelines do not silently switch to the slice JSONL when the brief's new
    default kicks in.
    """
    rc = cli.main(["play", "--seed", "42", "--answers", str(SEED42_FIXTURE)])
    assert rc == 0
    captured = capsys.readouterr()
    # The intake mode emits indented canonical JSON (one object), not JSONL.
    payload = json.loads(captured.out)
    assert "events" in payload
    assert "schema_version" in payload


def test_subprocess_play_seed_42_runs_without_tty():
    """The north-star command runs deterministically with stdin closed."""
    result = subprocess.run(
        [sys.executable, "-m", "mirror", "play", "--seed", "42"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert result.stderr == b""
    text = result.stdout.decode("utf-8")
    lines = text.splitlines()
    assert json.loads(lines[0])["event_type"] == "run_started"
    assert json.loads(lines[-1])["event_type"] == "run_completed"


# --- single-impure-module property -------------------------------------------


def test_loop_module_is_the_only_mirror_module_doing_filesystem_io():
    """The brief's "loop.py is the sole impure module" property.

    Spot-checks each :mod:`mirror` source file for calls that read/write the
    filesystem. The legitimate inhabitants of this set are ``mirror.loop``
    (the orchestrator the brief blesses) and the two long-standing utility
    surfaces: ``mirror.play.load_answers`` (CI fixture intake), ``mirror.validate``
    (fixture validator), and ``mirror.__main__`` (CLI argument plumbing). No
    *new* :mod:`mirror` module is allowed to grow filesystem I/O without
    explicit review.
    """
    mirror_pkg = Path(mloop.__file__).parent
    allowed = {"loop.py", "play.py", "validate.py", "__main__.py"}
    io_markers = ("open(", ".read_text(", ".write_text(", ".read_bytes(", ".write_bytes(")
    for path in mirror_pkg.glob("*.py"):
        if path.name in allowed:
            continue
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        for marker in io_markers:
            assert marker not in text, (
                f"{path.name} contains {marker!r} — only "
                f"{sorted(allowed)} are allowed to do filesystem I/O; "
                f"mirror.loop is the sole orchestrator-tier impure module."
            )
