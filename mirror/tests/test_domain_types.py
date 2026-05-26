"""The frozen domain-types index: Event · MirrorState · Scene · Adaptation.

The M1 architecture (``docs/SCHEMAS.md``) freezes four versioned, serializable
types as the contract everything else reduces and records against. This test
pins three claims about the index:

1. Each type is **defined once** — re-exporting ``mirror.schema.X`` returns the
   *same* class object as importing ``X`` from its canonical module. Anyone who
   redefines one will see this test fail.
2. The four consumers named in the acceptance criterion (serialization, scene
   loader, reducer, reflection) import these canonical types and do not
   shadow them with local redefinitions.
3. Each type has a **symmetric encode/decode round-trip** through the canonical
   serialization for its medium (JSON for Event/MirrorState/Adaptation; the
   ``.scene`` text format for Scene). Round-trip exactness is what makes the
   "log is the source of truth" rule operational — a recorded session must
   reload into byte-equivalent state.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import mirror.schema as schema_module


# --- 1. Each type is defined once, re-exported from mirror.schema -----------


def test_event_is_re_exported_as_the_canonical_union():
    from mirror.log import MirrorEvent

    assert schema_module.Event is MirrorEvent


def test_mirrorstate_is_re_exported_as_the_canonical_class():
    from mirror.state import MirrorState

    assert schema_module.MirrorState is MirrorState


def test_scene_is_re_exported_as_the_canonical_class():
    from loop.core import Scene

    assert schema_module.Scene is Scene


def test_adaptation_is_re_exported_as_the_canonical_class():
    from game.adaptation import Adaptation

    assert schema_module.Adaptation is Adaptation


def test_unknown_attribute_on_mirror_schema_still_raises():
    # The lazy __getattr__ must only resolve the named domain types, not be a
    # silent re-export of arbitrary symbols.
    with pytest.raises(AttributeError):
        schema_module.NotADomainType  # noqa: B018


def test_dir_includes_the_canonical_domain_types():
    listed = set(dir(schema_module))
    assert {"Event", "MirrorState", "Scene", "Adaptation"} <= listed


# --- 2. Consumers import canonical, do not redefine ---------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]


def _module_redefines(path: Path, names: set[str]) -> set[str]:
    """Return the names from ``names`` that ``path`` defines as a class.

    Walks the AST so an import (`from x import Scene`) does *not* count as a
    definition; only a `class Scene: ...` or `Scene = <other class>` at
    module top level does.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in names:
            found.add(node.name)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found.add(target.id)
    return found


# Each row is (consumer module path, the canonical-module path that *is*
# allowed to define each name). A consumer is any module the acceptance
# criterion names as needing to import these types.
_CONSUMERS = (
    # serialization
    REPO_ROOT / "mirror" / "log.py",
    # scene loader
    REPO_ROOT / "game" / "scenes" / "loader.py",
    # reducer
    REPO_ROOT / "mirror" / "log.py",
    # reflection (the legibility beat — Mirror.reflect lives in loop/core.py,
    # which is the *canonical* module for Scene, so it owns the definition; the
    # check below excludes that one self-definition.)
    REPO_ROOT / "loop" / "core.py",
    # session-level persistence consumes Scene/Choice via loop.core too
    REPO_ROOT / "loop" / "session.py",
    # adaptation seam consumes Adaptation/MirrorState
    REPO_ROOT / "game" / "adapt.py",
)

_CANONICAL = {
    "Event": REPO_ROOT / "mirror" / "log.py",       # MirrorEvent lives here
    "MirrorState": REPO_ROOT / "mirror" / "state.py",
    "Scene": REPO_ROOT / "loop" / "core.py",
    "Adaptation": REPO_ROOT / "game" / "adaptation.py",
}


def test_no_consumer_redefines_a_canonical_domain_type():
    # ``Event`` shows up under that bare name only as the lazy re-export in
    # mirror.schema; the canonical definition is the ``MirrorEvent`` union in
    # mirror.log. So the per-name redefinition check uses the type's canonical
    # *class* name.
    canonical_names = {"MirrorEvent", "MirrorState", "Scene", "Adaptation"}
    offenders: list[str] = []
    for path in _CONSUMERS:
        # The canonical module is allowed (and required) to define its own
        # types; skip it for the name it owns.
        allowed = set()
        for name, owner in _CANONICAL.items():
            real_name = "MirrorEvent" if name == "Event" else name
            if path == owner:
                allowed.add(real_name)
        redefined = _module_redefines(path, canonical_names) - allowed
        for name in redefined:
            offenders.append(f"{path.relative_to(REPO_ROOT)} redefines {name!r}")
    assert offenders == [], "consumer module(s) shadowed a canonical type:\n" + "\n".join(
        offenders
    )


