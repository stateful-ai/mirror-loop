"""Tests for the player-facing reflection render over MirrorState.

The two contracts being pinned:

- ``mirror/reflection.py`` is pure: it imports no IO modules and exposes only
  ``render(MirrorState) -> str``. This is why the Reflection beat can sit on a
  separate seam from the rest of the runtime (``docs/ADAPTATION.md`` §4).
- The rendered line names the **dominant** confidently-known axis using the
  axis's own pole/mode wording (player-facing language from the schema), and
  refuses to speak about unobserved neutrals.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mirror.reflection import NO_LEAN_LINE, render
from mirror.state import Choice, MirrorState, Signal


# --- the purity acceptance: this module imports no IO -------------------------


# Modules whose presence in ``import``s would mean this render touches IO,
# globals, or the outside world. ``json`` is intentionally not here — it is pure
# data manipulation, and excluding it would over-constrain the module.
_FORBIDDEN_IMPORT_ROOTS = frozenset({
    "os",
    "io",
    "sys",
    "pathlib",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "ftplib",
    "shutil",
    "tempfile",
    "logging",
    "fileinput",
    "requests",
    "httpx",
})


def test_module_imports_no_io():
    src_path = pathlib.Path(__file__).resolve().parent.parent / "reflection.py"
    tree = ast.parse(src_path.read_text())
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imported_roots.add(node.module.split(".")[0])
    leaked = imported_roots & _FORBIDDEN_IMPORT_ROOTS
    assert not leaked, f"reflection.py must not import IO modules: {sorted(leaked)}"


# --- snapshot: nothing observed → the render says so plainly ------------------


def test_fresh_state_renders_no_lean_line():
    assert render(MirrorState.new()) == NO_LEAN_LINE


def test_inert_choices_keep_render_at_no_lean():
    state = MirrorState.new()
    for _ in range(5):
        state.apply_choice(Choice("narrative_beat", signals=()))
        state.tick()
    assert render(state) == NO_LEAN_LINE


# --- snapshots: each kind renders the right pole/mode wording -----------------


def _state_for(signals_factory, repeats: int = 8) -> MirrorState:
    state = MirrorState.new()
    for _ in range(repeats):
        state.apply_choice(Choice("c", signals=signals_factory()))
    return state


def test_snapshot_bipolar_low_pole_defiant():
    state = _state_for(lambda: (Signal.toward("authority_trust", -1.0),))
    assert render(state) == "Mirror noticed: you read as defiant / distrustful."


def test_snapshot_bipolar_high_pole_deferential():
    state = _state_for(lambda: (Signal.toward("authority_trust", 1.0),))
    assert render(state) == "Mirror noticed: you read as deferential / trusting."


def test_snapshot_unit_high_pole_probing():
    state = _state_for(lambda: (Signal.toward("curiosity", 1.0),))
    assert render(state) == "Mirror noticed: you read as probing."


def test_snapshot_unit_low_pole_incurious():
    state = _state_for(lambda: (Signal.toward("curiosity", 0.0),))
    assert render(state) == "Mirror noticed: you read as incurious."


def test_snapshot_distribution_mode_combat():
    state = _state_for(lambda: (Signal.spend("playstyle_mix", "combat"),))
    assert render(state) == "Mirror noticed: you read as combat."


# --- the anti-mush guarantee: an unobserved neutral never gets named ----------


def test_unobserved_axes_at_neutral_are_never_the_lean():
    """Even when one axis is confidently observed at its neutral, the render
    names some *other* axis with a real lean — never the confident-but-neutral
    one. (Neutral-with-confidence is the textbook way mush sneaks into a
    spoken observation.)"""
    state = MirrorState.new()
    # Drive moral_consistency with signals that target its neutral so the axis
    # accumulates evidence (confidence rises) while the value never leaves 0.5.
    # The axis ends confident *and* leaning nowhere — the exact mush shape we
    # want the render to refuse to name.
    for _ in range(20):
        state.apply_choice(
            Choice("at_neutral", signals=(Signal.toward("moral_consistency", 0.5),))
        )
    # Also evidence a different axis so there is *something* to name.
    for _ in range(6):
        state.apply_choice(
            Choice("defy", signals=(Signal.toward("authority_trust", -1.0),))
        )
    assert state.readings["moral_consistency"].confidence > 0.9
    assert state.readings["moral_consistency"].value == pytest.approx(
        0.5, abs=1e-3
    )
    rendered = render(state)
    assert "principled" not in rendered
    assert "erratic" not in rendered
    assert rendered == "Mirror noticed: you read as defiant / distrustful."


# --- determinism: ties resolve to a stable axis -------------------------------


def test_tie_breaks_by_schema_declaration_order():
    """When two axes have identical lean-strength, the earlier-declared axis
    wins. ``authority_trust`` is declared before ``risk_tolerance`` in the
    schema, so it should be the one that speaks."""
    state = MirrorState.new()
    # Same kind, same learning_rate, same halflife, same number of full-weight
    # signals → identical confidence and identical |value|.
    choice = Choice(
        "twin",
        signals=(
            Signal.toward("authority_trust", -1.0),
            Signal.toward("risk_tolerance", -1.0),
        ),
    )
    for _ in range(8):
        state.apply_choice(choice)
    assert (
        state.readings["authority_trust"].confidence
        == state.readings["risk_tolerance"].confidence
    )
    assert state.readings["authority_trust"].value == pytest.approx(
        state.readings["risk_tolerance"].value
    )
    assert render(state) == "Mirror noticed: you read as defiant / distrustful."


def test_render_is_deterministic_across_calls():
    state = _state_for(lambda: (Signal.toward("authority_trust", -1.0),))
    assert render(state) == render(state)


# --- the public surface is just ``render`` ------------------------------------


def test_public_surface_is_one_function():
    import mirror.reflection as mod

    assert callable(mod.render)
    assert mod.__all__ == ["render"]
