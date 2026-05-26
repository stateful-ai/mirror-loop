"""Pins the session-objective decision (``docs/SESSION.md``) to the code.

The decision doc names what a session is, the structural end condition (the
spine is exhausted, exactly once), and three diegetic outcomes (win / lose /
exhaust) read off the closing readout's bands. These tests assert each of those
claims against the real ``play_session`` runner, the shipped world, and the
locked predictability gate so the doc cannot quietly drift from the engine.

The boundary numbers used here are deliberately read from their single sources
of truth (``acceptance.predictability`` for the gate, ``game.templates`` for the
bands) rather than retyped — the doc's promise is that the boundaries are
*reused*, not redefined, and that is what is being pinned.
"""

from __future__ import annotations

from acceptance.predictability import MIN_TOP1_ACCURACY
from game.session import (
    MAX_LOOPS,
    MIN_LOOPS,
    erratic_policy,
    persona_policy,
    play_session,
)
from game.templates import final_report
from game.world import DEFAULT_WORLD


# --- §1  What a session is: one walk of the fixed spine ------------------------


def test_session_target_is_three_to_five_loops():
    # The doc states the target as MIN_LOOPS=3, MAX_LOOPS=5. The runner asserts
    # the bound; pin the constants here so the doc number cannot drift.
    assert (MIN_LOOPS, MAX_LOOPS) == (3, 5)


def test_shipped_world_is_the_five_loop_spine_intake_to_exit():
    assert DEFAULT_WORLD.length == 5
    assert MIN_LOOPS <= DEFAULT_WORLD.length <= MAX_LOOPS
    # The doc names the spine explicitly; pin the slot keys and their order.
    assert tuple(s.key for s in DEFAULT_WORLD.slots) == (
        "intake",
        "records",
        "corridor",
        "confrontation",
        "exit",
    )


# --- §3  Structural end: the spine is walked, exactly once, with is_finale at exit ---


def test_structural_end_is_exhausting_the_spine():
    # The only termination condition v0 has: every slot is played, in order, once.
    session = play_session(persona_policy("kindness"))
    assert session.loop_count == DEFAULT_WORLD.length
    assert [r.declared.id for r in session.records] == [
        "intake",
        "records",
        "corridor",
        "confrontation",
        "exit",
    ]


def test_every_persona_completes_the_full_spine_with_no_early_termination():
    # No choice in any slot ends the run early (§4). Each persona reaches `exit`.
    policies = {
        "kindness": persona_policy("kindness"),
        "control": persona_policy("control"),
        "defiance": persona_policy("defiance"),
        "erratic": erratic_policy(),
    }
    for label, policy in policies.items():
        session = play_session(policy)
        assert session.loop_count == DEFAULT_WORLD.length, label
        assert session.records[-1].declared.id == "exit", label


# --- §3  Three diegetic outcomes: win / lose / exhaust, read off the bands ----


def test_lose_outcome_at_or_above_the_locked_gate():
    # LOSE (captured): top-1 >= MIN_TOP1_ACCURACY (= 0.60). The Mirror's model
    # has won the session; the readout reads HIGH confidence, LOW drift,
    # escape "improbable".
    assert MIN_TOP1_ACCURACY == 0.60
    report = final_report(hits=3, total=5, accuracy=MIN_TOP1_ACCURACY, dominant="kindness")
    assert "MODEL CONFIDENCE     : HIGH" in report
    assert "AGENCY DRIFT         : LOW" in report
    assert "ESCAPE               : improbable" in report


def test_exhaust_outcome_in_the_middle_band():
    # EXHAUST (ambiguous): 0.40 <= top-1 < 0.60. The spine ran out before either
    # side proved; the readout reads MODERATE/ELEVATED, escape "plausible".
    for accuracy in (0.40, 0.50, 0.59):
        report = final_report(hits=0, total=5, accuracy=accuracy, dominant="control")
        assert "MODEL CONFIDENCE     : MODERATE" in report, accuracy
        assert "AGENCY DRIFT         : ELEVATED" in report, accuracy
        assert "ESCAPE               : plausible" in report, accuracy


def test_win_outcome_below_the_escape_floor():
    # WIN (escape): top-1 < 0.40. The player slipped the model; the readout
    # reads LOW confidence, HIGH drift, escape "open".
    for accuracy in (0.0, 0.20, 0.39):
        report = final_report(hits=0, total=5, accuracy=accuracy, dominant="defiance")
        assert "MODEL CONFIDENCE     : LOW" in report, accuracy
        assert "AGENCY DRIFT         : HIGH" in report, accuracy
        assert "ESCAPE               : open" in report, accuracy


def test_outcome_boundaries_partition_the_unit_interval():
    # The three bands must be disjoint and cover [0, 1]: every possible
    # top-1 score resolves into exactly one of win / lose / exhaust. Reading
    # the boundaries from the readout itself keeps this honest if templates
    # ever drift.
    seen_escapes: set[str] = set()
    for accuracy in (0.0, 0.10, 0.39, 0.40, 0.50, 0.59, 0.60, 0.80, 1.0):
        report = final_report(hits=0, total=10, accuracy=accuracy, dominant="kindness")
        escape_line = next(
            line for line in report.splitlines() if line.lstrip().startswith("ESCAPE")
        )
        seen_escapes.add(escape_line.split(":", 1)[1].strip())
    assert seen_escapes == {"improbable", "plausible", "open"}


# --- §5  Same log feeds the DoD AND the A/B metric, with no translation -------


def test_completed_session_emits_a_gate_compatible_log():
    # The DoD's "complete a short session" produces a log the A/B metric scores
    # without translation: one decision point per loop, ready for the gate.
    session = play_session(persona_policy("kindness"))
    log = session.session_log()
    assert log["decision_points"], "a completed session must emit decision points"
    assert len(log["decision_points"]) == session.loop_count
    # The log carries the variant label so the per-session unit stays
    # self-identifying when the A/B harness pools it (PLAYTEST_METHOD.md §4).
    assert "variant" in log