def _imports_from(path: Path, module: str, name: str) -> bool:
    """True iff ``path`` contains a top-level ``from <module> import ... <name> ...``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            for alias in node.names:
                if alias.name == name:
                    return True
    return False


def test_scene_loader_imports_scene_via_the_mirror_schema_index():
    # The scene loader is the one "consumer role" named in the M1 acceptance
    # criteria that is *not* a canonical owner — serialization, reducer, and
    # reflection all live in modules that themselves define one of the four
    # types (and so can't import via the lazy index without a circular import).
    # Pinning the loader to ``from mirror.schema import Scene`` proves the
    # index is the single discoverable path in practice, not just on paper.
    loader = REPO_ROOT / "game" / "scenes" / "loader.py"
    assert _imports_from(loader, "mirror.schema", "Scene"), (
        f"{loader.relative_to(REPO_ROOT)} must import Scene from mirror.schema "
        "(the frozen domain-types index), not from its canonical definition module"
    )


# --- 3. Per-type encode/decode round-trip ------------------------------------


def test_event_choice_observed_encode_decode_round_trip():
    from mirror.log import ChoiceObserved, event_from_dict, event_to_dict
    from mirror.state import Signal

    event = ChoiceObserved(
        choice_id="inspect_exit",
        signals=(
            Signal.toward("boundary_testing", 1.0),
            Signal.spend("playstyle_mix", "exploration"),
        ),
        scene_id="lab_observation_room",
        act_id="act_1",
    )
    assert event_from_dict(json.loads(json.dumps(event_to_dict(event)))) == event


def test_event_turn_advanced_encode_decode_round_trip():
    from mirror.log import TurnAdvanced, event_from_dict, event_to_dict

    event = TurnAdvanced()
    assert event_from_dict(json.loads(json.dumps(event_to_dict(event)))) == event


def test_mirrorstate_encode_decode_round_trip():
    from mirror.state import Choice, MirrorState, Signal

    state = MirrorState.new()
    state.apply_choice(Choice("c", signals=(
        Signal.toward("authority_trust", -1.0),
        Signal.spend("playstyle_mix", "conversation"),
        Signal.toward("frustration", 1.0, weight=0.5),
    )))
    state.tick()
    state.apply_choice(Choice("d", signals=(Signal.toward("curiosity", 1.0),)))

    restored = MirrorState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored == state


def test_scene_encode_decode_round_trip():
    # Scene's canonical serialization is the ``.scene`` text format; the
    # encode/decode pair is ``dumps_scene`` / ``loads_scene``.
    from game.scenes import dumps_scene, loads_scene
    from loop.core import Choice, Scene

    scene = Scene(
        id="records",
        prompt="The records room is quiet.\n\nA single light hums.",
        choices=(
            Choice(
                id="c_read",
                text="Read the open file on the desk.",
                tendency="kindness",
                evidence="read the open file",
            ),
            Choice(
                id="c_close",
                text="Close the file without reading.",
                tendency="control",
                evidence="closed the file without reading",
            ),
        ),
    )
    assert loads_scene(dumps_scene(scene)) == scene


def test_adaptation_encode_decode_round_trip():
    from game.adaptation import Adaptation
    from loop.core import Choice, PlayerState, Turn

    state = PlayerState(history=(
        Turn(scene_id="s0", choice=Choice("c0", "t", "kindness", "did a thing")),
        Turn(scene_id="s1", choice=Choice("c1", "t", "kindness", "did a thing again")),
    ))
    branch = Adaptation.branch_selection(
        "records", "kindness", state=state, source_event_seq=2
    )
    reorder = Adaptation.choice_reordering(
        "confrontation", ("c_wait", "c_walk"), state=state, source_event_seq=2
    )
    for adaptation in (branch, reorder):
        restored = Adaptation.from_dict(json.loads(json.dumps(adaptation.to_dict())))
        assert restored == adaptation
