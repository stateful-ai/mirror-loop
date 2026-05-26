"""Pins the README "Try it" block to runnable behavior.

The M1 founder brief defines DoD §7: *"README 'Try it' block names the two
commands; founder cold-run reaches Reflection in < 5 min."* The block lives at
the top of [`README.md`](../../README.md). These tests guarantee three things:

1. The block exists, is reachable above the design content, and names the two
   commands verbatim.
2. The two commands actually run end-to-end from a clean checkout (no install,
   no extra args) and visibly produce the Reflection beat the README promises.
3. The block's promise that the Reflection lands at **loop 3** is true of the
   shipped spine, so the section can't drift from the engine.

A failure here means a founder following only the README would not reach the
Reflection beat — i.e. the acceptance criterion itself has been broken.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from game.__main__ import main

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"

# The two commands the founder brief calls out. The README must name these
# verbatim; the tests below also execute them to keep the README honest.
ADAPTIVE_CMD = "python -m game"
BASELINE_CMD = "python -m game --variant fixed"

# The Reflection line the founder sees at Recalibration when they pick kindness
# three loops in a row. Stable enough to pin: it's the canonical example used
# across docs/CORE_LOOP.md §4 and docs/core_loop_feel.md §4.
REFLECTION_CLAIM = "Mirror noticed: you chose kindness in 3 of 3 moments so far."


def _try_it_section() -> str:
    """Return the "## Try it" section of the README (header to next ##)."""
    text = README.read_text(encoding="utf-8")
    match = re.search(
        r"^## Try it\n(.*?)(?=^## )", text, flags=re.MULTILINE | re.DOTALL
    )
    assert match is not None, "README is missing a '## Try it' section"
    return match.group(0)


# --- The block exists, sits at the top, and names the two commands ----------


def test_readme_has_a_try_it_section():
    _try_it_section()  # raises if absent


def test_try_it_is_above_the_design_content_so_a_founder_sees_it_first():
    # The block must precede the long design narrative, or "follow only the
    # README" doesn't get the founder to a runnable command in time.
    text = README.read_text(encoding="utf-8")
    try_it = text.index("## Try it")
    for later_section in ("## Core Premise", "## Design Thesis", "## MVP Goal"):
        assert try_it < text.index(later_section), (
            f"'## Try it' must appear before '{later_section}' so the "
            "founder reaches a runnable command before the design content."
        )


def test_try_it_names_both_canonical_commands_verbatim():
    section = _try_it_section()
    assert ADAPTIVE_CMD in section, f"missing adaptive command {ADAPTIVE_CMD!r}"
    assert BASELINE_CMD in section, f"missing baseline command {BASELINE_CMD!r}"


def test_try_it_promises_the_reflection_at_recalibration():
    # The block must tell the founder what to feel at Recalibration: the
    # Reflection beat, by name, anchored to that moment — not just a generic
    # "play the game and see what happens."
    section = _try_it_section()
    assert "Reflection" in section
    assert "Recalibration" in section
    # And it must name the actual claim line the founder will see, so the
    # promise survives a casual scan of the README on a clean checkout.
    assert REFLECTION_CLAIM in section


# --- The two commands actually run and reach the Reflection beat ------------


def _five_kindness_choices() -> io.StringIO:
    # The README tells the founder to pick `1` three times to reach Reflection;
    # the spine is five loops, so we feed five `1`s so the run completes cleanly.
    return io.StringIO("1\n1\n1\n1\n1\n")


def test_adaptive_command_reaches_the_reflection_beat(monkeypatch, capsys):
    # `python -m game` with five `1` choices on stdin: the founder's path.
    monkeypatch.setattr("sys.stdin", _five_kindness_choices())
    assert main([]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert REFLECTION_CLAIM in combined, (
        "the adaptive command did not produce the Reflection line the README promises"
    )
    # The README also promises the visible adaptation on the next loop — pin it
    # so the "first variant adapts to that read" sentence stays honest. The
    # interactive shell emits the live-feedback form of this line, which is the
    # one quoted in the README.
    assert "the Mirror had moved" in combined and "it expected that choice" in combined


def test_baseline_command_reaches_the_reflection_beat_but_does_not_adapt(
    monkeypatch, capsys
):
    # `python -m game --variant fixed`: same UX, same Reflection, no re-ordering.
    monkeypatch.setattr("sys.stdin", _five_kindness_choices())
    assert main(["--variant", "fixed"]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert REFLECTION_CLAIM in combined, (
        "the baseline command did not produce the Reflection line the README promises"
    )
    # The README's contrast claim: baseline does *not* adapt. The fixed variant
    # never re-orders, so the live-feedback "moved" line must not appear.
    assert "the Mirror had moved" not in combined


# --- The block's structural claim: Reflection fires on loop 3 ---------------


def test_reflection_lands_on_loop_three_so_the_block_stays_truthful(
    monkeypatch, capsys
):
    monkeypatch.setattr("sys.stdin", _five_kindness_choices())
    assert main([]) == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err

    # The loop banner immediately preceding the Reflection claim must be loop 3
    # — that is what the README block tells the founder to expect.
    claim_pos = text.index(REFLECTION_CLAIM)
    preceding = text[:claim_pos]
    loop_markers = re.findall(r"LOOP (\d+)", preceding)
    assert loop_markers, "no LOOP marker appeared before the Reflection claim"
    assert loop_markers[-1] == "3", (
        f"Reflection beat must fire on loop 3 (Recalibration), saw loop {loop_markers[-1]}"
    )
